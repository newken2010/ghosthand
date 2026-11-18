# -*- coding: utf-8 -*-
"""GhostHand 拟人引擎 —— 框架无关的人类行为计划生成器。

设计原则
========
1. **只产"计划"，不碰浏览器**：本模块所有函数输入坐标/参数，输出
   ``PointerEvent`` / ``KeyEvent`` 序列。驱动器（Playwright CDP / chrome.debugger）
   负责执行。好处：可单测、可复现（seed）、可移植到 JS 扩展端。
2. **trusted 事件是硬约束**：现代前端（React 受控输入、滑块验证码）只认真实
   输入事件，JS 合成事件会被忽略。所以计划必须由驱动器走 CDP Input 域下发。
3. **不规则 > 随机**：真人不是白噪声，是"有模式的抖动"——基础节奏循环 +
   幅度抖动 + 偶发分心长停。统一固定间隔（如每 3 秒一次）是最容易被风控
   识破的特征。

三大核心能力（对应用户需求）
============================
- ``HumanRhythm``    —— 不规则操作间隔（1s,2s,3s,5s,1s,2s... 循环 + 抖动 + 分心）
- ``plan_hold_drag`` —— 长按拖动（按住 1~2s 激活，再分多段拖过去）
- ``plan_pointer_move`` / ``plan_typing`` / ``plan_scroll`` —— 贝塞尔轨迹 / 拟人打字 / 拟人滚动
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import Iterator, List, Optional, Sequence, Tuple

__all__ = [
    "PointerEvent",
    "KeyEvent",
    "ScrollEvent",
    "PaceLevel",
    "HumanRhythm",
    "plan_pointer_move",
    "plan_hold_drag",
    "plan_typing",
    "plan_scroll",
    "micro_jitter",
]

# ---------------------------------------------------------------------------
# 事件模型
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PointerEvent:
    """一个指针事件。t 为相对计划起点的秒数（单调递增）。"""

    kind: str  # "move" | "down" | "up"
    x: float
    y: float
    t: float

    def as_dict(self) -> dict:
        return {"kind": self.kind, "x": round(self.x, 2), "y": round(self.y, 2), "t": round(self.t, 4)}


@dataclass(frozen=True)
class KeyEvent:
    """一个按键事件。kind: "down" | "up"。"""

    kind: str
    key: str
    t: float

    def as_dict(self) -> dict:
        return {"kind": self.kind, "key": self.key, "t": round(self.t, 4)}


@dataclass(frozen=True)
class ScrollEvent:
    """一次滚轮事件（deltaY 为滚动量，向下为正）。"""

    delta_y: float
    t: float

    def as_dict(self) -> dict:
        return {"delta_y": round(self.delta_y, 1), "t": round(self.t, 4)}


# ---------------------------------------------------------------------------
# 节奏档位
# ---------------------------------------------------------------------------


class PaceLevel:
    """操作节奏档位。multiplier 越小越快。"""

    CAUTIOUS = 1.6  # 谨慎：像第一次用网站的人
    NORMAL = 1.0  # 正常：普通用户
    BRISK = 0.55  # 轻快：熟练用户（仍远快于机器人的固定间隔，但别太过）

    @classmethod
    def from_name(cls, name: str) -> float:
        return {"cautious": cls.CAUTIOUS, "normal": cls.NORMAL, "brisk": cls.BRISK}.get(name, cls.NORMAL)


# 邻键表（QWERTY，用于拟人打错改正）
_NEIGHBORS = {
    "a": "sq", "b": "vgn", "c": "xvd", "d": "sf", "e": "wr", "f": "dg",
    "g": "fh", "h": "gj", "i": "uo", "j": "hk", "k": "jl", "l": "k",
    "m": "n", "n": "bm", "o": "ip", "p": "o", "q": "wa", "r": "et",
    "s": "ad", "t": "ry", "u": "yi", "v": "cb", "w": "qe", "x": "zc",
    "y": "tu", "z": "x",
}


# ---------------------------------------------------------------------------
# 不规则节奏
# ---------------------------------------------------------------------------


class HumanRhythm:
    """不规则操作间隔发生器。

    用户原话："第 1 次按 1 秒，第 2 次按 2 秒，第 3 次按 3 秒，第 4 次按 5 秒，
    然后又按 1 秒、2 秒，就是不规则的间隔。"

    实现 = 基础模式循环 (1,2,3,5) + 每项 0.55~1.5 倍幅度抖动
          + 15% 概率"分心长停"（2~8 秒，模拟看手机/走神）
          + 档位倍率。

    注意：这不是均匀随机（那反而是机器特征），而是"有人的模式的不规则"。
    """

    BASE_PATTERN: Tuple[float, ...] = (1.0, 2.0, 3.0, 5.0)

    def __init__(
        self,
        pace: float = PaceLevel.NORMAL,
        seed: Optional[int] = None,
        distraction_prob: float = 0.15,
        distraction_range: Tuple[float, float] = (2.0, 8.0),
    ) -> None:
        self.pace = max(0.1, pace)
        self._rng = random.Random(seed)
        self._i = 0
        self.distraction_prob = distraction_prob
        self.distraction_range = distraction_range

    def gap(self) -> float:
        """下一次操作间隔（秒）。"""
        base = self.BASE_PATTERN[self._i % len(self.BASE_PATTERN)]
        self._i += 1
        g = base * self._rng.uniform(0.55, 1.5)
        if self._rng.random() < self.distraction_prob:
            g += self._rng.uniform(*self.distraction_range)
        return g * self.pace

    def sleep_gap(self) -> float:
        """gap() 的别名，语义化给驱动器用。"""
        return self.gap()

    def reset(self) -> None:
        self._i = 0


# ---------------------------------------------------------------------------
# 贝塞尔轨迹
# ---------------------------------------------------------------------------


def _smooth_noise(rng: random.Random, n: int, amp: float) -> List[float]:
    """平滑随机游走（模拟手抖），不是白噪声。"""
    out: List[float] = []
    v = 0.0
    for _ in range(n):
        v = 0.75 * v + rng.uniform(-amp, amp)
        out.append(v)
    return out


def micro_jitter(rng: random.Random, amp: float = 1.2) -> Tuple[float, float]:
    """单点微抖动（长按保持期间用）。"""
    return (rng.uniform(-amp, amp), rng.uniform(-amp, amp))


def _bezier(p0, p1, p2, p3, u: float) -> Tuple[float, float]:
    mt = 1 - u
    x = mt**3 * p0[0] + 3 * mt**2 * u * p1[0] + 3 * mt * u**2 * p2[0] + u**3 * p3[0]
    y = mt**3 * p0[1] + 3 * mt**2 * u * p1[1] + 3 * mt * u**2 * p2[1] + u**3 * p3[1]
    return x, y


def _ease_in_out(u: float) -> float:
    """真人移动鼠标：起步加速、接近目标减速。"""
    return u * u * (3 - 2 * u)


def plan_pointer_move(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rng: Optional[random.Random] = None,
    base_duration: Optional[float] = None,
    overshoot_prob: float = 0.22,
    jitter_amp: float = 1.1,
    n_points: Optional[int] = None,
) -> List[PointerEvent]:
    """从 (x0,y0) 拟人移动到 (x1,y1) 的事件序列。

    - 三次贝塞尔轨迹，控制点垂直偏移带随机
    - 速度 ease-in-out（慢-快-慢）
    - 每点叠加平滑手抖噪声
    - overshoot_prob 概率过冲目标 3~10px 后回拉（真人特征）

    n_points: 采样点数。None=按距离自动；驱动器在慢机器上会按实测
    单事件成本传小值（保证总时长落在人类范围，见 driver._auto_points）。
    """
    rng = rng or random.Random()
    dist = math.hypot(x1 - x0, y1 - y0)
    if base_duration is None:
        # Fitts 定律风格：距离越远越久，但有人的抖动
        base_duration = 0.18 + 0.0011 * dist + rng.uniform(-0.05, 0.12)
    base_duration = max(0.08, base_duration)

    # 控制点：连线垂直方向随机偏移
    dx, dy = x1 - x0, y1 - y0
    L = math.hypot(dx, dy) or 1.0
    nx, ny = -dy / L, dx / L  # 单位法向
    off1 = rng.uniform(0.06, 0.30) * L * rng.choice([-1, 1])
    off2 = rng.uniform(0.04, 0.22) * L * rng.choice([-1, 1])
    c1 = (x0 + dx * 0.28 + nx * off1, y0 + dy * 0.28 + ny * off1)
    c2 = (x0 + dx * 0.72 + nx * off2, y0 + dy * 0.72 + ny * off2)

    n_points = max(8, min(90, n_points if n_points else int(dist / 9) + 12))
    noise_t = _smooth_noise(rng, n_points, jitter_amp)
    noise_n = _smooth_noise(rng, n_points, jitter_amp * 0.7)

    events: List[PointerEvent] = []
    t = 0.0
    prev_u = 0.0
    for i in range(1, n_points + 1):
        u = i / n_points
        bx, by = _bezier((x0, y0), c1, c2, (x1, y1), u)
        # 切向单位向量（用于把噪声拆成切向/法向）
        bx2, by2 = _bezier((x0, y0), c1, c2, (x1, y1), min(1.0, u + 0.01))
        tx, ty = bx2 - bx, by2 - by
        tl = math.hypot(tx, ty) or 1.0
        tx, ty = tx / tl, ty / tl
        px, py = bx + tx * noise_t[i - 1] - ty * noise_n[i - 1], by + ty * noise_t[i - 1] + tx * noise_n[i - 1]
        # 速度曲线：ease-in-out 的微分，间隔 ∝ 1/v
        v = 6 * _ease_in_out(u) * (1 - _ease_in_out(u)) + 0.12  # +下限防除零
        t += base_duration / (n_points * v * 3.2)
        events.append(PointerEvent("move", px, py, t))
        prev_u = u

    # 过冲回拉
    if rng.random() < overshoot_prob and dist > 30:
        over = rng.uniform(3.0, 10.0)
        ux, uy = dx / L, dy / L
        ox, oy = x1 + ux * over, y1 + uy * over
        events.append(PointerEvent("move", ox, oy, t + rng.uniform(0.02, 0.06)))
        t += rng.uniform(0.02, 0.06)
        # 2~3 步回拉到位
        for k in (0.55, 0.8, 1.0):
            events.append(PointerEvent("move", x1 + ux * over * (1 - k), y1 + uy * over * (1 - k), t + 0.03 * k))
            t += 0.03 * k
    return events


# ---------------------------------------------------------------------------
# 长按拖动（用户需求 2）
# ---------------------------------------------------------------------------


def plan_hold_drag(
    x0: float,
    y0: float,
    x1: float,
    y1: float,
    rng: Optional[random.Random] = None,
    hold_seconds: float = 1.5,
    approach: bool = True,
    n_points: Optional[int] = None,
    hold_step: float = 0.11,
) -> List[PointerEvent]:
    """长按拖动计划：移动到起点 → 按住 hold_seconds → 分段拖到终点 → 松开。

    场景：滑块验证码"点一下很快不行，要按住大概一两秒再把长条拖过去"。

    - hold 期间：每 hold_step 秒微动 ±1px（模拟手指按住时的生理抖动，
      也让对端 mousedown 状态持续刷新）。慢机器上 hold_step 传实测单事件
      成本，保证"按住 1~2 秒"不失真（见 driver._auto_points）。
    - 拖动分段：3~6 段，速度 慢(启动摩擦)→快→减速(对准目标)，
      段间 50~150ms 停顿
    - approach=True 时先拟人移动到起点再按下
    - n_points: 拖动段采样点数（None=自动；慢机器上传小值）
    """
    rng = rng or random.Random()
    events: List[PointerEvent] = []
    t = 0.0

    if approach:
        # 从"当前位置附近"拟人划过来（假装从页面某处移过来）
        sx = x0 - rng.uniform(60, 220) * rng.choice([-1, 1])
        sy = y0 - rng.uniform(20, 120) * rng.choice([-1, 1])
        for ev in plan_pointer_move(sx, sy, x0, y0, rng=rng):
            events.append(PointerEvent(ev.kind, ev.x, ev.y, t + ev.t))
        t += events[-1].t if events else 0.0
        # 按下前停顿（瞄准）
        t += rng.uniform(0.10, 0.35)

    events.append(PointerEvent("down", x0, y0, t))
    t += rng.uniform(0.02, 0.06)

    # ---- 按住阶段：持续 hold_seconds，微动保持活性 ----
    hold_end = t + hold_seconds
    cx, cy = x0, y0
    while t < hold_end:
        dt = hold_step * rng.uniform(0.85, 1.15)
        t = min(t + dt, hold_end)
        jx, jy = micro_jitter(rng, amp=1.0)
        cx, cy = x0 + jx, y0 + jy
        events.append(PointerEvent("move", cx, cy, t))

    # ---- 拖动阶段：分段、变速、段间停顿 ----
    dist = math.hypot(x1 - x0, y1 - y0)
    n_seg = max(3, min(6, int(dist / 90) + 3))
    seg_events = plan_pointer_move(x0, y0, x1, y1, rng=rng, base_duration=0.25 + 0.0009 * dist, n_points=n_points)
    # 把连续轨迹按时间切成 n_seg 段，段间插停顿
    total_t = seg_events[-1].t
    bounds = [total_t * k / n_seg for k in range(n_seg + 1)]
    seg_i = 0
    for ev in seg_events:
        while seg_i < n_seg and ev.t > bounds[seg_i + 1]:
            seg_i += 1
            t += rng.uniform(0.05, 0.15)  # 段间停顿（换气/瞄准）
        events.append(PointerEvent("move", ev.x, ev.y, t + ev.t))
    t += seg_events[-1].t

    # 到位后微调（对准缺口）再松手
    t += rng.uniform(0.08, 0.25)
    events.append(PointerEvent("move", x1, y1, t))
    events.append(PointerEvent("up", x1, y1, t + rng.uniform(0.02, 0.08)))
    return events


# ---------------------------------------------------------------------------
# 拟人打字
# ---------------------------------------------------------------------------


def plan_typing(
    text: str,
    rng: Optional[random.Random] = None,
    pace: float = PaceLevel.NORMAL,
    typo_prob: float = 0.06,
) -> List[KeyEvent]:
    """拟人打字计划：可变击键间隔 + 偶发打错-停顿-改正。

    - 每字符间隔 ~ 三角分布（40~130ms * pace），词内稍快、词间稍慢
    - typo_prob 概率敲错邻键 → 停顿 200~500ms → Backspace 改正
      （真人的"发现打错了"特征；机器人从不出错反而可疑）
    """
    rng = rng or random.Random()
    events: List[KeyEvent] = []
    t = 0.0
    for i, ch in enumerate(text):
        if ch == " ":
            delay = rng.triangular(90, 260, 150) * pace  # 词间停顿
        else:
            delay = rng.triangular(35, 150, 75) * pace
        # 偶发长停顿（想一下）
        if rng.random() < 0.04:
            delay += rng.uniform(0.25, 0.9)
        t += delay / 1000.0
        # 保证上一键已抬起（物理约束：不能按下一键时上一键还按着）
        if events:
            t = max(t, events[-1].t + 0.012)
        events.append(KeyEvent("down", ch, t))
        events.append(KeyEvent("up", ch, t + rng.uniform(0.03, 0.11)))

        if ch.isalpha() and rng.random() < typo_prob:
            neigh = _NEIGHBORS.get(ch.lower(), "")
            if neigh:
                wrong = rng.choice(neigh)
                t = max(t + rng.uniform(0.2, 0.5), events[-1].t + 0.012)  # 发现打错的停顿
                events.append(KeyEvent("down", wrong, t))
                events.append(KeyEvent("up", wrong, t + 0.06))
                t = max(t + rng.uniform(0.25, 0.6), events[-1].t + 0.012)  # 反应时间
                events.append(KeyEvent("down", "Backspace", t))
                events.append(KeyEvent("up", "Backspace", t + 0.07))
                t = max(t + rng.uniform(0.15, 0.4), events[-1].t + 0.012)
                events.append(KeyEvent("down", ch, t))
                events.append(KeyEvent("up", ch, t + 0.08))
    return events


# ---------------------------------------------------------------------------
# 拟人滚动
# ---------------------------------------------------------------------------


def plan_scroll(
    total_delta: float,
    rng: Optional[random.Random] = None,
    pace: float = PaceLevel.NORMAL,
) -> List[ScrollEvent]:
    """拟人滚动计划：分段滚 + 阅读停顿 + 偶发回滚。

    真人滚页面不是一次滚 5000px，而是"滚一段-停下来读-再滚"，
    偶尔还会滚回去一点（刚才没看清）。
    """
    rng = rng or random.Random()
    events: List[ScrollEvent] = []
    direction = 1.0 if total_delta >= 0 else -1.0
    remaining = abs(total_delta)
    t = 0.0
    while remaining > 20:
        seg = min(remaining, rng.uniform(120, 520))
        remaining -= seg
        t += rng.uniform(0.02, 0.09) * pace
        events.append(ScrollEvent(direction * seg, t))
        # 阅读停顿
        t += rng.triangular(0.4, 2.6, 1.0) * pace
        # 偶发回滚
        if remaining > 100 and rng.random() < 0.18:
            back = rng.uniform(30, 110)
            t += rng.uniform(0.15, 0.4)
            events.append(ScrollEvent(-direction * back, t))
            t += rng.uniform(0.3, 1.0)
            remaining += back
    return events


# ---------------------------------------------------------------------------
# 便捷迭代器
# ---------------------------------------------------------------------------


def iter_pointer(events: Sequence[PointerEvent]) -> Iterator[PointerEvent]:
    """按时间顺序产出指针事件。"""
    yield from sorted(events, key=lambda e: e.t)