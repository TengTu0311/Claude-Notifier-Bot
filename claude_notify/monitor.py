"""主监控逻辑

监控 Claude Code 会话状态，发送飞书通知。
"""

from __future__ import annotations

import sys
import time
from dataclasses import dataclass, field
from typing import Optional

from .config import MonitorConfig
from .ssh.connection import ServerConfig, ClaudeSession, read_sessions
from .parser.task_extractor import extract_task_info
from .notify.feishu import FeishuNotifier


def log(msg: str) -> None:
    """输出日志（立即刷新）"""
    print(msg)
    sys.stdout.flush()


@dataclass
class SessionNotifyState:
    """会话通知状态"""
    session_id: str
    server_name: str
    last_status: str = "unknown"  # 上次状态
    last_user_message: str = ""  # 上次通知时的用户消息
    start_notified: bool = False  # 是否已发送任务开始通知
    complete_notified: bool = False  # 是否已发送任务完成通知
    long_running_notified: bool = False  # 是否已发送长时间运行通知
    last_active_time: float = 0  # 上次活跃时间


class ClaudeMonitor:
    """Claude Code 监控器"""
    
    def __init__(self, config: MonitorConfig):
        self.config = config
        self.notifier = FeishuNotifier(config.feishu)
        # key: "server_name:session_id"
        self.notify_state: dict[str, SessionNotifyState] = {}
        self.running = False
    
    def run(self) -> None:
        """运行监控"""
        self.running = True
        
        log("[monitor] 启动 Claude Code 通知监控")
        log(f"[monitor] 监控服务器: {len(self.config.servers)} 个")
        for s in self.config.servers:
            log(f"  - {s.name} ({s.ssh_host})")
        log(f"[monitor] 轮询间隔: {self.config.poll_interval} 秒")
        log("")
        
        # 发送启动通知
        self._send_startup_notification()
        
        while self.running:
            try:
                self._poll_all_servers()
            except Exception as e:
                log(f"[monitor] 轮询错误: {e}")
            
            time.sleep(self.config.poll_interval)
    
    def stop(self) -> None:
        """停止监控"""
        self.running = False
    
    def _poll_all_servers(self) -> None:
        """轮询所有服务器"""
        for server in self.config.servers:
            try:
                sessions = read_sessions(server)
                if sessions is not None:
                    self._process_sessions(server, sessions)
                else:
                    log(f"[monitor] {server.name}: SSH 连接失败，跳过本轮")
            except Exception as e:
                log(f"[monitor] 处理 {server.name} 错误: {e}")
    
    def _process_sessions(self, server: ServerConfig, sessions: list[ClaudeSession]) -> None:
        """处理服务器上的会话"""
        for session in sessions:
            key = f"{server.name}:{session.session_id}"
            state = self.notify_state.get(key)
            
            # 获取当前用户消息
            current_message = self._get_current_user_message(server, session)
            
            if state is None:
                # 首次发现这个会话
                self.notify_state[key] = SessionNotifyState(
                    session_id=session.session_id,
                    server_name=server.name,
                    last_status=session.status,
                    last_user_message=current_message,
                    last_active_time=time.time(),
                )
                
                # 如果是 busy 状态，发送任务开始通知
                if session.is_active:
                    log(f"[monitor] {server.name}: 发现活跃会话 {session.session_id[:8]}...")
                    self._notify_task_start(server, session, current_message)
                    self.notify_state[key].start_notified = True
                else:
                    log(f"[monitor] {server.name}: 发现空闲会话 {session.session_id[:8]}...")
                continue
            
            # 已知会话，检查状态变化
            old_status = state.last_status
            new_status = session.status
            
            # 状态变化：idle -> busy
            if old_status == "idle" and new_status == "busy":
                log(f"[monitor] {server.name}: 会话 {session.session_id[:8]}... 开始新任务")
                self._notify_task_start(server, session, current_message)
                state.start_notified = True
                state.complete_notified = False
                state.long_running_notified = False
                state.last_user_message = current_message
                state.last_active_time = time.time()
            
            # 状态变化：busy -> idle
            elif old_status == "busy" and new_status == "idle":
                if not state.complete_notified:
                    log(f"[monitor] {server.name}: 会话 {session.session_id[:8]}... 任务完成")
                    self._notify_task_complete(server, session)
                    state.complete_notified = True
                    state.start_notified = False
            
            # 状态不变：仍然是 busy，检查是否有新任务
            elif old_status == "busy" and new_status == "busy":
                # 用户消息变了，说明是新任务
                if current_message and current_message != state.last_user_message:
                    log(f"[monitor] {server.name}: 会话 {session.session_id[:8]}... 新任务（消息变化）")
                    self._notify_task_start(server, session, current_message)
                    state.start_notified = True
                    state.complete_notified = False
                    state.long_running_notified = False
                    state.last_user_message = current_message
                    state.last_active_time = time.time()
                
                # 检查长时间运行
                if self.config.notify.on_long_running and not state.long_running_notified:
                    runtime_minutes = (time.time() - state.last_active_time) / 60
                    if runtime_minutes >= self.config.notify.long_running_threshold_minutes:
                        log(f"[monitor] {server.name}: 会话 {session.session_id[:8]}... 长时间运行 ({int(runtime_minutes)} 分钟)")
                        self._notify_long_running(server, session, int(runtime_minutes))
                        state.long_running_notified = True
            
            # 更新状态
            state.last_status = new_status
    
    def _get_current_user_message(self, server: ServerConfig, session: ClaudeSession) -> str:
        """获取当前用户消息"""
        try:
            task_info = extract_task_info(server, session.session_id, session.cwd)
            return task_info.last_user_message
        except Exception:
            return ""
    
    def _notify_task_start(self, server: ServerConfig, session: ClaudeSession, user_message: str) -> None:
        """通知任务开始"""
        log(f"[monitor] 发送任务开始通知: {server.name}")
        
        content = f"**服务器:** {server.name}\n"
        if user_message:
            msg = user_message[:200]
            if len(user_message) > 200:
                msg += "..."
            content += f"**用户消息:** {msg}\n"
        content += f"**项目目录:** ...{session.cwd[-40:]}"
        
        self.notifier.send_card(
            title="🔄 Claude Code 开始新任务",
            content=content,
            color="blue",
        )
    
    def _notify_task_complete(self, server: ServerConfig, session: ClaudeSession) -> None:
        """通知任务完成"""
        log(f"[monitor] 发送任务完成通知: {server.name}")
        
        # 获取任务信息
        task_info = extract_task_info(server, session.session_id, session.cwd)
        
        content = f"**服务器:** {server.name}\n"
        content += f"**项目目录:** ...{session.cwd[-40:]}\n"
        
        if task_info.last_assistant_message:
            msg = task_info.last_assistant_message[:300]
            if len(task_info.last_assistant_message) > 300:
                msg += "..."
            content += f"\n**Claude 回复:**\n{msg}"
        
        if task_info.background_tasks:
            completed = [t for t in task_info.background_tasks if t.status == "completed"]
            if completed:
                content += f"\n\n**完成的后台任务:** {len(completed)} 个"
        
        self.notifier.send_card(
            title="✅ Claude Code 任务完成",
            content=content,
            color="green",
        )
    
    def _notify_long_running(self, server: ServerConfig, session: ClaudeSession, runtime_minutes: int) -> None:
        """通知长时间运行"""
        log(f"[monitor] 发送长时间运行通知: {server.name}")
        
        content = (
            f"**服务器:** {server.name}\n"
            f"**运行时长:** {runtime_minutes} 分钟\n"
            f"**项目目录:** ...{session.cwd[-40:]}"
        )
        
        self.notifier.send_card(
            title="⏱️ Claude Code 长时间运行",
            content=content,
            color="yellow",
        )
    
    def _send_startup_notification(self) -> None:
        """发送启动通知"""
        server_names = ", ".join(s.name for s in self.config.servers)
        content = (
            f"**监控服务器:** {server_names}\n"
            f"**轮询间隔:** {self.config.poll_interval} 秒"
        )
        
        self.notifier.send_card(
            title="🟢 Claude Code 监控已启动",
            content=content,
            color="green",
        )
