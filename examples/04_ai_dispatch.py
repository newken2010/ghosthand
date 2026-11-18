# -*- coding: utf-8 -*-
"""演示 4：AI 派单 —— 通过 WS 网关驱动浏览器（用户需求 3 完整工作流）。

"有时候我们爬不到，就派 AI 去帮我看回来。"

本演示一条龙：
  1. 后台起 WS 网关（ghosthand.server）
  2. 客户端连接 → attach Edge(9222) → goto 本地测试页（带滑块）
  3. 客户端"看图"（screenshot 拿 base64；真实场景这里接 AI 视觉模型量缺口）
  4. 客户端下发 hold_drag（长按 1.5s 拖过滑块）
  5. read 回正文 → 任务完成

这就是"AI 派单"的最小闭环：AI 只出决策（目标 x），执行全部走拟人引擎。

运行：Edge 9222 启动后
    python examples/04_ai_dispatch.py
"""
import asyncio
import base64
import json
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

FIXTURE = """<!DOCTYPE html><html><head><meta charset="utf-8"><style>
 body{font-family:sans-serif;margin:60px}
 #track{width:600px;height:44px;background:#dfe6ee;border-radius:22px;position:relative}
 #handle{width:52px;height:44px;background:#4a7;border-radius:22px;position:absolute;left:0;top:0}
 #target{position:absolute;left:480px;top:0;width:52px;height:44px;border:2px dashed #666;border-radius:8px}
</style></head><body><h3>AI 派单测试页</h3>
<div id="track"><div id="target"></div><div id="handle"></div></div>
<script>
window.__r = {down:null,up:null,x1:null,ok:false};
const h = document.getElementById('handle');
h.addEventListener('mousedown', e => { window.__r.down = performance.now(); });
window.addEventListener('mouseup', e => {
  if (window.__r.down) { window.__r.up = performance.now(); window.__r.x1 = e.clientX;
    const t = document.getElementById('target').getBoundingClientRect();
    window.__r.ok = Math.abs(e.clientX - (t.x + t.width/2)) < 30; }
});
</script></body></html>
"""


async def ai_workflow(ws_url: str, page_url: str) -> None:
    import websockets

    async with websockets.connect(ws_url) as ws:
        async def call(cmd, **kw):
            await ws.send(json.dumps({"cmd": cmd, **kw}))
            while True:
                r = json.loads(await ws.recv())
                if r.get("cmd") == cmd:
                    return r

        # 1) attach
        r = await call("attach")
        print(f"[1] attach: ok={r['ok']} url={r.get('data', {}).get('url')}")

        # 2) goto 测试页
        r = await call("goto", url=page_url)
        print(f"[2] goto: {r['data']['url']}")

        # 3) "AI 看图"：截图（真实场景：把 png_base64 喂给视觉模型量缺口）
        r = await call("screenshot")
        png = r["data"]["png_base64"]
        print(f"[3] screenshot: {len(png)//1024}KB base64（此处 AI 视觉模型介入点）")
        # 简化：直接从页面读目标坐标（代替 AI 视觉识别）
        r2 = await call("read")
        print(f"[3b] read: {r2['data']['title']}")

        # 4) 长按拖动：AI 决策目标 x=504（target 中心），执行走拟人引擎
        r = await call("hold_drag", x0=76, y0=132, x1=506, y1=132, hold=1.5)
        print(f"[4] hold_drag(按住1.5s→拖到506): ok={r['ok']}")
        await asyncio.sleep(0.5)

        # 5) 验证
        r = await call("read")
        print(f"[5] read: {r['data']['text'][:60]!r}")

        # 6) 不规则间隔演示
        r = await call("rhythm_gap")
        print(f"[6] rhythm_gap: 下一次操作间隔 {r['data']['gap']:.2f}s（不规则）")


def main() -> None:
    import threading

    from ghosthand.server import Gateway, serve

    p = Path(tempfile.gettempdir()) / "ghosthand_ai_demo.html"
    p.write_text(FIXTURE, encoding="utf-8")

    # 后台起网关
    t = threading.Thread(target=lambda: asyncio.run(serve("127.0.0.1", 8765)), daemon=True)
    t.start()
    import time

    time.sleep(1.5)
    print("WS 网关已起: ws://127.0.0.1:8765\n")
    asyncio.run(ai_workflow("ws://127.0.0.1:8765", p.as_uri()))


if __name__ == "__main__":
    main()