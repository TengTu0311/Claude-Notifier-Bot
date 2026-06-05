#!/bin/bash
# Claude Code 通知监控 - 停止脚本

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/monitor.pid"

if [ ! -f "$PID_FILE" ]; then
    echo "监控未运行"
    exit 0
fi

PID=$(cat "$PID_FILE")

if kill -0 "$PID" 2>/dev/null; then
    # 杀掉整个进程组
    kill -- -"$PID" 2>/dev/null || kill "$PID" 2>/dev/null
    rm -f "$PID_FILE"
    echo "✅ 监控已停止 (PID: $PID)"
else
    rm -f "$PID_FILE"
    echo "监控进程已不存在"
fi
