"""Claude Notify CLI 入口

支持两种模式：
1. 监控模式：监控 Claude Code 会话状态，发送通知
2. 聊天模式：飞书双向交互，调用 Claude CLI
"""

from __future__ import annotations

import argparse
import signal
import sys
from pathlib import Path

from .config import MonitorConfig


def parse_args() -> argparse.Namespace:
    """解析命令行参数"""
    parser = argparse.ArgumentParser(
        prog="claude-notify",
        description="Claude Code monitor and Feishu chat bot",
    )

    parser.add_argument(
        "mode",
        nargs="?",
        default="monitor",
        choices=["monitor", "chat", "both"],
        help="运行模式: monitor=监控, chat=聊天, both=两者都运行",
    )

    parser.add_argument(
        "--config", "-c",
        type=Path,
        help="配置文件路径",
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="发送测试通知",
    )

    return parser.parse_args()


def run_monitor(config: MonitorConfig) -> None:
    """运行监控模式"""
    from .monitor import ClaudeMonitor

    monitor = ClaudeMonitor(config)

    def shutdown(signum, frame):
        print("\n[cli] 正在退出...")
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    monitor.run()


def run_chat(config: MonitorConfig) -> None:
    """运行聊天模式"""
    from .chat.feishu_bot import FeishuChatBot
    from .ssh.connection import ServerConfig

    if not config.feishu.app_id or not config.feishu.app_secret:
        print("错误: 未配置飞书应用凭证")
        sys.exit(1)

    # 转换服务器配置
    servers = [
        ServerConfig(
            name=s.name,
            ssh_host=s.ssh_host or "",
            is_local=s.is_local,
        )
        for s in config.servers
    ]

    bot = FeishuChatBot(
        app_id=config.feishu.app_id,
        app_secret=config.feishu.app_secret,
        allowed_user_id=config.feishu.user_id or None,
        servers=servers,
    )

    def shutdown(signum, frame):
        print("\n[cli] 正在退出...")
        sys.exit(0)

    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)

    bot.start()


def run_both(config: MonitorConfig) -> None:
    """同时运行监控和聊天"""
    import threading
    from .monitor import ClaudeMonitor
    from .chat.feishu_bot import FeishuChatBot
    from .ssh.connection import ServerConfig

    # 启动监控（后台线程）
    monitor = ClaudeMonitor(config)
    monitor_thread = threading.Thread(target=monitor.run, daemon=True, name="monitor")
    monitor_thread.start()

    # 启动聊天（主线程）
    if config.feishu.app_id and config.feishu.app_secret:
        # 转换服务器配置
        servers = [
            ServerConfig(
                name=s.name,
                ssh_host=s.ssh_host or "",
                is_local=s.is_local,
            )
            for s in config.servers
        ]

        bot = FeishuChatBot(
            app_id=config.feishu.app_id,
            app_secret=config.feishu.app_secret,
            allowed_user_id=config.feishu.user_id or None,
            servers=servers,
        )
        bot.start()
    else:
        print("[cli] 未配置飞书凭证，只运行监控模式")
        monitor.run()


def test_notification(config: MonitorConfig) -> None:
    """发送测试通知"""
    from .notify.feishu import FeishuNotifier

    notifier = FeishuNotifier(config.feishu)

    print("发送测试通知...")

    success = notifier.send_card(
        title="🧪 测试通知",
        content="这是一条测试通知，用于验证飞书配置是否正确。",
        color="blue",
    )

    if success:
        print("✅ 通知发送成功！")
    else:
        print("❌ 通知发送失败，请检查配置")


def main() -> None:
    """主入口"""
    args = parse_args()

    # 加载配置
    config = MonitorConfig.load(args.config)

    # 执行命令
    if args.test:
        test_notification(config)
    elif args.mode == "monitor":
        run_monitor(config)
    elif args.mode == "chat":
        run_chat(config)
    elif args.mode == "both":
        run_both(config)


if __name__ == "__main__":
    main()
