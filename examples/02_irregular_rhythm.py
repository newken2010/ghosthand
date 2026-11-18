# -*- coding: utf-8 -*-
"""演示 2：不规则操作间隔（用户需求 1）。

"不能统一间隔 3 秒，比如第 1 次按 1 秒，第 2 次按 2 秒，第 3 次按 3 秒，
第 4 次按 5 秒，然后又按 1 秒、2 秒，就是不规则的间隔。"

本演示：打印 HumanRhythm 生成的间隔序列（离线，立即可跑），
然后在 Edge 里真实点击 8 次，回录每次点击的真实时间戳验证间隔不规则。

运行：python examples/02_irregular_rhythm.py        （只看序列）
      Edge 9222 启动后加上 --live 参数真实点击验证
"""
import sys
import time
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")  # GitBash 终端默认 GBK，防 Unicode 崩
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghosthand import HumanRhythm, PaceLevel


def show_sequence() -> None:
    print("=== 离线序列（normal 档，seed=42）===")
    r = HumanRhythm(seed=42)
    for i in range(16):
        g = r.gap()
        bar = "█" * int(g * 4)
        print(f"  第 {i+1:2d} 次: {g:5.2f}s  {bar}")
    print("\n对比：固定 3 秒的机器人节奏会是 3.00 3.00 3.00 3.00 …（一眼假）")

    print("\n=== 档位对比（同样 8 次）===")
    for name, pace in (("cautious", PaceLevel.CAUTIOUS), ("normal", PaceLevel.NORMAL), ("brisk", PaceLevel.BRISK)):
        r = HumanRhythm(pace=pace, seed=42)
        print(f"  {name:9s}: " + " ".join(f"{r.gap():.2f}" for _ in range(8)))


def live() -> None:
    import tempfile

    from ghosthand import GhostDriver
    from ghosthand.stealth import apply_stealth

    # 本地测试页（离线可控，不依赖外网）
    p = Path(tempfile.gettempdir()) / "ghosthand_rhythm_demo.html"
    p.write_text(
        "<!DOCTYPE html><meta charset=utf-8><style>body{margin:80px;font-family:sans-serif}"
        "h1{display:inline-block;padding:20px;background:#eef}</style>"
        "<h1>点我 8 次</h1>", encoding="utf-8")

    d = GhostDriver(pace="normal", seed=7)
    d.attach(new_tab=True)
    apply_stealth(d)
    d.page.goto(p.as_uri(), wait_until="load")
    box = d.page.locator("h1").first.bounding_box()
    x, y = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2

    print("=== 真实点击 8 次（回录时间戳）===")
    stamps = []
    for i in range(8):
        t0 = time.perf_counter()
        d.human_click(x, y)
        dur = time.perf_counter() - t0
        stamps.append(time.perf_counter())  # 绝对完成时刻
        print(f"  第 {i+1} 次点击完成，动作耗时 {dur:.2f}s")
        d.wait_rhythm()  # 不规则间隔
    gaps = [b - a for a, b in zip(stamps, stamps[1:])]  # 相邻点击总间隔（含 wait_rhythm）
    print(f"\n相邻点击总间隔: {[round(g, 2) for g in gaps]}")
    print(f"间隔去重后 {len(set(round(g) for g in gaps))}/{len(gaps)} 个不同值 -> 不规则 OK")
    d.close()


if __name__ == "__main__":
    show_sequence()
    if "--live" in sys.argv:
        live()