"""会话管理模块

管理 Claude Code 会话状态，支持跨设备会话恢复。
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Optional

# 会话数据存储路径
SESSIONS_DIR = Path.home() / ".config" / "claude-notify" / "sessions"


@dataclass
class ChatSession:
    """聊天会话"""
    user_id: str
    chat_id: str
    session_id: Optional[str] = None  # Claude CLI session ID
    model: str = "claude-sonnet-4-20250514"
    cwd: str = ""
    permission_mode: str = "bypassPermissions"
    last_active: float = field(default_factory=time.time)
    created_at: float = field(default_factory=time.time)


class SessionStore:
    """会话存储管理"""

    def __init__(self, storage_dir: Optional[Path] = None):
        self.storage_dir = storage_dir or SESSIONS_DIR
        self.storage_dir.mkdir(parents=True, exist_ok=True)
        self._sessions: dict[str, ChatSession] = {}
        self._load()

    def _load(self):
        """加载会话数据"""
        data_file = self.storage_dir / "sessions.json"
        if not data_file.exists():
            return

        try:
            with open(data_file, "r", encoding="utf-8") as f:
                data = json.load(f)

            for key, session_data in data.items():
                self._sessions[key] = ChatSession(**session_data)
        except Exception as e:
            print(f"[session_store] 加载失败: {e}")

    def _save(self):
        """保存会话数据"""
        data_file = self.storage_dir / "sessions.json"
        try:
            data = {}
            for key, session in self._sessions.items():
                data[key] = {
                    "user_id": session.user_id,
                    "chat_id": session.chat_id,
                    "session_id": session.session_id,
                    "model": session.model,
                    "cwd": session.cwd,
                    "permission_mode": session.permission_mode,
                    "last_active": session.last_active,
                    "created_at": session.created_at,
                }

            with open(data_file, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2, ensure_ascii=False)
        except Exception as e:
            print(f"[session_store] 保存失败: {e}")

    def _make_key(self, user_id: str, chat_id: str) -> str:
        """生成会话键"""
        return f"{user_id}:{chat_id}"

    def get_current(self, user_id: str, chat_id: str) -> ChatSession:
        """获取当前会话（不存在则创建）"""
        key = self._make_key(user_id, chat_id)

        if key not in self._sessions:
            self._sessions[key] = ChatSession(
                user_id=user_id,
                chat_id=chat_id,
            )
            self._save()

        session = self._sessions[key]
        session.last_active = time.time()
        return session

    def update_session(
        self,
        user_id: str,
        chat_id: str,
        session_id: Optional[str] = None,
        model: Optional[str] = None,
        cwd: Optional[str] = None,
    ):
        """更新会话信息"""
        session = self.get_current(user_id, chat_id)

        if session_id is not None:
            session.session_id = session_id
        if model is not None:
            session.model = model
        if cwd is not None:
            session.cwd = cwd

        session.last_active = time.time()
        self._save()

    def clear_session(self, user_id: str, chat_id: str):
        """清除会话（开始新会话）"""
        key = self._make_key(user_id, chat_id)

        if key in self._sessions:
            old_session = self._sessions[key]
            # 保留模型和工作目录设置
            self._sessions[key] = ChatSession(
                user_id=user_id,
                chat_id=chat_id,
                model=old_session.model,
                cwd=old_session.cwd,
                permission_mode=old_session.permission_mode,
            )
            self._save()

    def get_all_sessions(self) -> dict[str, ChatSession]:
        """获取所有会话"""
        return dict(self._sessions)

    def cleanup_expired(self, max_age_hours: int = 24):
        """清理过期会话"""
        cutoff = time.time() - (max_age_hours * 3600)
        expired_keys = [
            key for key, session in self._sessions.items()
            if session.last_active < cutoff
        ]

        for key in expired_keys:
            del self._sessions[key]

        if expired_keys:
            self._save()
            print(f"[session_store] 清理了 {len(expired_keys)} 个过期会话")
