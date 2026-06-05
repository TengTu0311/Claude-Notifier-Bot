#!/bin/bash
# Claude Code 通知监控 - 后台运行脚本
# 使用方法: ./run.sh

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
LOG_FILE="$SCRIPT_DIR/monitor.log"
PID_FILE="$SCRIPT_DIR/monitor.pid"

# 检查是否已在运行
if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "监控已在运行 (PID: $PID)"
        echo "查看日志: tail -f $LOG_FILE"
        echo "停止运行: ./stop.sh"
        exit 0
    fi
fi

echo "启动 Claude Code 通知监控..."

# 后台运行，自动重启
nohup bash -c '
    while true; do
        echo "[$(date)] 监控启动" >> '"$LOG_FILE"'
        cd '"$SCRIPT_DIR"' && python3 -m claude_notify.cli >> '"$LOG_FILE"' 2>&1
        echo "[$(date)] 监控退出，5秒后重启..." >> '"$LOG_FILE"'
        sleep 5
    done
' > /dev/null 2>&1 &

echo $! > "$PID_FILE"
echo "✅ 监控已启动 (PID: $!)"
echo "📋 查看日志: tail -f $LOG_FILE"
echo "🛑 停止运行: ./stop.sh"
