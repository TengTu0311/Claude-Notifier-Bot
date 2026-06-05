"""Claude Code 通知机器人 CLI"""

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
        description="Claude Code task notification via Feishu",
    )
    
    parser.add_argument(
        "--config", "-c",
        type=Path,
        help="配置文件路径",
    )
    
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="试运行模式（不发送通知）",
    )
    
    parser.add_argument(
        "--test",
        action="store_true",
        help="发送测试通知",
    )
    
    return parser.parse_args()


def run_monitor(config: MonitorConfig) -> None:
    """运行监控"""
    from .monitor import ClaudeMonitor
    
    monitor = ClaudeMonitor(config)
    
    # 处理信号
    def shutdown(signum, frame):
        print("\n[cli] 正在退出...")
        monitor.stop()
        sys.exit(0)
    
    signal.signal(signal.SIGINT, shutdown)
    signal.signal(signal.SIGTERM, shutdown)
    
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
    
    # 验证配置
    if not config.servers:
        print("错误: 未配置服务器")
        print("请在配置文件中添加服务器:")
        print("  ~/.config/claude-notify/config.json")
        sys.exit(1)
    
    if not config.feishu.webhook_url and not config.feishu.app_id:
        print("错误: 未配置飞书通知")
        print("请在配置文件中添加飞书 Webhook 或应用凭证")
        sys.exit(1)
    
    # 执行命令
    if args.test:
        test_notification(config)
    else:
        run_monitor(config)


if __name__ == "__main__":
    main()
