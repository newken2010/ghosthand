# -*- coding: utf-8 -*-
"""演示 3：批量浏览 + 限速（用户需求 3）。

"AI 快，但不能太快。人类顶多打开两三个网页，AI 一下子能打开几十个、
上百个。"——批量能力 + 人类节奏限速。

本演示：本地起 N 个静态页（file://，不联网），用 TaskQueue 以 human 档
批量浏览：任务间不规则间隔 + 每页停留阅读 + 断点续传（JSONL）。

运行：python examples/03_batch_browse.py [--n 6] [--pace human]
"""
import argparse
import http.server
import socketserver
import sys
import tempfile
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

PAGES = {}


def make_pages(n: int) -> str:
    """生成 n 个本地静态页，起一个临时 HTTP 服务，返回 base url。"""
    root = Path(tempfile.mkdtemp(prefix="ghosthand_pages_"))
    for i in range(n):
        (root / f"page{i}.html").write_text(
            f"<!DOCTYPE html><html><head><meta charset=utf-8><title>页面 {i}</title></head>"
            f"<body><h1>GhostHand 批量浏览测试页 {i}</h1>"
            f"<p>{'内容' * 200}</p></body></html>",
            encoding="utf-8",
        )

    class H(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *a, **kw):
            super().__init__(*a, directory=str(root), **kw)

        def log_message(self, *a):
            pass

    class S(socketserver.TCPServer):
        allow_reuse_address = True

    srv = S(("127.0.0.1", 0), H)
    port = srv.server_address[1]
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    return f"http://127.0.0.1:{port}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=6)
    ap.add_argument("--pace", default="human", choices=["cautious", "normal", "brisk"])
    ap.add_argument("--state", default=str(Path(tempfile.gettempdir()) / "ghosthand_demo_queue.jsonl"))
    a = ap.parse_args()

    from ghosthand import GhostDriver, TaskQueue
    from ghosthand.stealth import apply_stealth

    base = make_pages(a.n)
    urls = [f"{base}/page{i}.html" for i in range(a.n)]

    d = GhostDriver(pace=a.pace)
    d.attach(new_tab=True)
    apply_stealth(d)

    q = TaskQueue(d, state_path=a.state, pace=a.pace)
    # 演示断点续传：先删旧状态
    Path(a.state).unlink(missing_ok=True)
    q = TaskQueue(d, state_path=a.state, pace=a.pace)
    q.add_many(urls)

    print(f"批量浏览 {a.n} 页，档位 {a.pace}（human≈2~3页/分钟，含不规则间隔+阅读停留）")
    print("提示：中途 Ctrl+C 杀掉，重跑会从 pending 继续（断点续传）\n")
    import time

    t0 = time.time()
    stats = q.run()
    print(f"\nSTATS: {stats}  总耗时 {time.time()-t0:.0f}s")
    for t in q.tasks:
        title = (t.result or {}).get("title", t.error[:40])
        print(f"  [{t.status:6s}] {t.url.split('/')[-1]:12s} {title}")
    d.close()


if __name__ == "__main__":
    main()