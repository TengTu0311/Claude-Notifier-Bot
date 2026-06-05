#!/bin/bash
# Claude Code 聊天机器人 - 后台运行脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/chat.log"
PID_FILE="$SCRIPT_DIR/chat.pid"

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "聊天机器人已在运行 (PID: $PID)"
        echo "查看日志: tail -f $LOG_FILE"
        echo "停止运行: ./stop-chat.sh"
        exit 0
    fi
fi

echo "启动 Claude Code 聊天机器人..."

# 后台运行
nohup bash -c '
    while true; do
        echo "[$(date)] 聊天机器人启动" >> '"$LOG_FILE"'
        cd '"$SCRIPT_DIR"' && python3 -m claude_notify.cli chat >> '"$LOG_FILE"' 2>&1
        echo "[$(date)] 聊天机器人退出，5秒后重启..." >> '"$LOG_FILE"'
        sleep 5
    done
' > /dev/null 2>&1 &

echo $! > "$PID_FILE"
echo "✅ 聊天机器人已启动 (PID: $!)"
echo "📋 查看日志: tail -f $LOG_FILE"
echo "🛑 停止运行: ./stop-chat.sh"
