# -*- coding: utf-8 -*-
"""GhostHand 命令行入口。

用法::

    python -m ghosthand serve [--port 8765] [--pace human]
    python -m ghosthand run <url> [--pace normal]      # attach 已开浏览器，拟人浏览并读正文
    python -m ghosthand queue <urls.txt> [--pace human] # 批量队列（断点续传）
    python -m ghosthand selftest                        # 本地测试页验证拟人动作（无网络依赖）
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> None:
    ap = argparse.ArgumentParser(prog="ghosthand", description="GhostHand 拟人浏览器自动化")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("serve", help="启动 WS 网关")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8765)
    p.add_argument("--cdp", default="http://127.0.0.1:9222")
    p.add_argument("--pace", default="normal", choices=["cautious", "normal", "brisk"])

    p = sub.add_parser("run", help="attach 已开浏览器，拟人浏览一个 URL")
    p.add_argument("url")
    p.add_argument("--cdp", default="http://127.0.0.1:9222")
    p.add_argument("--pace", default="normal", choices=["cautious", "normal", "brisk"])
    p.add_argument("--seed", type=int, default=None)

    p = sub.add_parser("queue", help="批量跑 URL 队列（JSONL 断点续传）")
    p.add_argument("urls", help="每行一个 URL 的文本文件")
    p.add_argument("--cdp", default="http://127.0.0.1:9222")
    p.add_argument("--pace", default="human", choices=["cautious", "normal", "brisk"])
    p.add_argument("--state", default="ghosthand_queue.jsonl")
    p.add_argument("--limit", type=int, default=None)

    sub.add_parser("selftest", help="本地测试页验证（不联网）")

    a = ap.parse_args()

    if a.cmd == "serve":
        from .server import serve as _serve

        import asyncio

        asyncio.run(_serve(a.host, a.port, a.cdp, a.pace))
        return

    if a.cmd == "run":
        from .driver import GhostDriver
        from .stealth import apply_stealth

        d = GhostDriver(cdp_url=a.cdp, pace=a.pace, seed=a.seed)
        d.attach(new_tab=True)  # 开新标签，不动用户当前页面
        apply_stealth(d)
        d.page.goto(a.url, wait_until="domcontentloaded", timeout=30000)
        d.human_scroll(700)
        text = d.page.evaluate("() => document.body ? document.body.innerText : ''")
        print("TITLE:", d.page.title())
        print("URL:", d.page.url)
        print("TEXT:", (text or "")[:3000])
        d.close()
        return

    if a.cmd == "queue":
        from .driver import GhostDriver
        from .queue import TaskQueue
        from .stealth import apply_stealth

        urls = [l.strip() for l in Path(a.urls).read_text(encoding="utf-8").splitlines() if l.strip()]
        d = GhostDriver(cdp_url=a.cdp, pace=a.pace)
        d.attach(new_tab=True)  # 开新标签，不动用户当前页面
        apply_stealth(d)
        q = TaskQueue(d, state_path=a.state, pace=a.pace)
        q.add_many(urls)
        stats = q.run(limit=a.limit)
        print("STATS:", stats)
        d.close()
        return

    if a.cmd == "selftest":
        from .selftest import run_selftest

        ok = run_selftest()
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()