"""SSH 连接管理

复用 claude-monitor 的 SSH 连接逻辑。
"""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from typing import Optional


@dataclass
class ServerConfig:
    """服务器配置"""
    name: str
    ssh_host: str  # SSH Host 别名（使用 ~/.ssh/config 中的配置）


@dataclass
class ClaudeSession:
    """Claude Code 会话信息"""
    pid: int
    session_id: str
    cwd: str
    started_at: int  # 毫秒时间戳
    version: str
    status: str  # busy, idle
    updated_at: Optional[int] = None
    server_name: Optional[str] = None
    
    @property
    def is_active(self) -> bool:
        """是否正在运行任务"""
        return self.status == "busy"


def execute_ssh(server: ServerConfig, command: str, timeout: int = 30) -> tuple[bool, str]:
    """在远程服务器执行命令
    
    Args:
        server: 服务器配置
        command: 要执行的命令
        timeout: 超时时间（秒）
        
    Returns:
        (成功与否, 输出内容或错误信息)
    """
    args = [
        "ssh",
        "-o", "StrictHostKeyChecking=no",
        "-o", "ConnectTimeout=15",
        "-o", "ServerAliveInterval=10",
        "-o", "ServerAliveCountMax=3",
        server.ssh_host,
        command,
    ]
    
    try:
        result = subprocess.run(
            args,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        
        if result.returncode == 0:
            return True, result.stdout
        else:
            return False, result.stderr or f"退出码: {result.returncode}"
            
    except subprocess.TimeoutExpired:
        return False, "命令执行超时"
    except Exception as e:
        return False, str(e)


def read_sessions(server: ServerConfig) -> list[ClaudeSession] | None:
    """读取服务器上的 Claude Code 会话
    
    Args:
        server: 服务器配置
        
    Returns:
        ClaudeSession 列表，SSH 连接失败返回 None
    """
    import json
    
    ok, output = execute_ssh(server, "cat ~/.claude/sessions/*.json 2>/dev/null", timeout=10)
    
    if not ok:
        return None  # SSH 连接失败
    
    sessions = []
    for line in output.strip().split("\n"):
        line = line.strip()
        if not line:
            continue
        
        try:
            data = json.loads(line)
            
            # 必需字段
            pid = data.get("pid")
            session_id = data.get("sessionId")
            cwd = data.get("cwd")
            started_at = data.get("startedAt")
            
            if not all([pid, session_id, cwd, started_at]):
                continue
            
            session = ClaudeSession(
                pid=pid,
                session_id=session_id,
                cwd=cwd,
                started_at=started_at,
                version=data.get("version", "unknown"),
                status=data.get("status", "unknown"),
                updated_at=data.get("updatedAt"),
                server_name=server.name,
            )
            sessions.append(session)
            
        except json.JSONDecodeError:
            continue
    
    return sessions


def read_history(server: ServerConfig, session_id: str, lines: int = 5) -> str:
    """读取会话的最近历史记录
    
    Args:
        server: 服务器配置
        session_id: 会话 ID
        lines: 读取行数
        
    Returns:
        最近的用户消息
    """
    ok, output = execute_ssh(
        server,
        f"tail -{lines} ~/.claude/history.jsonl 2>/dev/null",
        timeout=10,
    )
    
    if not ok:
        return ""
    
    import json
    messages = []
    for line in output.strip().split("\n"):
        try:
            data = json.loads(line)
            if "display" in data:
                messages.append(data["display"])
        except:
            continue
    
    return "\n".join(messages)
