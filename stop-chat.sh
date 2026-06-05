#!/bin/bash
# Claude Code 聊天机器人 - 停止脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/chat.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "聊天机器人未运行"
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    echo "✅ 聊天机器人已停止 (PID: $PID)"
else
    rm -f "$PID_FILE"
    echo "聊天机器人进程已不存在"
fi
