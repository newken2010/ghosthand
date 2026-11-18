# -*- coding: utf-8 -*-
"""GhostHand 滑块验证码专项 —— 长按拖动的落地场景。

工作方式（对应用户需求 2 + 3）
==============================
"点一下很快不行，要按住大概一两秒再把长条拖过去"——这是典型滑块验证码。
GhostHand 的做法：

1. **检测滑块柄**（DOM 启发式，不针对特定站点）：按 class/role 特征找
   可见的、典型宽高比的拖动柄。
2. **缺口定位两条路**：
   - ``solve(gap_x=...)``：调用方（通常是 AI 看了截图后）直接给目标 x——
     这就是"派 AI 去帮我看回来"的用法，最可靠；
   - ``auto_detect()``：DOM/样式启发式猜缺口位置（不可靠站点会失败）。
3. **长按拖动**：走 ``driver.hold_drag``——按住 1~2s 激活，分多段拖过去。
4. **失败重试**：检测失败提示 → 回退一点 → 换随机种子重试
   （每次重试的轨迹/时长都不同，避免"同一轨迹反复失败"的机器特征）。

诚实边界：不识别验证码图片内容（那是 ML/打码平台的活）。
这里只负责"像人一样把滑块拖过去"，拖多远由调用方或启发式决定。
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Callable, List, Optional, Tuple

from .driver import GhostDriver

# 滑块柄常见特征（命中任一即候选）
_HANDLE_HINTS = ("slide", "slider", "drag", "handle", "verify", "code-btn", "captcha")

# 失败提示常见文案
_FAIL_HINTS = ("重新", "失败", "错误", "不准", "再试", "retry", "again", "incorrect", "wrong", "try again")


@dataclass
class Handle:
    x: float
    y: float
    width: float
    height: float
    selector: str

    @property
    def cx(self) -> float:
        return self.x + self.width / 2

    @property
    def cy(self) -> float:
        return self.y + self.height / 2


class SliderSolver:
    def __init__(self, driver: GhostDriver) -> None:
        self.d = driver

    # ---------------- 检测 ----------------

    def find_handle(self) -> Optional[Handle]:
        """DOM 启发式找滑块柄。返回 None 表示没找到。"""
        js = """
        (hints) => {
          const els = [...document.querySelectorAll('div, span, i, button, a')]
            .filter(e => {
              const r = e.getBoundingClientRect();
              if (r.width < 20 || r.width > 120) return false;
              if (r.height < 12 || r.height > 80) return false;
              const cls = (e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) || '';
              const s = (cls + ' ' + (e.id || '')).toLowerCase();
              return hints.some(h => s.includes(h));
            })
            .filter(e => e.getBoundingClientRect().width > 0);
          if (!els.length) return null;
          // 取面积最大的候选
          els.sort((a, b) => b.getBoundingClientRect().width * b.getBoundingClientRect().height
                            - a.getBoundingClientRect().width * a.getBoundingClientRect().height);
          const e = els[0];
          const r = e.getBoundingClientRect();
          const cls = (e.className && e.className.baseVal !== undefined ? e.className.baseVal : e.className) || '';
          return { x: r.x, y: r.y, width: r.width, height: r.height,
                   selector: cls ? '.' + String(cls).split(/\\s+/).filter(Boolean).join('.') : 'div' };
        }
        """
        try:
            r = self.d.page.evaluate(js, list(_HANDLE_HINTS))
        except Exception:
            return None
        if not r:
            return None
        return Handle(**r)

    def auto_detect_gap(self, handle: Handle) -> Optional[float]:
        """启发式猜缺口 x：优先读 DOM/样式里的位置提示，否则 None。

        不可靠的站点会返回 None——此时应改用 solve(gap_x=...) 由 AI 看图给目标。
        """
        js = """
        (hx) => {
          // 1) data-* / style 里的位置提示
          const cands = [...document.querySelectorAll('[data-x], [data-left], [data-position]')];
          for (const c of cands) {
            const v = c.dataset.x || c.dataset.left || c.dataset.position;
            const n = parseFloat(v);
            if (!isNaN(n) && n > 0) return n;
          }
          // 2) 缺口元素（常见 class: gap / puzzle / notch / 缺口）
          const gaps = [...document.querySelectorAll('[class*=gap], [class*=puzzle], [class*=notch], [class*=lack]')]
            .filter(g => g.getBoundingClientRect().width > 0);
          if (gaps.length) {
            const r = gaps[0].getBoundingClientRect();
            return r.x;
          }
          return null;
        }
        """
        try:
            r = self.d.page.evaluate(js, handle.cx)
            return float(r) if r is not None else None
        except Exception:
            return None

    # ---------------- 解题 ----------------

    def failed(self) -> bool:
        """检测页面是否出现失败提示。"""
        try:
            js = """
            (hints) => {
              const txt = (document.body.innerText || '').toLowerCase();
              return hints.some(h => txt.includes(h));
            }
            """
            return bool(self.d.page.evaluate(js, list(_FAIL_HINTS)))
        except Exception:
            return False

    def solve(
        self,
        gap_x: Optional[float] = None,
        hold_seconds: float = 1.5,
        max_attempts: int = 4,
        on_attempt: Optional[Callable[[int, Handle, float], None]] = None,
    ) -> bool:
        """长按拖动解滑块。

        Parameters
        ----------
        gap_x:
            缺口目标 x（视口坐标）。None 时先试 auto_detect_gap()。
        hold_seconds:
            按住激活时长（默认 1.5s，符合"按住大概一两秒"）。
        max_attempts:
            最大尝试次数（每次换随机种子，轨迹不同）。
        on_attempt:
            每次尝试前的回调 (attempt, handle, gap_x)——AI 可在此看截图
            修正 gap_x（"派 AI 去看回来"的接入点）。
        """
        handle = self.find_handle()
        if handle is None:
            return False

        target = gap_x if gap_x is not None else self.auto_detect_gap(handle)
        if target is None:
            return False  # 调用方必须给 gap_x

        for attempt in range(1, max_attempts + 1):
            if on_attempt:
                on_attempt(attempt, handle, target)
            # 每次尝试换种子 → 不同轨迹/时长/抖动
            self.d._rng.seed((self.d._rng_seed or 0) + attempt * 977)
            self.d.hold_drag(handle.cx, handle.cy, target, handle.cy, hold_seconds=hold_seconds)
            time.sleep(1.2)  # 等结果渲染
            if not self.failed():
                return True
            # 失败：目标回退一点（常见"拖过头/不够"），下次换轨迹重试
            target -= (6 if attempt % 2 else -4)
            self.d.wait_rhythm()
        return False