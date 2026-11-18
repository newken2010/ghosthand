# -*- coding: utf-8 -*-
"""GhostHand 本地自检 —— 不联网，用本地测试页真实验证拟人动作。

验证点（全部读页面回录的数据，不是"看起来动了"）：
1. **trusted 事件**：点击/按键的 isTrusted 必须为 true（untrusted 会被 React 忽略）
2. **长按生效**：mousedown→mouseup 时长 ≥ 1.2s（"按住一两秒"）
3. **拖动到位**：拖动终点接近目标（过冲回拉后收敛）
4. **不规则节奏**：连续点击间隔不全相等、按键间隔有变化
5. **轨迹非直线**：鼠标经过的采样点路径长 ≥ 直线距离

用法：Edge 以 --remote-debugging-port=9222 启动后，运行
    python -m ghosthand selftest
"""

from __future__ import annotations

import json
import math
import random
import sys
import tempfile
import time
from pathlib import Path

# 测试页：滑块 + 输入框 + 计数器，所有交互录进 window.__gh
FIXTURE_HTML = """<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>
 body{font-family:sans-serif;margin:40px}
 #track{width:600px;height:44px;background:#dfe6ee;border-radius:22px;position:relative;margin:20px 0}
 #handle{width:52px;height:44px;background:#4a7;border-radius:22px;position:absolute;left:0;top:0;cursor:pointer}
 #target{position:absolute;left:480px;top:0;width:52px;height:44px;background:#eee;border:2px dashed #999;border-radius:8px}
 input{font-size:16px;padding:8px;width:300px}
 #log{color:#666;font-size:12px;margin-top:20px;white-space:pre-wrap}
</style></head><body>
<h3>GhostHand selftest</h3>
<div id="track"><div id="target"></div><div id="handle"></div></div>
<input id="inp" placeholder="type here">
<button id="btn">click me</button>
<div id="log"></div>
<script>
window.__gh = {clicks:[], keys:[], drag:{down:null,up:null,x0:null,x1:null}, moves:[]};
const h = document.getElementById('handle');
h.addEventListener('mousedown', e => { window.__gh.drag.down = performance.now(); window.__gh.drag.x0 = e.clientX; });
window.addEventListener('mouseup', e => { if (window.__gh.drag.down){ window.__gh.drag.up = performance.now(); window.__gh.drag.x1 = e.clientX; } });
window.addEventListener('mousemove', e => { window.__gh.moves.push([e.clientX, e.clientY, e.isTrusted]); });
document.getElementById('btn').addEventListener('click', e => { window.__gh.clicks.push({t: performance.now(), trusted: e.isTrusted}); });
document.getElementById('inp').addEventListener('keydown', e => { window.__gh.keys.push({t: performance.now(), key: e.key, trusted: e.isTrusted}); });
</script></body></html>
"""


def _fixture_url() -> str:
    p = Path(tempfile.gettempdir()) / "ghosthand_selftest.html"
    p.write_text(FIXTURE_HTML, encoding="utf-8")
    return p.as_uri()


def run_selftest(verbose: bool = True) -> bool:
    from .driver import GhostDriver
    from .stealth import apply_stealth

    results: list = []

    def check(name: str, ok: bool, detail: str = "") -> None:
        results.append((name, ok, detail))
        if verbose:
            print(f"{'PASS' if ok else 'FAIL'}  {name}  {detail}")

    d = GhostDriver(pace="normal", seed=1234)
    try:
        d.attach(new_tab=True)  # 开新标签页，不动用户当前页面
    except Exception as e:
        print(f"FAIL  连接浏览器失败: {e}")
        print("      （需要 Edge/Chrome 以 --remote-debugging-port=9222 启动）")
        return False
    apply_stealth(d)
    pg = d.page
    pg.goto(_fixture_url(), wait_until="load")

    # ---- 1) 拟人点击按钮 ----
    box = pg.locator("#btn").bounding_box()
    d.human_click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
    time.sleep(0.3)
    gh = pg.evaluate("() => window.__gh")
    check("点击被记录", len(gh["clicks"]) >= 1, f"clicks={len(gh['clicks'])}")
    check("trusted 事件", all(c["trusted"] for c in gh["clicks"]), "isTrusted=true")

    # ---- 2) 不规则节奏：间隔不全相等 ----
    gaps = [b["t"] - a["t"] for a, b in zip(gh["clicks"], gh["clicks"][1:])]
    # 多点几次凑样本
    for _ in range(3):
        d.human_click(box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
        time.sleep(0.2)
    gh = pg.evaluate("() => window.__gh")
    gaps = [b["t"] - a["t"] for a, b in zip(gh["clicks"], gh["clicks"][1:])]
    check("多次点击成功", len(gh["clicks"]) >= 4, f"clicks={len(gh['clicks'])}")
    varied = len(set(round(g) for g in gaps)) >= max(1, len(gaps) - 1)
    check("点击间隔不规则", varied, f"gaps={[round(g) for g in gaps]}")

    # ---- 3) 轨迹非直线 ----
    moves = [m for m in gh["moves"] if m[2]]  # trusted 的 move
    if len(moves) >= 5:
        path = sum(math.hypot(b[0] - a[0], b[1] - a[1]) for a, b in zip(moves, moves[1:]))
        direct = math.hypot(moves[-1][0] - moves[0][0], moves[-1][1] - moves[0][1])
        check("鼠标轨迹非瞬移", path > direct * 1.05, f"path={path:.0f}px direct={direct:.0f}px 采样{len(moves)}点")
    else:
        check("鼠标轨迹非瞬移", False, f"move 采样不足: {len(moves)}")

    # ---- 4) 长按拖动：按住 ~1.5s，拖到目标 ----
    hb = pg.locator("#handle").bounding_box()
    tb = pg.locator("#target").bounding_box()
    pg.evaluate("() => { window.__gh.drag = {down:null,up:null,x0:null,x1:null}; window.__gh.moves = []; }")
    d.hold_drag(
        hb["x"] + hb["width"] / 2, hb["y"] + hb["height"] / 2,
        tb["x"] + tb["width"] / 2, tb["y"] + tb["height"] / 2,
        hold_seconds=1.5,
    )
    time.sleep(0.3)
    gh = pg.evaluate("() => window.__gh")
    drag = gh["drag"]
    if drag["down"] and drag["up"]:
        hold_ms = drag["up"] - drag["down"]
        check("长按生效(≥1.2s)", hold_ms >= 1200, f"按住 {hold_ms:.0f}ms")
        err = abs(drag["x1"] - (tb["x"] + tb["width"] / 2))
        check("拖动到位", err < 30, f"终点误差 {err:.0f}px")
    else:
        check("长按生效(≥1.2s)", False, "未录到 drag 事件")

    # ---- 5) 拟人打字 ----
    pg.locator("#inp").click()
    time.sleep(0.2)
    d.human_type("GhostHand 2026", clear=True)
    time.sleep(0.3)
    gh = pg.evaluate("() => window.__gh")
    val = pg.locator("#inp").input_value()
    check("打字进输入框", val == "GhostHand 2026", f"value={val!r}")
    key_gaps = [b["t"] - a["t"] for a, b in zip(gh["keys"], gh["keys"][1:]) if b["t"] > a["t"]]
    check("击键间隔不规则", len(set(round(g) for g in key_gaps)) > 3, f"{len(key_gaps)} 个间隔")

    # ---- 6) stealth：webdriver 已抹 ----
    wd = pg.evaluate("() => navigator.webdriver")
    check("webdriver 已抹除", wd in (None, False, "undefined"), f"navigator.webdriver={wd!r}")

    d.screenshot(str(Path(tempfile.gettempdir()) / "ghosthand_selftest.png"))
    passed = sum(1 for _, ok, _ in results if ok)
    print(f"\n自检结果: {passed}/{len(results)} 通过")
    return passed == len(results)


if __name__ == "__main__":
    sys.exit(0 if run_selftest() else 1)