#!/bin/bash
# 直邮管家启动脚本
# 用法: ./zygj.sh [start|stop|restart|status]

NAME="zygj"
DIR="$(cd "$(dirname "$0")" && pwd)"
PIDFILE="/tmp/${NAME}.pid"
LOGFILE="${DIR}/${NAME}.log"

# 加载环境变量（从 .env 文件或环境变量）
if [ -f "${DIR}/.env" ]; then
    set -a
    source "${DIR}/.env"
    set +a
fi

# 检查必要变量
if [ -z "$JST_APP_KEY" ] || [ -z "$JST_APP_SECRET" ] || [ -z "$JST_TOKEN" ]; then
    echo "ERROR: 请设置 JST_APP_KEY / JST_APP_SECRET / JST_TOKEN"
    echo "   可复制 .env.example 为 .env 并填入实际值"
    exit 1
fi

export JST_APP_KEY JST_APP_SECRET JST_TOKEN

start() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$NAME already running (PID: $pid)"
            return
        fi
        rm -f "$PIDFILE"
    fi
    
    echo "Starting $NAME..."
    cd "$DIR"
    nohup python3 app.py >> "$LOGFILE" 2>&1 &
    echo $! > "$PIDFILE"
    sleep 2
    
    if kill -0 $(cat "$PIDFILE") 2>/dev/null; then
        echo "$NAME started (PID: $(cat "$PIDFILE"))"
    else
        echo "Failed to start $NAME"
        rm -f "$PIDFILE"
        exit 1
    fi
}

stop() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "Stopping $NAME (PID: $pid)..."
            kill "$pid"
            sleep 2
            # force kill if still running
            if kill -0 "$pid" 2>/dev/null; then
                kill -9 "$pid"
            fi
        fi
        rm -f "$PIDFILE"
        echo "$NAME stopped"
    else
        echo "$NAME not running"
    fi
}

status() {
    if [ -f "$PIDFILE" ]; then
        pid=$(cat "$PIDFILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "$NAME running (PID: $pid)"
            return 0
        else
            echo "$NAME not running (stale PID file)"
            rm -f "$PIDFILE"
            return 1
        fi
    else
        echo "$NAME not running"
        return 1
    fi
}

case "$1" in
    start)
        start
        ;;
    stop)
        stop
        ;;
    restart)
        stop
        start
        ;;
    status)
        status
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac