# -*- coding: utf-8 -*-
"""GhostHand × browser-use 拟人中间件 —— 千问建议的落地姿势。

原理
====
browser-use 的 ``actor/mouse.py`` 里 ``Mouse.click(x, y)`` 是**瞬移式**
CDP 事件（mousePressed + mouseReleased 打在同一坐标，中间没有任何移动），
这是最典型的机器特征。同理 ``Mouse.move`` 是单步跳转。

中间件做的事：monkey patch ``browser_use.actor.mouse.Mouse`` 的
``click`` / ``move`` / ``down`` / ``up``，把瞬移换成 GhostHand 的
贝塞尔轨迹 + 不规则节奏；``Keyboard.type`` 换成拟人打字。
**不碰 browser-use 的 Agent 决策逻辑**——LLM 该看什么该点什么照旧，
只是"手"变成了人的手。

用法::

    from ghosthand.agent import humanize_browser_use
    undo = humanize_browser_use(pace="normal")   # 打了补丁
    ...  # 正常用 browser-use 的 Agent
    undo()                                        # 还原（测试用）

依赖：browser-use 已安装（本地 0.12.6 已验证结构）。
"""

from __future__ import annotations

import asyncio
import random
from typing import Callable, Optional

from .human import PaceLevel, plan_pointer_move, plan_typing

_PATCHED = False
_ORIGINALS: dict = {}


def _patch_mouse(pace: float, seed: Optional[int]) -> None:
    from browser_use.actor.mouse import Mouse

    if getattr(Mouse, "_ghosthand", False):
        return
    rng = random.Random(seed)

    orig_click = Mouse.click
    orig_move = Mouse.move
    _ORIGINALS["Mouse.click"] = (Mouse, "click", orig_click)
    _ORIGINALS["Mouse.move"] = (Mouse, "move", orig_move)

    async def click(self, x: int, y: int, button="left", click_count: int = 1) -> None:
        """拟人点击：贝塞尔轨迹移动 → 瞄准停顿 → 按下抬起。"""
        # 从"上一位置"划过来（记录在 self 上）
        cx, cy = getattr(self, "_ghost_pos", (x - random.uniform(80, 260), y - random.uniform(30, 140)))
        plan = plan_pointer_move(cx, cy, float(x), float(y), rng=rng)
        for ev in plan:
            await self._client.send.Input.dispatchMouseEvent(
                {"type": "mouseMoved", "x": ev.x, "y": ev.y}, session_id=self._session_id
            )
            await asyncio.sleep(max(0.0, ev.t - (getattr(self, "_ghost_t", 0.0))))
            self._ghost_t = ev.t
        self._ghost_t = 0.0
        self._ghost_pos = (x, y)
        await asyncio.sleep(random.uniform(0.08, 0.3))  # 瞄准停顿
        await orig_click(self, x, y, button, click_count)

    async def move(self, x: int, y: int, steps: int = 1) -> None:
        """拟人移动：单步跳转变多步平滑轨迹。"""
        cx, cy = getattr(self, "_ghost_pos", (float(x), float(y)))
        plan = plan_pointer_move(cx, cy, float(x), float(y), rng=rng)
        for ev in plan:
            await self._client.send.Input.dispatchMouseEvent(
                {"type": "mouseMoved", "x": ev.x, "y": ev.y}, session_id=self._session_id
            )
            await asyncio.sleep(0.004)
        self._ghost_pos = (x, y)

    Mouse.click = click
    Mouse.move = move
    Mouse._ghosthand = True


def _patch_keyboard(pace: float, seed: Optional[int]) -> None:
    try:
        from browser_use.actor.page import Keyboard  # 新版位置
    except Exception:
        try:
            from browser_use.actor.keyboard import Keyboard  # 旧版位置
        except Exception:
            return
    if getattr(Keyboard, "_ghosthand", False):
        return
    rng = random.Random((seed or 0) + 1)

    orig_type = None
    for name in ("type", "type_text", "input_text"):
        if hasattr(Keyboard, name):
            orig_type = getattr(Keyboard, name)
            _ORIGINALS[f"Keyboard.{name}"] = (Keyboard, name, orig_type)
            break
    if orig_type is None:
        return

    async def type_text(self, text: str) -> None:
        """拟人打字：可变节奏 + 偶发打错改正。"""
        plan = plan_typing(text, rng=rng, pace=pace)
        for ev in plan:
            if ev.kind == "down":
                await self._client.send.Input.dispatchKeyEvent(
                    {"type": "keyDown", "key": ev.key, "text": ev.key if len(ev.key) == 1 else None},
                    session_id=self._session_id,
                )
            else:
                await self._client.send.Input.dispatchKeyEvent(
                    {"type": "keyUp", "key": ev.key}, session_id=self._session_id
                )
            await asyncio.sleep(0.004)

    setattr(Keyboard, orig_type.__name__, type_text)
    Keyboard._ghosthand = True


def humanize_browser_use(pace: str = "normal", seed: Optional[int] = None) -> Callable[[], None]:
    """给 browser-use 打拟人补丁。返回还原函数。"""
    global _PATCHED
    p = PaceLevel.from_name(pace)
    _patch_mouse(p, seed)
    _patch_keyboard(p, seed)
    _PATCHED = True

    def undo() -> None:
        for (cls, name, orig) in _ORIGINALS.values():
            setattr(cls, name, orig)
        _ORIGINALS.clear()

    return undo


def run_agent(task: str, pace: str = "normal", seed: Optional[int] = None, headless: bool = False):
    """一把梭：拟人补丁 + browser-use Agent 跑任务。

    task 例："打开 example.com，告诉我页面标题"。
    需要配置 LLM（browser-use 的 ChatOpenAI 等）——按 browser-use 文档来。
    """
    undo = humanize_browser_use(pace=pace, seed=seed)
    try:
        from browser_use import Agent  # noqa: F401  （占位：实际 LLM 由调用方注入）

        raise NotImplementedError(
            "请在你的代码里组合：humanize_browser_use() + Agent(task=..., llm=...)。"
            "browser-use 的 LLM 配置请按其官方文档（ChatOpenAI 等）。"
        )
    finally:
        undo()