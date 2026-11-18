# -*- coding: utf-8 -*-
"""演示 5：browser-use Agent + GhostHand 拟人中间件（千问建议的落地姿势）。

原理：browser-use 的 Mouse.click 是"瞬移式" CDP 事件（同一坐标直接
pressed+released，无移动轨迹）——典型机器特征。GhostHand 中间件把它
monkey patch 成贝塞尔轨迹 + 不规则节奏，Agent 决策逻辑一行不改。

本演示只验证中间件安装/还原（不真正跑 Agent——跑 Agent 需要配 LLM key，
按 browser-use 官方文档来）。

运行：python examples/05_browser_use_agent.py
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))


def main() -> None:
    from ghosthand.agent import humanize_browser_use

    undo = humanize_browser_use(pace="normal", seed=42)
    print("中间件已安装：browser-use 的 Mouse.click/move、Keyboard.type 已变为拟人版")

    from browser_use.actor.mouse import Mouse

    print(f"  Mouse.click 已 patch: {getattr(Mouse.click, '__name__', '') == 'click' and Mouse._ghosthand}")
    print(f"  Mouse.move  已 patch: {Mouse._ghosthand}")

    undo()
    print("已还原（测试用）")

    print("""
真正跑 Agent 的姿势（需要配 LLM）：

    from browser_use import Agent
    from browser_use.llm import ChatOpenAI   # 或你用的模型
    from ghosthand.agent import humanize_browser_use

    humanize_browser_use(pace="cautious")    # 先打补丁
    agent = Agent(task="打开 example.com 告诉我标题", llm=ChatOpenAI(...))
    agent.run_sync()                          # LLM 决策照旧，"手"变成人的手
""")


if __name__ == "__main__":
    main()