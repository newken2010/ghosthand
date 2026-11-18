# -*- coding: utf-8 -*-
"""GhostHand WebSocket 网关 —— AI / 扩展的接入点。

协议（JSON over WebSocket）
==========================
请求::

    {"cmd": "attach"}                          # 连已开浏览器(9222)
    {"cmd": "launch", "user_data_dir": "..."}  # 自带实例
    {"cmd": "goto", "url": "https://..."}
    {"cmd": "click", "x": 100, "y": 200}       # 拟人单击（贝塞尔轨迹）
    {"cmd": "type", "text": "hello"}           # 拟人打字（先点聚焦可选 x/y）
    {"cmd": "scroll", "delta": 800}
    {"cmd": "hold_drag", "x0":..,"y0":..,"x1":..,"y1":..,"hold":1.5}
    {"cmd": "read"}                            # 返回正文+标题
    {"cmd": "screenshot"}                      # 返回 base64 PNG
    {"cmd": "rhythm_gap"}                      # 返回一个不规则间隔（秒）
    {"cmd": "queue_add", "urls": [...], "action": "read"}
    {"cmd": "queue_run", "pace": "human", "limit": 10}
    {"cmd": "queue_status"}

响应::

    {"type": "result", "cmd": "...", "ok": true, "data": {...}}
    {"type": "error", "cmd": "...", "ok": false, "error": "..."}

典型 AI 工作流（"派 AI 去帮我看回来"）：
  1. AI 收到"看看这个页面"的任务 → ``goto``
  2. AI ``screenshot`` 看图（或 ``read`` 读正文）
  3. 发现滑块 → AI 从图里量出缺口 x → ``hold_drag``（长按拖过去）
  4. 批量页面 → ``queue_add`` + ``queue_run``（human 档限速）
"""

from __future__ import annotations

import asyncio
import base64
import json
import tempfile
import threading
from pathlib import Path
from typing import Optional

from .driver import GhostDriver
from .queue import TaskQueue


class Gateway:
    """网关核心：持有驱动器与队列，处理命令。线程安全用锁保护驱动器。"""

    def __init__(self, cdp_url: str = "http://127.0.0.1:9222", pace: str = "normal") -> None:
        self.cdp_url = cdp_url
        self.pace = pace
        self.driver: Optional[GhostDriver] = None
        self.queue: Optional[TaskQueue] = None
        self._lock = threading.Lock()

    # ---------------- 命令处理 ----------------

    def handle(self, msg: dict) -> dict:
        cmd = msg.get("cmd", "")
        try:
            with self._lock:
                data = self._dispatch(cmd, msg)
            return {"type": "result", "cmd": cmd, "ok": True, "data": data}
        except Exception as e:
            return {"type": "error", "cmd": cmd, "ok": False, "error": f"{type(e).__name__}: {e}"}

    def _dispatch(self, cmd: str, msg: dict) -> dict:
        if cmd == "ping":
            return {"pong": True}
        if cmd == "attach":
            self.driver = GhostDriver(cdp_url=msg.get("cdp_url", self.cdp_url), pace=msg.get("pace", self.pace))
            # 默认开新标签页，不劫持用户正在看的页面；url_match 可显式指定复用某页
            self.driver.attach(url_match=msg.get("url_match"), new_tab=not msg.get("url_match"))
            from .stealth import apply_stealth

            apply_stealth(self.driver)
            return {"url": self.driver.page.url}
        if cmd == "launch":
            self.driver = GhostDriver(pace=msg.get("pace", self.pace))
            self.driver.launch(msg["user_data_dir"], headless=msg.get("headless", False))
            from .stealth import apply_stealth

            apply_stealth(self.driver)
            return {"url": self.driver.page.url}
        self._require_driver()
        if cmd == "goto":
            self.driver.page.goto(msg["url"], wait_until="domcontentloaded", timeout=30000)
            return {"url": self.driver.page.url}
        if cmd == "click":
            self.driver.human_click(msg["x"], msg["y"])
            return {}
        if cmd == "type":
            self.driver.human_type(msg["text"], msg.get("x"), msg.get("y"))
            return {}
        if cmd == "scroll":
            self.driver.human_scroll(msg["delta"])
            return {}
        if cmd == "hold_drag":
            self.driver.hold_drag(msg["x0"], msg["y0"], msg["x1"], msg["y1"], msg.get("hold", 1.5))
            return {}
        if cmd == "read":
            pg = self.driver.page
            text = pg.evaluate("() => document.body ? document.body.innerText : ''")
            return {"title": pg.title(), "url": pg.url, "text": (text or "")[:20000]}
        if cmd == "screenshot":
            with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
                path = f.name
            self.driver.page.screenshot(path=path)
            b64 = base64.b64encode(Path(path).read_bytes()).decode()
            Path(path).unlink(missing_ok=True)
            return {"png_base64": b64}
        if cmd == "rhythm_gap":
            return {"gap": self.driver.rhythm_gap()}
        if cmd == "queue_add":
            self.queue = self.queue or TaskQueue(
                self.driver, state_path=msg.get("state_path", "ghosthand_queue.jsonl"), pace=msg.get("pace", self.pace)
            )
            self.queue.add_many(msg["urls"], msg.get("action", "read"))
            return {"pending": len(self.queue.pending)}
        if cmd == "queue_run":
            if not self.queue:
                raise RuntimeError("先 queue_add")
            return self.queue.run(limit=msg.get("limit"), pace=msg.get("pace", self.pace))
        if cmd == "queue_status":
            if not self.queue:
                return {"tasks": 0}
            return {
                "tasks": len(self.queue.tasks),
                "pending": len(self.queue.pending),
                "done": sum(1 for t in self.queue.tasks if t.status == "done"),
                "failed": sum(1 for t in self.queue.tasks if t.status == "failed"),
            }
        raise ValueError(f"未知命令: {cmd}")

    def _require_driver(self) -> None:
        if self.driver is None:
            raise RuntimeError("先 attach 或 launch")


async def serve(host: str = "127.0.0.1", port: int = 8765, cdp_url: str = "http://127.0.0.1:9222", pace: str = "normal"):
    """启动 WS 网关服务。"""
    import websockets

    gw = Gateway(cdp_url=cdp_url, pace=pace)

    async def _handler(ws):
        async for raw in ws:
            try:
                msg = json.loads(raw)
            except Exception:
                await ws.send(json.dumps({"type": "error", "ok": False, "error": "bad json"}))
                continue
            resp = await asyncio.get_running_loop().run_in_executor(None, gw.handle, msg)
            await ws.send(json.dumps(resp, ensure_ascii=False))

    print(f"[ghosthand] WS 网关监听 ws://{host}:{port}  (CDP: {cdp_url}, pace: {pace})")
    async with websockets.serve(_handler, host, port):
        await asyncio.Future()  # 永久运行


def main() -> None:
    import argparse

    ap = argparse.ArgumentParser(description="GhostHand WS 网关")
    ap.add_argument("--host", default="127.0.0.1")
    ap.add_argument("--port", type=int, default=8765)
    ap.add_argument("--cdp", default="http://127.0.0.1:9222")
    ap.add_argument("--pace", default="normal", choices=["cautious", "normal", "brisk"])
    a = ap.parse_args()
    asyncio.run(serve(a.host, a.port, a.cdp, a.pace))


if __name__ == "__main__":
    main()