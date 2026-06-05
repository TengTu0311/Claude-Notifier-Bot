"""任务信息提取器

从 Claude Code 会话日志中提取任务信息。
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Optional

from ..ssh.connection import ServerConfig, execute_command


@dataclass
class TaskInfo:
    """任务信息"""
    session_id: str
    project_dir: str  # 项目目录
    last_user_message: str  # 用户最后一条消息
    last_assistant_message: str  # Claude 最后一条回复
    recent_commands: list[str]  # 最近执行的命令
    background_tasks: list[BackgroundTask]  # 后台任务
    
    @property
    def summary(self) -> str:
        """生成摘要"""
        parts = []
        
        # 项目目录（简化显示）
        if self.project_dir:
            # 提取最后两级目录
            parts_dir = self.project_dir.rstrip("/").split("/")
            if len(parts_dir) >= 2:
                short_dir = "/".join(parts_dir[-2:])
            else:
                short_dir = self.project_dir
            parts.append(f"📁 {short_dir}")
        
        # 用户最后的消息
        if self.last_user_message:
            msg = self.last_user_message[:100]
            if len(self.last_user_message) > 100:
                msg += "..."
            parts.append(f"💬 {msg}")
        
        # Claude 的回复摘要
        if self.last_assistant_message:
            msg = self.last_assistant_message[:150]
            if len(self.last_assistant_message) > 150:
                msg += "..."
            parts.append(f"🤖 {msg}")
        
        # 后台任务
        if self.background_tasks:
            completed = sum(1 for t in self.background_tasks if t.status == "completed")
            running = sum(1 for t in self.background_tasks if t.status == "running")
            if completed > 0:
                parts.append(f"✅ 完成 {completed} 个后台任务")
            if running > 0:
                parts.append(f"⏳ {running} 个任务运行中")
        
        return "\n".join(parts) if parts else "无详细信息"


@dataclass
class BackgroundTask:
    """后台任务"""
    task_id: str
    command: str
    status: str  # running, completed, failed
    output_summary: Optional[str] = None


def extract_task_info(server: ServerConfig, session_id: str, project_dir: str) -> TaskInfo:
    """提取任务信息
    
    Args:
        server: 服务器配置
        session_id: 会话 ID
        project_dir: 项目目录（从 session 的 cwd 获取）
        
    Returns:
        TaskInfo 对象
    """
    # 构建会话日志路径
    # Claude Code 的日志在 ~/.claude/projects/<encoded-path>/<session-id>.jsonl
    # 编码规则：/ 替换为 -，. 替换为 -，开头加 -
    import re
    encoded_path = project_dir.replace("/", "-").replace(".", "-")
    if not encoded_path.startswith("-"):
        encoded_path = "-" + encoded_path
    # 合并连续的连字符
    encoded_path = re.sub(r'-+', '-', encoded_path)
    
    # 尝试查找实际目录（因为编码可能不完全一致）
    find_cmd = f"ls -d ~/.claude/projects/*{session_id[:8]}* 2>/dev/null | head -1"
    ok, found_path = execute_command(server, find_cmd, timeout=5)
    
    log_content = ""
    
    # 如果找到了精确目录，直接使用
    if ok and found_path.strip():
        log_dir = found_path.strip()
        ok2, output = execute_command(server, f"tail -30 {log_dir}/{session_id}.jsonl 2>/dev/null", timeout=10)
        if ok2 and output.strip():
            log_content = output
    
    # 如果没找到，尝试编码路径
    if not log_content:
        possible_paths = [
            f"~/.claude/projects/{encoded_path}/{session_id}.jsonl",
            f"~/.claude/projects/{encoded_path}*/{session_id}.jsonl",
        ]
        
        for path in possible_paths:
            ok, output = execute_command(server, f"tail -30 {path} 2>/dev/null", timeout=10)
            if ok and output.strip():
                log_content = output
                break
    
    # 如果还是没找到，用 find 命令搜索
    if not log_content:
        find_cmd = f"find ~/.claude/projects -name '{session_id}.jsonl' 2>/dev/null | head -1"
        ok, found_file = execute_command(server, find_cmd, timeout=10)
        if ok and found_file.strip():
            ok2, output = execute_command(server, f"tail -30 {found_file.strip()} 2>/dev/null", timeout=10)
            if ok2 and output.strip():
                log_content = output
    
    # 解析日志
    last_user_msg = ""
    last_assistant_msg = ""
    recent_commands = []
    background_tasks = []
    
    if log_content:
        for line in log_content.strip().split("\n"):
            try:
                entry = json.loads(line)
                entry_type = entry.get("type")
                
                # 用户消息
                if entry_type == "user":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") == "tool_result":
                                    # 工具结果，可能是后台任务通知
                                    task_content = str(item.get("content", ""))
                                    if "Background command" in task_content and "completed" in task_content:
                                        task = _parse_background_task(task_content, entry)
                                        if task:
                                            background_tasks.append(task)
                    elif isinstance(content, str) and content:
                        last_user_msg = content
                
                # Assistant 消息
                elif entry_type == "assistant":
                    msg = entry.get("message", {})
                    content = msg.get("content", [])
                    
                    if isinstance(content, list):
                        for item in content:
                            if isinstance(item, dict):
                                if item.get("type") == "text":
                                    text = item.get("text", "")
                                    if text:
                                        last_assistant_msg = text
                                elif item.get("type") == "tool_use":
                                    tool_name = item.get("name", "")
                                    tool_input = item.get("input", {})
                                    if tool_name == "Bash":
                                        cmd = tool_input.get("command", "")
                                        if cmd:
                                            recent_commands.append(cmd[:100])
                
                # 后台任务通知
                elif entry_type == "queue-operation" and entry.get("operation") == "enqueue":
                    content = entry.get("content", "")
                    if "<task-notification>" in content:
                        task = _parse_task_notification(content)
                        if task:
                            background_tasks.append(task)
                            
            except json.JSONDecodeError:
                continue
    
    # 也读取 history.jsonl 获取用户最后消息
    if not last_user_msg:
        ok, history = execute_command(server, "tail -3 ~/.claude/history.jsonl 2>/dev/null", timeout=5)
        if ok:
            for line in history.strip().split("\n"):
                try:
                    data = json.loads(line)
                    if "display" in data:
                        last_user_msg = data["display"]
                except:
                    continue
    
    return TaskInfo(
        session_id=session_id,
        project_dir=project_dir,
        last_user_message=last_user_msg,
        last_assistant_message=last_assistant_msg,
        recent_commands=recent_commands[-5:],
        background_tasks=background_tasks,
    )


def _parse_background_task(content: str, entry: dict) -> Optional[BackgroundTask]:
    """解析后台任务完成通知"""
    import re
    
    # 提取任务 ID
    task_id_match = re.search(r'<task-id>(.*?)</task-id>', content)
    command_match = re.search(r'Background command "(.*?)" completed', content)
    status_match = re.search(r'<status>(.*?)</status>', content)
    
    if not task_id_match:
        return None
    
    return BackgroundTask(
        task_id=task_id_match.group(1),
        command=command_match.group(1) if command_match else "unknown",
        status=status_match.group(1) if status_match else "unknown",
    )


def _parse_task_notification(content: str) -> Optional[BackgroundTask]:
    """解析任务通知"""
    import re
    
    task_id_match = re.search(r'<task-id>(.*?)</task-id>', content)
    status_match = re.search(r'<status>(.*?)</status>', content)
    summary_match = re.search(r'<summary>(.*?)</summary>', content)
    
    if not task_id_match:
        return None
    
    command = ""
    if summary_match:
        # 提取命令名
        cmd_match = re.search(r'Background command "(.*?)"', summary_match.group(1))
        if cmd_match:
            command = cmd_match.group(1)
    
    return BackgroundTask(
        task_id=task_id_match.group(1),
        command=command,
        status=status_match.group(1) if status_match else "unknown",
        output_summary=summary_match.group(1) if summary_match else None,
    )
