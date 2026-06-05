"""飞书聊天机器人

支持通过飞书消息控制 Claude Code：
- /server: 选择服务器
- /session: 选择会话
- /new: 创建新会话
- /status: 查看当前状态
- 直接发消息: 与 Claude 对话
"""

from __future__ import annotations

import asyncio
import json
import sys
import threading
import time
from typing import Optional

import lark_oapi as lark
from lark_oapi.api.im.v1.model import P2ImMessageReceiveV1

from .feishu_client import FeishuClient
from .claude_runner import run_claude
from ..ssh.connection import ServerConfig, read_sessions, execute_command


def log(msg: str) -> None:
    """输出日志（立即刷新）"""
    print(msg)
    sys.stdout.flush()


class ChatState:
    """用户聊天状态"""

    def __init__(self):
        self.server: Optional[ServerConfig] = None
        self.session_id: Optional[str] = None
        self.is_running: bool = False
        self.last_active: float = time.time()


class FeishuChatBot:
    """飞书聊天机器人"""

    def __init__(
        self,
        app_id: str,
        app_secret: str,
        allowed_user_id: Optional[str] = None,
        servers: Optional[list[ServerConfig]] = None,
    ):
        self.app_id = app_id
        self.app_secret = app_secret
        self.allowed_user_id = allowed_user_id
        self.servers = servers or []

        self.feishu = FeishuClient(app_id, app_secret)

        # 用户状态: user_id -> ChatState
        self._user_states: dict[str, ChatState] = {}

        # 独立的 asyncio 事件循环
        self._bot_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        threading.Thread(target=self._start_bot_loop, daemon=True, name="bot-loop").start()

    def _start_bot_loop(self):
        asyncio.set_event_loop(self._bot_loop)
        self._bot_loop.run_forever()

    def _get_state(self, user_id: str) -> ChatState:
        """获取用户状态（不存在则创建）"""
        if user_id not in self._user_states:
            self._user_states[user_id] = ChatState()
        state = self._user_states[user_id]
        state.last_active = time.time()
        return state

    def start(self):
        """启动机器人（阻塞）"""
        log("[bot] 启动飞书聊天机器人...")
        log(f"[bot] App ID: {self.app_id[:10]}...")
        if self.allowed_user_id:
            log(f"[bot] 允许的用户: {self.allowed_user_id[:10]}...")
        log(f"[bot] 可用服务器: {len(self.servers)} 个")

        # 创建事件处理器
        handler = lark.EventDispatcherHandler.builder("", "") \
            .register_p2_im_message_receive_v1(self._on_message_receive) \
            .build()

        # 创建 WebSocket 客户端
        ws_client = lark.ws.Client(
            self.app_id,
            self.app_secret,
            event_handler=handler,
            log_level=lark.LogLevel.INFO,
        )

        log("[bot] 连接飞书 WebSocket 长连接...")
        ws_client.start()  # 阻塞

    def _on_message_receive(self, data: P2ImMessageReceiveV1) -> None:
        """飞书消息接收回调（同步）→ 调度异步任务"""
        asyncio.run_coroutine_threadsafe(
            self._handle_message_async(data),
            self._bot_loop,
        )

    async def _handle_message_async(self, event: P2ImMessageReceiveV1):
        """异步处理飞书消息"""
        msg = event.event.message
        sender = event.event.sender
        user_id = sender.sender_id.open_id

        log(f"[bot] 收到消息: user={user_id[:8]}... type={msg.message_type}")

        # 权限检查
        if self.allowed_user_id and user_id != self.allowed_user_id:
            log(f"[bot] 忽略未授权用户: {user_id[:8]}...")
            return

        # 只处理文本消息
        if msg.message_type != "text":
            return

        # 提取文本内容
        try:
            text = json.loads(msg.content).get("text", "").strip()
        except Exception:
            return

        if not text:
            return

        log(f"[bot] 文本: {text[:50]}...")

        # 处理命令
        if text.startswith("/"):
            await self._handle_command(user_id, msg.message_id, text)
            return

        # 处理普通消息 → 调用 Claude
        await self._handle_claude_message(user_id, msg.message_id, text)

    async def _handle_command(self, user_id: str, message_id: str, text: str):
        """处理斜杠命令"""
        parts = text.strip().split(maxsplit=1)
        cmd = parts[0].lower()
        args = parts[1] if len(parts) > 1 else ""

        if cmd == "/server":
            await self._cmd_server(user_id, message_id, args)
        elif cmd == "/session":
            await self._cmd_session(user_id, message_id, args)
        elif cmd == "/new":
            await self._cmd_new(user_id, message_id)
        elif cmd == "/status":
            await self._cmd_status(user_id, message_id)
        elif cmd == "/help":
            await self._cmd_help(message_id)
        else:
            await self.feishu.reply_text(message_id, f"未知命令: {cmd}\n输入 `/help` 查看帮助")

    async def _cmd_server(self, user_id: str, message_id: str, args: str):
        """处理 /server 命令"""
        state = self._get_state(user_id)

        # 如果有参数，尝试切换服务器
        if args:
            server = self._find_server(args)
            if server:
                state.server = server
                state.session_id = None  # 切换服务器时清除 session
                await self.feishu.reply_text(
                    message_id,
                    f"✅ 已切换到服务器 **{server.name}**\n"
                    f"地址: `{server.ssh_host or '本地'}`\n\n"
                    f"使用 `/session` 查看可用会话"
                )
            else:
                await self.feishu.reply_text(message_id, f"❌ 未找到服务器: {args}")
            return

        # 列出所有服务器
        if not self.servers:
            await self.feishu.reply_text(message_id, "❌ 没有配置服务器")
            return

        lines = ["📋 **可用服务器：**\n"]
        for i, server in enumerate(self.servers, 1):
            current = " ← 当前" if state.server and state.server.name == server.name else ""
            addr = server.ssh_host or "本地"
            lines.append(f"{i}. **{server.name}** (`{addr}`){current}")

        lines.append("\n请输入服务器名称或编号切换")

        await self.feishu.reply_card(message_id, "\n".join(lines))

    async def _cmd_session(self, user_id: str, message_id: str, args: str):
        """处理 /session 命令"""
        state = self._get_state(user_id)

        # 检查是否已选择服务器
        if not state.server:
            await self.feishu.reply_text(message_id, "❌ 请先选择服务器: `/server`")
            return

        # 如果有参数，尝试切换 session
        if args:
            session_id = self._find_session(state.server, args)
            if session_id:
                state.session_id = session_id
                await self.feishu.reply_text(
                    message_id,
                    f"✅ 已绑定到 session `{session_id[:12]}...`\n"
                    f"现在可以直接发消息了"
                )
            else:
                await self.feishu.reply_text(message_id, f"❌ 未找到 session: {args}")
            return

        # 列出所有 session
        sessions = read_sessions(state.server)
        if not sessions:
            await self.feishu.reply_text(message_id, f"❌ 服务器 {state.server.name} 上没有活跃会话")
            return

        lines = [f"📋 **{state.server.name} 上的会话：**\n"]
        for i, session in enumerate(sessions, 1):
            current = " ← 当前" if state.session_id == session.session_id else ""
            status_icon = "🟢" if session.is_active else "⚪"
            cwd_short = session.cwd.split("/")[-1] if session.cwd else "未知"
            lines.append(f"{i}. {status_icon} `{session.session_id[:12]}...` ({cwd_short}){current}")

        lines.append("\n请输入 session ID 或编号切换")

        await self.feishu.reply_card(message_id, "\n".join(lines))

    async def _cmd_new(self, user_id: str, message_id: str):
        """处理 /new 命令"""
        state = self._get_state(user_id)
        state.session_id = None
        await self.feishu.reply_text(message_id, "✅ 已清除 session，下次消息将创建新会话")

    async def _cmd_status(self, user_id: str, message_id: str):
        """处理 /status 命令"""
        state = self._get_state(user_id)

        server_name = state.server.name if state.server else "未选择"
        server_addr = state.server.ssh_host or "本地" if state.server else "-"
        session_id = state.session_id or "未绑定（将创建新会话）"
        is_running = "是" if state.is_running else "否"

        status = (
            f"**当前状态**\n\n"
            f"- 服务器: **{server_name}** (`{server_addr}`)\n"
            f"- Session: `{session_id}`\n"
            f"- 运行中: {is_running}"
        )

        await self.feishu.reply_card(message_id, status)

    async def _cmd_help(self, message_id: str):
        """处理 /help 命令"""
        help_text = (
            "**可用命令**\n\n"
            "`/server` - 列出所有服务器\n"
            "`/server ZJUtt` - 切换到指定服务器\n"
            "`/session` - 列出当前服务器的会话\n"
            "`/session 32bdda90` - 切换到指定会话\n"
            "`/new` - 创建新会话\n"
            "`/status` - 查看当前状态\n"
            "`/help` - 显示帮助\n\n"
            "**使用流程**\n"
            "1. `/server` 选择服务器\n"
            "2. `/session` 选择会话（或 `/new` 创建新会话）\n"
            "3. 直接发消息与 Claude 对话"
        )
        await self.feishu.reply_card(message_id, help_text)

    def _find_server(self, name: str) -> Optional[ServerConfig]:
        """根据名称或编号查找服务器"""
        # 尝试按编号
        try:
            index = int(name) - 1
            if 0 <= index < len(self.servers):
                return self.servers[index]
        except ValueError:
            pass

        # 尝试按名称
        name_lower = name.lower()
        for server in self.servers:
            if server.name.lower() == name_lower:
                return server

        return None

    def _find_session(self, server: ServerConfig, session_id: str) -> Optional[str]:
        """根据 ID 或编号查找 session"""
        sessions = read_sessions(server)
        if not sessions:
            return None

        # 尝试按编号
        try:
            index = int(session_id) - 1
            if 0 <= index < len(sessions):
                return sessions[index].session_id
        except ValueError:
            pass

        # 尝试按 ID 前缀匹配
        session_id_lower = session_id.lower()
        for session in sessions:
            if session.session_id.lower().startswith(session_id_lower):
                return session.session_id

        return None

    async def _handle_claude_message(self, user_id: str, message_id: str, text: str):
        """处理普通消息，调用 Claude CLI"""
        state = self._get_state(user_id)

        # 检查是否已选择服务器
        if not state.server:
            await self.feishu.reply_text(message_id, "❌ 请先选择服务器: `/server`")
            return

        # 检查是否已有活跃任务
        if state.is_running:
            await self.feishu.reply_text(message_id, "⏳ 上一个任务还在运行中，请稍候...")
            return

        # 发送占位卡片
        try:
            card_msg_id = await self.feishu.reply_card(message_id, loading=True)
        except Exception as e:
            log(f"[error] 发送占位卡片失败: {e}")
            return

        # 标记为活跃
        state.is_running = True

        # 流式输出相关变量
        accumulated = ""
        tool_history = []
        last_push_time = 0.0
        PUSH_INTERVAL = 2.0

        async def push(content: str):
            """更新卡片内容"""
            try:
                await self.feishu.update_card(card_msg_id, content)
            except Exception as e:
                log(f"[warn] push 失败: {e}")

        def build_display() -> str:
            """构建显示内容"""
            parts = []
            if tool_history:
                parts.append("\n".join(tool_history[-5:]))
            if accumulated:
                if parts:
                    parts.append("")
                d = accumulated
                if len(d) > 2500:
                    d = "...\n\n" + d[-2500:]
                parts.append(d)
            return "\n".join(parts) if parts else "⏳ 思考中..."

        async def on_text_chunk(chunk: str):
            """文本增量回调"""
            nonlocal accumulated, last_push_time
            accumulated += chunk
            now = time.time()
            if now - last_push_time >= PUSH_INTERVAL:
                await push(build_display())
                last_push_time = now

        async def on_tool_use(name: str, inp: dict):
            """工具调用回调"""
            nonlocal last_push_time
            tool_line = self._format_tool(name, inp)
            if tool_history:
                tool_history[-1] = tool_line
            else:
                tool_history.append(tool_line)
            await push(build_display())
            last_push_time = time.time()

        try:
            server = state.server
            log(f"[claude] 开始调用: server={server.name} session={state.session_id}")

            # 判断是本地还是远程
            if server.is_local:
                # 本地调用
                full_text, new_session_id, _ = await run_claude(
                    message=text,
                    session_id=state.session_id,
                    on_text_chunk=on_text_chunk,
                    on_tool_use=on_tool_use,
                )
            else:
                # 远程调用（通过 SSH）
                full_text, new_session_id = await self._run_claude_remote(
                    server=server,
                    message=text,
                    session_id=state.session_id,
                    on_text_chunk=on_text_chunk,
                    on_tool_use=on_tool_use,
                )

            log(f"[claude] 完成: session={new_session_id}")

            # 更新 session
            if new_session_id:
                state.session_id = new_session_id

            # 最终更新卡片
            final = full_text or accumulated or "（无输出）"
            await self.feishu.update_card(card_msg_id, final)

            # 发送完成标记
            await self.feishu.reply_text(message_id, "✅")

        except Exception as e:
            log(f"[error] Claude 执行失败: {type(e).__name__}: {e}")
            try:
                await self.feishu.update_card(card_msg_id, f"❌ 执行出错：{type(e).__name__}: {e}")
            except Exception:
                pass

        finally:
            state.is_running = False

    async def _run_claude_remote(
        self,
        server: ServerConfig,
        message: str,
        session_id: Optional[str] = None,
        on_text_chunk=None,
        on_tool_use=None,
    ) -> tuple[str, Optional[str]]:
        """通过 SSH 远程调用 Claude CLI"""
        import shlex

        # 构建命令
        cmd_parts = [
            "claude",
            "--print",
            "--output-format", "stream-json",
            "--verbose",
            "--include-partial-messages",
            "--dangerously-skip-permissions",
        ]

        if session_id:
            cmd_parts.extend(["--resume", session_id])

        # 转义消息内容
        escaped_message = shlex.quote(message)

        # 构建完整命令（echo 管道到 claude）
        full_cmd = f"echo {escaped_message} | {' '.join(cmd_parts)}"

        # 通过 SSH 执行
        ok, output = execute_command(server, full_cmd, timeout=300)

        if not ok:
            raise RuntimeError(f"SSH 执行失败: {output}")

        # 解析输出
        full_text = ""
        new_session_id = None

        for line in output.strip().split("\n"):
            line = line.strip()
            if not line:
                continue

            try:
                data = json.loads(line)
            except json.JSONDecodeError:
                continue

            event_type = data.get("type")

            if event_type == "system":
                sid = data.get("session_id")
                if sid:
                    new_session_id = sid

            elif event_type == "result":
                sid = data.get("session_id")
                if sid:
                    new_session_id = sid
                result = data.get("result", "")
                if isinstance(result, str):
                    full_text = result
                elif isinstance(result, list):
                    parts = []
                    for item in result:
                        if isinstance(item, dict) and item.get("type") == "text":
                            parts.append(item.get("text", ""))
                    full_text = "".join(parts)

        return full_text, new_session_id

    def _format_tool(self, name: str, inp: dict) -> str:
        """格式化工具调用的进度提示"""
        n = name.lower()
        if n == "bash":
            cmd = inp.get("command", "")
            if len(cmd) > 80:
                cmd = cmd[:77] + "..."
            return f"🔧 **执行命令：** `{cmd}`" if cmd else "🔧 **执行命令...**"
        elif n in ("read_file", "read"):
            return f"📄 **读取：** `{inp.get('file_path', inp.get('path', ''))}`"
        elif n in ("write_file", "write"):
            return f"✏️ **写入：** `{inp.get('file_path', inp.get('path', ''))}`"
        elif n in ("edit_file", "edit"):
            return f"✂️ **编辑：** `{inp.get('file_path', inp.get('path', ''))}`"
        elif n in ("glob",):
            return f"🔍 **搜索文件：** `{inp.get('pattern', '')}`"
        elif n in ("grep",):
            return f"🔎 **搜索内容：** `{inp.get('pattern', '')}`"
        elif n == "task":
            return f"🤖 **子任务：** {inp.get('description', inp.get('prompt', '')[:40])}"
        elif n == "webfetch":
            return "🌐 **抓取网页...**"
        elif n == "websearch":
            return f"🔍 **搜索：** {inp.get('query', '')}"
        else:
            return f"⚙️ **{name}**"
