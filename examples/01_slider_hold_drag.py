# -*- coding: utf-8 -*-
"""演示 1：长按拖动滑块（用户需求 2）。

场景还原："有的网站需要按住长时间把条子拖过去，点一下很快不行，
要按住大概一两秒钟的时间，再把长条拖过去。"

本演示在本地测试页上真刀真枪跑：attach Edge(9222) → 开新标签 →
加载带滑块的测试页 → SliderSolver 检测滑块柄 → 按住 1.5s → 分段拖到目标。

运行：Edge 以 --remote-debugging-port=9222 启动后
    python examples/01_slider_hold_drag.py
"""
import sys
import tempfile
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from ghosthand import GhostDriver, SliderSolver
from ghosthand.stealth import apply_stealth

FIXTURE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
 body{font-family:sans-serif;margin:60px}
 #track{width:600px;height:44px;background:#dfe6ee;border-radius:22px;position:relative}
 #handle{width:52px;height:44px;background:#4a7;border-radius:22px;position:absolute;left:0;top:0;cursor:pointer}
 #target{position:absolute;left:480px;top:0;width:52px;height:44px;border:2px dashed #666;border-radius:8px}
 #result{margin-top:20px;font-size:14px}
</style></head><body>
<h3>滑块测试页（模拟验证码）</h3>
<div id="track"><div id="target"></div><div id="handle"></div></div>
<div id="result">等待拖动…</div>
<script>
window.__r = {down:null, up:null, x0:null, x1:null, ok:false};
const h = document.getElementById('handle');
h.addEventListener('mousedown', e => { window.__r.down = performance.now(); window.__r.x0 = e.clientX; });
window.addEventListener('mouseup', e => {
  if (window.__r.down) { window.__r.up = performance.now(); window.__r.x1 = e.clientX;
    const t = document.getElementById('target').getBoundingClientRect();
    const err = Math.abs(e.clientX - (t.x + t.width/2));
    window.__r.ok = err < 30;
    document.getElementById('result').textContent =
      window.__r.ok ? `✅ 验证通过（误差 ${err.toFixed(0)}px，按住 ${((window.__r.up-window.__r.down)/1000).toFixed(2)}s）`
                    : `❌ 误差 ${err.toFixed(0)}px，按住 ${((window.__r.up-window.__r.down)/1000).toFixed(2)}s`;
  }
});
</script></body></html>
"""


def main() -> None:
    p = Path(tempfile.gettempdir()) / "ghosthand_slider_demo.html"
    p.write_text(FIXTURE, encoding="utf-8")

    d = GhostDriver(pace="normal", seed=2026)
    d.attach(new_tab=True)
    apply_stealth(d)
    d.page.goto(p.as_uri(), wait_until="load")

    solver = SliderSolver(d)
    handle = solver.find_handle()
    if not handle:
        print("未检测到滑块柄"); return
    print(f"滑块柄: cx={handle.cx:.0f} cy={handle.cy:.0f}")

    # 目标：测试页 target 元素中心（真实场景由 AI 看图量出，见 04 演示）
    tb = d.page.locator("#target").bounding_box()
    target_x = tb["x"] + tb["width"] / 2

    ok = solver.solve(gap_x=target_x, hold_seconds=1.5)
    r = d.page.evaluate("() => window.__r")
    print(f"结果: {'成功' if r['ok'] else '失败'} | "
          f"按住 {((r['up']-r['down'])/1000):.2f}s | 起点 {r['x0']:.0f} → 终点 {r['x1']:.0f} (目标 {target_x:.0f})")
    d.screenshot(str(Path(tempfile.gettempdir()) / "ghosthand_slider_demo.png"))
    print("截图: %TEMP%/ghosthand_slider_demo.png")
    d.close()


if __name__ == "__main__":
    main()