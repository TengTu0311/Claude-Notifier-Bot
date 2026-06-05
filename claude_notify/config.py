"""配置管理"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

from .notify.feishu import FeishuConfig


@dataclass
class ServerConfig:
    """服务器配置"""
    name: str
    ssh_host: str = ""  # SSH Host 别名，为空表示本地
    is_local: bool = False  # 是否本地服务器


@dataclass
class NotifyConfig:
    """通知配置"""
    on_task_complete: bool = True
    on_task_start: bool = True
    on_long_running: bool = True
    long_running_threshold_minutes: int = 30


@dataclass
class MonitorConfig:
    """监控器配置"""
    servers: list[ServerConfig] = field(default_factory=list)
    poll_interval: int = 30  # 轮询间隔（秒）
    notify: NotifyConfig = field(default_factory=NotifyConfig)
    feishu: FeishuConfig = field(default_factory=FeishuConfig)
    
    @classmethod
    def load(cls, config_path: Optional[Path] = None) -> MonitorConfig:
        """从配置文件加载"""
        if config_path is None:
            config_path = Path.home() / ".config" / "claude-notify" / "config.json"
        
        if not config_path.exists():
            return cls()
        
        with open(config_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        
        servers = [ServerConfig(**s) for s in data.get("servers", [])]
        notify = NotifyConfig(**data.get("notify", {}))
        feishu = FeishuConfig(**data.get("feishu", {}))
        
        return cls(
            servers=servers,
            poll_interval=data.get("poll_interval", 30),
            notify=notify,
            feishu=feishu,
        )
