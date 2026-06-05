"""飞书通知模块

使用飞书开放平台 API 发送通知。
支持两种方式：
1. Webhook（简单，只能发群消息）
2. 应用 API（功能更强，可发私聊）
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from typing import Optional

import requests


@dataclass
class FeishuConfig:
    """飞书配置"""
    # Webhook 方式
    webhook_url: Optional[str] = None
    
    # 应用 API 方式
    app_id: Optional[str] = None
    app_secret: Optional[str] = None
    
    # 通知目标
    chat_id: Optional[str] = None  # 群聊 ID
    user_id: Optional[str] = None  # 用户 ID（用于私聊）


class FeishuNotifier:
    """飞书通知器"""
    
    def __init__(self, config: FeishuConfig):
        self.config = config
        self._access_token: Optional[str] = None
        self._token_expire_at: float = 0
    
    def send_text(self, text: str) -> bool:
        """发送文本消息
        
        Args:
            text: 消息内容
            
        Returns:
            是否发送成功
        """
        # 优先使用 Webhook
        if self.config.webhook_url:
            return self._send_webhook(text)
        
        # 使用应用 API
        if self.config.app_id and self.config.app_secret:
            return self._send_app_message(text)
        
        print("错误: 未配置飞书 Webhook 或应用凭证")
        return False
    
    def send_card(self, title: str, content: str, color: str = "blue") -> bool:
        """发送卡片消息
        
        Args:
            title: 卡片标题
            content: 卡片内容
            color: 标题颜色（blue, green, red, yellow）
            
        Returns:
            是否发送成功
        """
        # 构建卡片消息
        card = {
            "header": {
                "title": {
                    "tag": "plain_text",
                    "content": title
                },
                "template": color
            },
            "elements": [
                {
                    "tag": "markdown",
                    "content": content
                }
            ]
        }
        
        # 优先使用 Webhook
        if self.config.webhook_url:
            return self._send_webhook_card(card)
        
        # 使用应用 API
        if self.config.app_id and self.config.app_secret:
            return self._send_app_card(card)
        
        return False
    
    def _send_webhook(self, text: str) -> bool:
        """通过 Webhook 发送文本消息"""
        payload = {
            "msg_type": "text",
            "content": {
                "text": text
            }
        }
        
        try:
            resp = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )
            result = resp.json()
            return result.get("code") == 0 or result.get("StatusCode") == 0
        except Exception as e:
            print(f"Webhook 发送失败: {e}")
            return False
    
    def _send_webhook_card(self, card: dict) -> bool:
        """通过 Webhook 发送卡片消息"""
        payload = {
            "msg_type": "interactive",
            "card": card
        }
        
        try:
            resp = requests.post(
                self.config.webhook_url,
                json=payload,
                timeout=10,
            )
            result = resp.json()
            return result.get("code") == 0 or result.get("StatusCode") == 0
        except Exception as e:
            print(f"Webhook 发送失败: {e}")
            return False
    
    def _get_access_token(self) -> Optional[str]:
        """获取访问令牌"""
        # 检查缓存是否有效
        if self._access_token and time.time() < self._token_expire_at:
            return self._access_token
        
        url = "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal"
        payload = {
            "app_id": self.config.app_id,
            "app_secret": self.config.app_secret,
        }
        
        try:
            resp = requests.post(url, json=payload, timeout=10)
            result = resp.json()
            
            if result.get("code") == 0:
                self._access_token = result.get("tenant_access_token")
                expire = result.get("expire", 7200)
                self._token_expire_at = time.time() + expire - 300  # 提前 5 分钟刷新
                return self._access_token
            else:
                print(f"获取 token 失败: {result}")
                return None
        except Exception as e:
            print(f"获取 token 异常: {e}")
            return None
    
    def _send_app_message(self, text: str) -> bool:
        """通过应用 API 发送消息"""
        token = self._get_access_token()
        if not token:
            return False
        
        # 确定接收者
        receive_id = self.config.chat_id or self.config.user_id
        if not receive_id:
            print("错误: 未配置 chat_id 或 user_id")
            return False
        
        # 确定消息类型
        id_type = "chat_id" if self.config.chat_id else "open_id"
        
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={id_type}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "text",
            "content": json.dumps({"text": text}),
        }
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            result = resp.json()
            return result.get("code") == 0
        except Exception as e:
            print(f"发送消息失败: {e}")
            return False
    
    def _send_app_card(self, card: dict) -> bool:
        """通过应用 API 发送卡片消息"""
        token = self._get_access_token()
        if not token:
            return False
        
        receive_id = self.config.chat_id or self.config.user_id
        if not receive_id:
            return False
        
        id_type = "chat_id" if self.config.chat_id else "open_id"
        
        url = f"https://open.feishu.cn/open-apis/im/v1/messages?receive_id_type={id_type}"
        headers = {
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
        }
        payload = {
            "receive_id": receive_id,
            "msg_type": "interactive",
            "content": json.dumps(card),
        }
        
        try:
            resp = requests.post(url, headers=headers, json=payload, timeout=10)
            result = resp.json()
            return result.get("code") == 0
        except Exception as e:
            print(f"发送卡片失败: {e}")
            return False
