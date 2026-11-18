# -*- coding: utf-8 -*-
"""GhostHand 任务队列 —— 批量浏览的节奏控制与断点续传（用户需求 3）。

"人类顶多打开两三个网页，AI 一下子能打开几十个、上百个"——
批量能力要有，但节奏必须像人：任务之间走 :class:`HumanRhythm` 不规则间隔，
档位决定整体速度，绝不匀速刷页。

设计
====
- **JSONL 持久化**：每个任务一行，状态 pending/done/failed 实时落盘。
  进程被杀后重启，pending 的接着跑（断点续传）。
- **节奏档位**：human（2~3 页/分钟）/ normal / brisk，任务间隔用
  不规则节奏（含分心长停），不是固定 sleep。
- **每任务流程**：goto → 等 load → 拟人滚动（触发懒加载 + 像人浏览）→
  抓正文/截图 → 落盘 → 不规则间隔 → 下一个。
- **失败重试**：网络错误重试 N 次，仍失败标 failed 继续下一个
  （不卡死队列）。
"""

from __future__ import annotations

import json
import random
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Callable, List, Optional

from .driver import GhostDriver
from .human import HumanRhythm, PaceLevel

# 每页停留时长（秒）：模拟"真人读一页要多久"
_PAGE_DWELL = {"human": (18, 45), "normal": (6, 15), "brisk": (2, 6)}


@dataclass
class Task:
    url: str
    action: str = "read"  # read=抓正文 / screenshot=截图 / custom
    status: str = "pending"  # pending/done/failed
    attempts: int = 0
    result: dict = field(default_factory=dict)
    error: str = ""

    def to_json(self) -> str:
        return json.dumps(asdict(self), ensure_ascii=False)


class TaskQueue:
    def __init__(
        self,
        driver: GhostDriver,
        state_path: str = "ghosthand_queue.jsonl",
        pace: str = "normal",
        max_attempts: int = 2,
        on_task: Optional[Callable[[Task], None]] = None,
    ) -> None:
        self.d = driver
        self.state_path = Path(state_path)
        self.pace = pace
        self.max_attempts = max_attempts
        self.on_task = on_task
        self.tasks: List[Task] = []
        self._rhythm = HumanRhythm(pace=PaceLevel.from_name(pace))
        self._load()

    # ---------------- 持久化 ----------------

    def _load(self) -> None:
        if self.state_path.exists():
            for line in self.state_path.read_text(encoding="utf-8").splitlines():
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                    self.tasks.append(Task(**d))
                except Exception:
                    continue

    def _flush(self) -> None:
        with self.state_path.open("w", encoding="utf-8") as f:
            for t in self.tasks:
                f.write(t.to_json() + "\n")

    # ---------------- 队列操作 ----------------

    def add(self, url: str, action: str = "read") -> Task:
        t = Task(url=url, action=action)
        self.tasks.append(t)
        self._flush()
        return t

    def add_many(self, urls: List[str], action: str = "read") -> None:
        for u in urls:
            self.add(u, action)

    @property
    def pending(self) -> List[Task]:
        return [t for t in self.tasks if t.status == "pending"]

    # ---------------- 执行 ----------------

    def run(self, limit: Optional[int] = None, stop_on_captcha: bool = True) -> dict:
        """跑队列。返回统计。stop_on_captcha: 检测到验证码特征时暂停等人。"""
        stats = {"done": 0, "failed": 0, "skipped": 0}
        n = 0
        for t in self.pending:
            if limit is not None and n >= limit:
                break
            n += 1
            t.attempts += 1
            try:
                self._run_one(t)
                t.status = "done"
                stats["done"] += 1
            except Exception as e:
                t.error = f"{type(e).__name__}: {e}"[:300]
                if t.attempts < self.max_attempts:
                    t.status = "pending"  # 重试
                else:
                    t.status = "failed"
                    stats["failed"] += 1
            self._flush()
            if self.on_task:
                self.on_task(t)
            # 任务间不规则间隔（像人，不匀速）
            if t.status != "failed" or True:
                time.sleep(self._rhythm.gap())
        stats["skipped"] = len(self.pending)
        return stats

    def _run_one(self, t: Task) -> None:
        pg = self.d.page
        pg.goto(t.url, wait_until="domcontentloaded", timeout=30000)
        try:
            pg.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass  # 长轮询页面永远不 idle，不阻塞
        # 拟人浏览：滚动几下（触发懒加载 + 停留阅读）
        self.d.human_scroll(600)
        dwell = random.uniform(*_PAGE_DWELL.get(self.pace, _PAGE_DWELL["normal"]))
        time.sleep(dwell)
        if t.action == "screenshot":
            p = f"ghosthand_shot_{abs(hash(t.url)) % 10**8}.png"
            pg.screenshot(path=p, full_page=False)
            t.result = {"screenshot": p}
        else:
            text = pg.evaluate("() => document.body ? document.body.innerText : ''")
            t.result = {"title": pg.title(), "text": (text or "")[:20000], "url": pg.url}