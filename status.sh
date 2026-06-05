#!/bin/bash
# Claude Code 通知监控 - 查看状态

SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
PID_FILE="$SCRIPT_DIR/monitor.pid"
LOG_FILE="$SCRIPT_DIR/monitor.log"

echo "=== Claude Code 通知监控状态 ==="
echo ""

if [ -f "$PID_FILE" ]; then
    PID=$(cat "$PID_FILE")
    if kill -0 "$PID" 2>/dev/null; then
        echo "状态: ✅ 运行中 (PID: $PID)"
    else
        echo "状态: ❌ 进程不存在"
    fi
else
    echo "状态: ⚪ 未启动"
fi

echo ""
echo "最近日志:"
if [ -f "$LOG_FILE" ]; then
    tail -5 "$LOG_FILE"
else
    echo "  无日志"
fi

echo ""
echo "常用命令:"
echo "  启动: ./run.sh"
echo "  停止: ./stop.sh"
echo "  日志: tail -f $LOG_FILE"
