# -*- coding:  utf-8 -*-
"""GhostHand CDP 驱动器 —— 把拟人"计划"变成 trusted 输入事件。

为什么必须走 CDP Input 域
========================
现代前端（React 受控输入、滑块验证码、reCAPTCHA）只认真实输入事件：
JS 页面内 ``dispatchEvent(new MouseEvent('click'))`` 是 untrusted，
``isTrusted=false``，React 的 onChange / 合成事件体系经常不响应
（本地踩坑记录：Fiverr React 站 JS 点击"选中了候选但状态没进"）。
Playwright 的 ``page.mouse`` / ``page.keyboard`` 底层就是 CDP
``Input.dispatchMouseEvent`` / ``Input.dispatchKeyEvent``，是 trusted。

两种接入模式
============
- ``attach``   ：连到已开的浏览器调试端口（本地工作流：Edge 开 9222），
                 直接复用真实登录态/指纹，不新开窗口。
- ``launch``   ：自带 persistent context 启动一个"干净但 stealth 过"的实例。

所有拟人动作最终都落到 :meth:`execute_pointer` / :meth:`execute_typing` /
:meth:`execute_scroll` 三个执行器，动作层（human_click / hold_drag / ...）
只负责生成计划 + 回读验证。
"""

from __future__ import annotations

import time
from typing import List, Optional, Sequence, Tuple

from .human import (
    HumanRhythm,
    KeyEvent,
    PaceLevel,
    PointerEvent,
    ScrollEvent,
    plan_hold_drag,
    plan_pointer_move,
    plan_scroll,
    plan_typing,
)

try:
    from playwright.sync_api import sync_playwright, Page, BrowserContext
except ImportError as e:  # pragma: no cover
    raise ImportError("需要 playwright：pip install playwright") from e


class GhostDriver:
    """CDP 拟人驱动器。

    Parameters
    ----------
    cdp_url:
        attach 模式的调试端点，默认 ``http://127.0.0.1:9222``（本地 Edge 工作流）。
    pace:
        节奏档位名：``cautious`` / ``normal`` / ``brisk``。
    seed:
        随机种子，便于复现。
    """

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222", pace: str = "normal", seed: Optional[int] = None) -> None:
        self.cdp_url = cdp_url
        self.pace_name = pace
        self.pace = PaceLevel.from_name(pace)
        self._rng_seed = seed
        import random as _random

        self._rng = _random.Random(seed)
        self._pos: Tuple[float, float] = (640.0, 360.0)
        self._cost_cache: Optional[float] = None
        self._pw = None
        self._browser = None
        self._context: Optional[BrowserContext] = None
        self._page: Optional[Page] = None
        self._owned = False  # 是否是自己 launch 的（关闭时要收拾）

    # ---------------- 生命周期 ----------------

    def attach(self, url_match: Optional[str] = None, new_tab: bool = False) -> Page:
        """连到已开浏览器，返回目标页面。

        new_tab=True 时开一个新标签页（不动用户正在看的页面，推荐自动化用）；
        否则默认选第一个非 about:blank 的页面，url_match 可指定匹配。
        """
        self._pw = sync_playwright().start()
        self._browser = self._pw.chromium.connect_over_cdp(self.cdp_url)
        ctx = self._browser.contexts[0]
        self._context = ctx
        if new_tab:
            page = ctx.new_page()
            self._page = page
            self._cost_cache = None  # 新会话重新测量事件成本
            self._ensure_visible()
            return page
        page = None
        for pg in ctx.pages:
            try:
                u = pg.url.lower()
            except Exception:
                continue
            if url_match and url_match.lower() in u:
                page = pg
                break
            if not url_match and u and not u.startswith(("about:", "chrome://newtab", "edge://newtab")):
                page = page or pg
        if page is None:
            page = ctx.pages[0] if ctx.pages else ctx.new_page()
        self._page = page
        self._ensure_visible()
        return page

    def _ensure_visible(self) -> None:
        """保证浏览器窗口可见且页面"聚焦"——否则 CDP 输入被后台节流，节奏失真。

        实测（2026-11-16）：Edge 窗口最小化/不可见时，Input.dispatchMouseEvent
        被浏览器节流，按住 1.5s 的计划实际录得 18~27s（慢 6~18 倍），
        轨迹/长按的拟人节奏全部失真。两道修复：
        1. Browser.setWindowBounds 还原最小化窗口；
        2. Emulation.setFocusEmulationEnabled 让页面保持聚焦状态（防后台标签节流）。
        """
        try:
            cdp = self._browser.new_browser_cdp_session()
            # 先拿本页 targetId，再查它的窗口（不带 targetId 会报 No web contents）
            tid = self._context.new_cdp_session(self._page).send("Target.getTargetInfo")["targetInfo"]["targetId"]
            w = cdp.send("Browser.getWindowForTarget", {"targetId": tid})
            if w.get("bounds", {}).get("windowState") in ("minimized", "hidden"):
                cdp.send(
                    "Browser.setWindowBounds",
                    {"windowId": w["windowId"], "bounds": {"windowState": "normal"}},
                )
        except Exception:
            pass
        try:
            pcdp = self._context.new_cdp_session(self._page)
            pcdp.send("Emulation.setFocusEmulationEnabled", {"enabled": True})
        except Exception:
            pass
        try:
            self._page.bring_to_front()
        except Exception:
            pass

    def launch(self, user_data_dir: str, headless: bool = False, channel: Optional[str] = None) -> Page:
        """自带 persistent context 启动（登录态存 user_data_dir）。"""
        self._pw = sync_playwright().start()
        self._context = self._pw.chromium.launch_persistent_context(
            user_data_dir,
            headless=headless,
            channel=channel,
            args=["--disable-blink-features=AutomationControlled", "--no-default-browser-check"],
        )
        self._page = self._context.pages[0] if self._context.pages else self._context.new_page()
        self._owned = True
        self._ensure_visible()
        return self._page

    def close(self) -> None:
        try:
            if self._owned and self._context:
                self._context.close()
            if self._browser:
                self._browser.close()
        finally:
            if self._pw:
                self._pw.stop()
            self._page = None

    def __enter__(self) -> "GhostDriver":
        return self

    def __exit__(self, *exc) -> None:
        self.close()

    @property
    def page(self) -> Page:
        if self._page is None:
            raise RuntimeError("先调用 attach() 或 launch()")
        return self._page

    # ---------------- 计划执行器（trusted 事件） ----------------

    def _sleep_until(self, t: float, t0: float) -> None:
        """按计划时间推进（Windows sleep 精度 ~15ms，真人抖动可吸收）。"""
        remain = t0 + t - time.perf_counter()
        if remain > 0:
            time.sleep(remain)

    def execute_pointer(self, events: Sequence[PointerEvent]) -> None:
        """执行指针事件序列：move/down/up 全部走 CDP Input 域。"""
        pg = self.page
        mouse = pg.mouse
        t0 = time.perf_counter()
        for ev in events:
            self._sleep_until(ev.t, t0)
            if ev.kind == "move":
                mouse.move(ev.x, ev.y)
            elif ev.kind == "down":
                mouse.down()
            elif ev.kind == "up":
                mouse.up()

    def execute_typing(self, events: Sequence[KeyEvent]) -> None:
        """执行按键事件序列。"""
        pg = self.page
        kb = pg.keyboard
        t0 = time.perf_counter()
        for ev in events:
            self._sleep_until(ev.t, t0)
            if ev.kind == "down":
                kb.down(ev.key)
            else:
                kb.up(ev.key)

    def execute_scroll(self, events: Sequence[ScrollEvent]) -> None:
        """执行滚轮事件序列。"""
        pg = self.page
        mouse = pg.mouse
        t0 = time.perf_counter()
        for ev in events:
            self._sleep_until(ev.t, t0)
            mouse.wheel(0, ev.delta_y)

    # ---------------- 拟人动作层 ----------------

    def _event_cost(self, samples: int = 8) -> float:
        """测量单次 mouse.move 的实际耗时（秒）。

        本机实测：空闲时 ~5ms；CPU 满载时 ~100ms（Edge CDP 通道被拖慢）。
        拟人节奏必须按实际成本校准，否则"按住 1.5s"会录成 9s+。
        """
        if not hasattr(self, "_cost_cache") or self._cost_cache is None:
            pg = self.page
            t0 = time.perf_counter()
            for i in range(samples):
                pg.mouse.move(200 + i, 200)
            self._cost_cache = (time.perf_counter() - t0) / samples
        return self._cost_cache

    def _auto_points(self, target_seconds: float, lo: int = 8, hi: int = 90) -> int:
        """按目标人类时长和实测单事件成本，反推轨迹采样点数。"""
        cost = max(self._event_cost(), 0.002)
        return max(lo, min(hi, int(target_seconds / cost)))

    def human_click(self, x: float, y: float, pause_before: float = 0.12) -> None:
        """拟人单击：贝塞尔轨迹移动 → 短暂停顿（瞄准）→ 按下抬起。

        轨迹点数按实测事件成本自适应：快机器 60+ 点丝般顺滑，
        慢机器 8~15 点也保证总时长落在人类范围（0.3~1.2s）。
        """
        cur = self._current_pos()
        plan = plan_pointer_move(cur[0], cur[1], x, y, rng=self._rng, n_points=self._auto_points(0.7))
        # 在终点加 down/up
        plan.append(PointerEvent("down", x, y, plan[-1].t + pause_before))
        plan.append(PointerEvent("up", x, y, plan[-1].t + 0.09))
        self.execute_pointer(plan)
        self._pos = (x, y)

    def human_type(self, text: str, x: Optional[float] = None, y: Optional[float] = None, clear: bool = True) -> None:
        """拟人打字：先点击聚焦（可选），focus + 逐键可变节奏。

        React 受控输入不要用 fill()——本地踩坑：值进了 DOM 但状态不进 React。
        """
        if x is not None and y is not None:
            self.human_click(x, y)
        pg = self.page
        pg.evaluate("() => { const el = document.activeElement; if (el) el.focus(); }")
        if clear:
            pg.keyboard.press("Control+a")
            time.sleep(0.05)
        self.execute_typing(plan_typing(text, rng=self._rng, pace=self.pace))

    def human_scroll(self, delta: float) -> None:
        """拟人滚动一段距离（分段+阅读停顿+偶发回滚）。"""
        self.execute_scroll(plan_scroll(delta, rng=self._rng, pace=self.pace))

    def hold_drag(
        self,
        x0: float,
        y0: float,
        x1: float,
        y1: float,
        hold_seconds: float = 1.5,
    ) -> None:
        """长按拖动（用户需求 2）：按住 1~2s 激活，再分多段拖过去。

        场景：滑块验证码"点一下很快不行，要按住大概一两秒再把长条拖过去"。
        点数/按住步长按实测事件成本自适应——慢机器上"按住 1.5s"不会失真成 9s。
        """
        cost = max(self._event_cost(), 0.002)
        plan = plan_hold_drag(
            x0, y0, x1, y1,
            rng=self._rng,
            hold_seconds=hold_seconds,
            n_points=self._auto_points(0.8),
            hold_step=min(0.15, max(0.06, cost * 1.2)),
        )
        self.execute_pointer(plan)
        self._pos = (x1, y1)

    def rhythm_gap(self) -> float:
        """不规则操作间隔（用户需求 1）：1s,2s,3s,5s 循环+抖动+偶发分心。"""
        if not hasattr(self, "_rhythm"):
            self._rhythm = HumanRhythm(pace=self.pace, seed=self._rng_seed)
        return self._rhythm.gap()

    def wait_rhythm(self) -> None:
        """按不规则节奏停一拍。"""
        time.sleep(self.rhythm_gap())

    # ---------------- 状态回读（React 站的保命动作） ----------------

    def click_verified(self, selector: str, verify_js: str, timeout_ms: int = 4000, attempts: int = 3) -> bool:
        """点击后必须回读状态验证——UI 表象（候选消失/有值）不算数。

        本地踩坑（Fiverr React 站）：JS/locator 点击后候选消失、input.checked
        偶发 true，但面板按钮仍 disabled——React 状态根本没进。所以每个
        "点中"动作都要用状态回读确认。

        Parameters
        ----------
        selector:
            Playwright 选择器。
        verify_js:
            在页面执行的真值判断 JS（返回 true 算成功）。
        """
        pg = self.page
        for _ in range(attempts):
            try:
                pg.locator(selector).first.click(timeout=timeout_ms)
            except Exception:
                pass
            time.sleep(0.4)
            try:
                if pg.evaluate(verify_js):
                    return True
            except Exception:
                pass
            self.wait_rhythm()
        return False

    def clear_blocking_modals(self, patterns: Tuple[str, ...] = ("no, go back", "cancel", "close")) -> int:
        """清理挡路模态/弹窗按钮（本地踩坑：残留模态 z-index 盖住目标，点击全被拦截）。"""
        pg = self.page
        js = """
        (pats) => {
          let n = 0;
          const btns = [...document.querySelectorAll('button, [role=button]')]
            .filter(b => b.getBoundingClientRect().width > 0);
          for (const b of btns) {
            const t = (b.textContent || '').trim().toLowerCase();
            if (pats.some(p => t === p || t.startsWith(p))) { try { b.click(); n++; } catch(e) {} }
          }
          return n;
        }
        """
        try:
            return int(pg.evaluate(js, list(patterns)))
        except Exception:
            return 0

    # ---------------- 工具 ----------------

    def _current_pos(self) -> Tuple[float, float]:
        if not hasattr(self, "_pos"):
            try:
                vp = self.page.viewport_size
                self._pos = ((vp or {}).get("width", 1280) / 2, (vp or {}).get("height", 720) / 2)
            except Exception:
                self._pos = (640.0, 360.0)
        return self._pos

    def screenshot(self, path: str) -> None:
        self.page.screenshot(path=path)