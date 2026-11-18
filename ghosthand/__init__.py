# -*- coding: utf-8 -*-
"""GhostHand —— 拟人浏览器自动化：不规则节奏 / 长按拖动 / 反爬 / AI 网关。"""

from .human import (
    HumanRhythm,
    PaceLevel,
    PointerEvent,
    KeyEvent,
    ScrollEvent,
    plan_pointer_move,
    plan_hold_drag,
    plan_typing,
    plan_scroll,
)
from .driver import GhostDriver
from .slider import SliderSolver, Handle
from .queue import TaskQueue, Task

__version__ = "0.1.0"
__all__ = [
    "GhostDriver",
    "SliderSolver",
    "Handle",
    "TaskQueue",
    "Task",
    "HumanRhythm",
    "PaceLevel",
    "PointerEvent",
    "KeyEvent",
    "ScrollEvent",
    "plan_pointer_move",
    "plan_hold_drag",
    "plan_typing",
    "plan_scroll",
]