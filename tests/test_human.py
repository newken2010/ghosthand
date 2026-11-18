# -*- coding: utf-8 -*-
"""human.py 拟人引擎单元测试 —— 验证"计划"的数学合理性，不需要浏览器。"""
import math
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import random

from ghosthand.human import (
    HumanRhythm,
    KeyEvent,
    PaceLevel,
    PointerEvent,
    plan_hold_drag,
    plan_pointer_move,
    plan_scroll,
    plan_typing,
)


def test_rhythm_irregular():
    """不规则间隔：模式循环 + 抖动 + 偶发长停，不是固定值。"""
    r = HumanRhythm(seed=42)
    gaps = [r.gap() for _ in range(40)]
    assert all(g > 0 for g in gaps)
    # 有变化（不是统一间隔）
    assert len(set(round(g, 2) for g in gaps)) > 10
    # 统计意义上遵循 1,2,3,5 模式：base=1 的轮次（0,4,8...）均值 < base=5 的轮次（3,7,11...）均值
    low = statistics.mean(gaps[i] for i in range(0, 40, 4))
    high = statistics.mean(gaps[i] for i in range(3, 40, 4))
    assert low < high
    # 偶发长停存在（40 次里至少一次 > 6s）
    assert max(gaps) > 5.0
    # 档位生效
    fast = HumanRhythm(pace=PaceLevel.BRISK, seed=42)
    slow = HumanRhythm(pace=PaceLevel.CAUTIOUS, seed=42)
    assert fast.gap() < slow.gap()


def test_rhythm_reproducible():
    a = HumanRhythm(seed=7)
    b = HumanRhythm(seed=7)
    assert [a.gap() for _ in range(10)] == [b.gap() for _ in range(10)]


def test_pointer_move_shape():
    rng = random.Random(1)
    ev = plan_pointer_move(100, 100, 800, 500, rng=rng)
    assert all(e.kind == "move" for e in ev)
    # 时间严格递增
    ts = [e.t for e in ev]
    assert all(b > a for a, b in zip(ts, ts[1:]))
    # 终点接近目标
    assert math.hypot(ev[-1].x - 800, ev[-1].y - 500) < 12
    # 轨迹不是直线（有抖动/弯曲）
    direct = math.hypot(800 - 100, 500 - 100)
    path = sum(math.hypot(b.x - a.x, b.y - a.y) for a, b in zip(ev, ev[1:]))
    assert path >= direct
    # 总时长合理（几十毫秒到一两秒）
    assert 0.05 < ev[-1].t < 3.0


def test_pointer_move_short_distance():
    rng = random.Random(2)
    ev = plan_pointer_move(0, 0, 5, 5, rng=rng)
    assert len(ev) >= 12
    assert math.hypot(ev[-1].x - 5, ev[-1].y - 5) < 12


def test_hold_drag_structure():
    """长按拖动：approach→down→hold(微动)→分段拖动→up。"""
    rng = random.Random(3)
    ev = plan_hold_drag(300, 300, 700, 300, rng=rng, hold_seconds=1.5)
    kinds = [e.kind for e in ev]
    assert kinds[0] == "move"  # approach
    assert "down" in kinds and "up" in kinds
    di, ui = kinds.index("down"), kinds.index("up")
    assert di < ui
    # down 在起点
    assert math.hypot(ev[di].x - 300, ev[di].y - 300) < 3
    # up 在终点
    assert math.hypot(ev[ui].x - 700, ev[ui].y - 300) < 3
    # 按住时长 ≈ hold_seconds（down 到开始拖动之间）
    hold_span = ev[ui - 1].t - ev[di].t
    assert hold_span > 1.2  # 至少按住 1.2s
    # hold 期间有多个微动 move（保持活性）
    hold_moves = [e for e in ev[di:ui] if e.kind == "move"]
    assert len(hold_moves) >= 5
    # 拖动段之间有停顿（时间不连续密集）——检查 down 之后总时长
    assert ev[ui].t > 2.0


def test_hold_drag_no_approach():
    rng = random.Random(4)
    ev = plan_hold_drag(0, 0, 400, 0, rng=rng, hold_seconds=1.0, approach=False)
    assert ev[0].kind == "down"


def test_typing():
    rng = random.Random(5)
    ev = plan_typing("hello world", rng=rng)
    downs = [e for e in ev if e.kind == "down"]
    ups = [e for e in ev if e.kind == "up"]
    # 每个 down 有对应 up
    assert len(downs) == len(ups)
    # 时间递增
    ts = [e.t for e in ev]
    assert all(b >= a for a, b in zip(ts, ts[1:]))
    # 总时长：11 字符 * ~75ms ≈ 0.8s+，加标点/停顿应超过 0.6s
    assert ev[-1].t > 0.5
    # 偶发打错（长文本下应出现 Backspace）
    long_ev = plan_typing("the quick brown fox jumps over the lazy dog 12345", rng=random.Random(9))
    assert any(e.key == "Backspace" for e in long_ev if e.kind == "down")


def test_scroll():
    rng = random.Random(6)
    ev = plan_scroll(2000, rng=rng)
    assert len(ev) >= 3  # 分段
    total = sum(e.delta_y for e in ev)
    assert total > 0  # 向下
    ts = [e.t for e in ev]
    assert all(b > a for a, b in zip(ts, ts[1:]))
    # 有阅读停顿（相邻事件间隔有 > 0.3s 的）
    assert any(b.t - a.t > 0.3 for a, b in zip(ev, ev[1:]))


def test_event_dicts():
    ev = plan_pointer_move(0, 0, 100, 0, rng=random.Random(0))
    d = ev[0].as_dict()
    assert set(d) == {"kind", "x", "y", "t"}


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
        print(f"PASS {fn.__name__}")
    print(f"\n{len(fns)} tests passed")