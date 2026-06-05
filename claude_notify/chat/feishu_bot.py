"""飞书 WebSocket 监听模块

通过 lark-oapi SDK 的 WebSocket 长连接接收用户消息，
调用 Claude CLI 处理后返回结果。
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
from .session_store import SessionStore
from .claude_runner import run_claude


def log(msg: str) -> None:
    """输出日志（立即刷新）"""
    print(msg)
    sys.stdout.flush()


class FeishuChatBot:
    """飞书聊天机器人"""

    def __init__(self, app_id: str, app_secret: str, allowed_user_id: Optional[str] = None):
        """
        Args:
            app_id: 飞书应用 App ID
            app_secret: 飞书应用 App Secret
            allowed_user_id: 允许的用户 ID（为空则允许所有用户）
        """
        self.app_id = app_id
        self.app_secret = app_secret
        self.allowed_user_id = allowed_user_id

        self.feishu = FeishuClient(app_id, app_secret)
        self.store = SessionStore()

        # 独立的 asyncio 事件循环
        self._bot_loop: asyncio.AbstractEventLoop = asyncio.new_event_loop()
        threading.Thread(target=self._start_bot_loop, daemon=True, name="bot-loop").start()

        # 活跃运行状态
        self._active_runs: dict[str, bool] = {}  # user_id -> is_running

    def _start_bot_loop(self):
        asyncio.set_event_loop(self._bot_loop)
        self._bot_loop.run_forever()

    def start(self):
        """启动机器人（阻塞）"""
        log("[bot] 启动飞书聊天机器人...")
        log(f"[bot] App ID: {self.app_id[:10]}...")
        if self.allowed_user_id:
            log(f"[bot] 允许的用户: {self.allowed_user_id[:10]}...")

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

        # 处理命令
        if text.startswith("/"):
            await self._handle_command(user_id, msg.message_id, text)
            return

        # 处理普通消息 → 调用 Claude
        await self._handle_claude_message(user_id, msg.message_id, text)

    async def _handle_command(self, user_id: str, message_id: str, text: str):
        """处理斜杠命令"""
        cmd = text.lower().strip()

        if cmd == "/new":
            self.store.clear_session(user_id, user_id)
            await self.feishu.reply_text(message_id, "✅ 已开始新会话")

        elif cmd == "/status":
            session = self.store.get_current(user_id, user_id)
            status = (
                f"**当前会话状态**\n"
                f"- Session ID: `{session.session_id or '无'}`\n"
                f"- 模型: `{session.model}`\n"
                f"- 工作目录: `{session.cwd or '默认'}`\n"
                f"- 权限模式: `{session.permission_mode}`"
            )
            await self.feishu.reply_card(message_id, status)

        elif cmd == "/help":
            help_text = (
                "**可用命令**\n\n"
                "`/new` - 开始新会话\n"
                "`/status` - 查看当前会话状态\n"
                "`/help` - 显示帮助信息\n\n"
                "直接发送消息即可与 Claude 对话"
            )
            await self.feishu.reply_card(message_id, help_text)

        else:
            await self.feishu.reply_text(message_id, f"未知命令: {text}\n输入 `/help` 查看帮助")

    async def _handle_claude_message(self, user_id: str, message_id: str, text: str):
        """处理普通消息，调用 Claude CLI"""
        # 检查是否已有活跃任务
        if self._active_runs.get(user_id):
            await self.feishu.reply_text(message_id, "⏳ 上一个任务还在运行中，请稍候...")
            return

        # 获取会话
        session = self.store.get_current(user_id, user_id)

        # 发送占位卡片
        try:
            card_msg_id = await self.feishu.reply_card(message_id, loading=True)
        except Exception as e:
            log(f"[error] 发送占位卡片失败: {e}")
            return

        # 标记为活跃
        self._active_runs[user_id] = True

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
            log(f"[claude] 开始调用: user={user_id[:8]}...")

            full_text, new_session_id, _ = await run_claude(
                message=text,
                session_id=session.session_id,
                model=session.model,
                cwd=session.cwd or None,
                permission_mode=session.permission_mode,
                on_text_chunk=on_text_chunk,
                on_tool_use=on_tool_use,
            )

            log(f"[claude] 完成: session={new_session_id}")

            # 更新会话信息
            if new_session_id:
                self.store.update_session(user_id, user_id, session_id=new_session_id)

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
            self._active_runs[user_id] = False

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
