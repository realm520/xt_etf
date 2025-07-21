#!/bin/bash
# 完整启动 STG3L 策略（包括净值计算和交易主程序）
#
# 使用方法：
#   ./scripts/run_stg3l_complete.sh           # 启动所有组件
#   ./scripts/run_stg3l_complete.sh stop      # 停止所有组件
#   ./scripts/run_stg3l_complete.sh status    # 查看运行状态

cd "$(dirname "$0")/.."

# 定义 PID 文件路径
PID_DIR=".pids"
NET_VALUE_PID_FILE="$PID_DIR/net_value_stg3l.pid"
TRADING_PID_FILE="$PID_DIR/trading_stg3l.pid"

# 创建 PID 目录
mkdir -p "$PID_DIR"

# 激活虚拟环境
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

# 停止函数
stop_services() {
    echo "停止 STG3L 服务..."

    # 停止净值计算服务
    if [ -f "$NET_VALUE_PID_FILE" ]; then
        PID=$(cat "$NET_VALUE_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "停止净值计算服务 (PID: $PID)"
            kill "$PID"
            sleep 2
            # 如果还在运行，强制停止
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID"
            fi
        fi
        rm -f "$NET_VALUE_PID_FILE"
    fi

    # 停止交易主程序
    if [ -f "$TRADING_PID_FILE" ]; then
        PID=$(cat "$TRADING_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "停止交易主程序 (PID: $PID)"
            kill "$PID"
            sleep 2
            # 如果还在运行，强制停止
            if kill -0 "$PID" 2>/dev/null; then
                kill -9 "$PID"
            fi
        fi
        rm -f "$TRADING_PID_FILE"
    fi

    echo "STG3L 服务已停止"
}

# 状态检查函数
check_status() {
    echo "=== STG3L 服务状态 ==="

    # 检查净值计算服务
    if [ -f "$NET_VALUE_PID_FILE" ]; then
        PID=$(cat "$NET_VALUE_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "净值计算服务: 运行中 (PID: $PID)"
        else
            echo "净值计算服务: 已停止 (PID 文件存在但进程不存在)"
        fi
    else
        echo "净值计算服务: 未运行"
    fi

    # 检查交易主程序
    if [ -f "$TRADING_PID_FILE" ]; then
        PID=$(cat "$TRADING_PID_FILE")
        if kill -0 "$PID" 2>/dev/null; then
            echo "交易主程序: 运行中 (PID: $PID)"
        else
            echo "交易主程序: 已停止 (PID 文件存在但进程不存在)"
        fi
    else
        echo "交易主程序: 未运行"
    fi

    # 检查 Redis 中的净值
    NETVALUE=$(redis-cli get netvalue_stg3l 2>/dev/null)
    if [ -n "$NETVALUE" ]; then
        echo "Redis 净值: $NETVALUE"
    else
        echo "Redis 净值: 未设置"
    fi
}

# 根据参数执行相应操作
case "$1" in
    stop)
        stop_services
        exit 0
        ;;
    status)
        check_status
        exit 0
        ;;
    *)
        # 默认启动服务
        ;;
esac

# 停止已有服务
stop_services

echo "启动 STG3L 策略..."

# 启动净值计算服务（后台运行）
echo "启动净值计算服务..."
nohup python net_value_stg3l.py > logs/net_value_stg3l.log 2>&1 &
NET_VALUE_PID=$!
echo $NET_VALUE_PID > "$NET_VALUE_PID_FILE"
echo "净值计算服务已启动 (PID: $NET_VALUE_PID)"

# 等待净值初始化
echo "等待净值初始化..."
for i in {1..10}; do
    NETVALUE=$(redis-cli get netvalue_stg3l 2>/dev/null)
    if [ -n "$NETVALUE" ]; then
        echo "净值已初始化: $NETVALUE"
        break
    fi
    echo "等待中... ($i/10)"
    sleep 1
done

# 检查净值是否成功初始化
NETVALUE=$(redis-cli get netvalue_stg3l 2>/dev/null)
if [ -z "$NETVALUE" ]; then
    echo "警告：净值初始化超时，但仍继续启动交易主程序"
    echo "交易主程序将使用文件中的净值或默认值"
fi

# 启动交易主程序
echo "启动交易主程序..."
python run_etf.py --strategy stg3l "$@" &
TRADING_PID=$!
echo $TRADING_PID > "$TRADING_PID_FILE"
echo "交易主程序已启动 (PID: $TRADING_PID)"

# 监控进程
echo ""
echo "STG3L 策略已完整启动"
echo "净值计算服务 PID: $NET_VALUE_PID"
echo "交易主程序 PID: $TRADING_PID"
echo ""
echo "使用以下命令管理服务："
echo "  $0 status  # 查看状态"
echo "  $0 stop    # 停止服务"
echo ""
echo "日志文件："
echo "  净值计算: logs/net_value_stg3l.log"
echo "  交易主程序: 控制台输出"
echo ""
echo "按 Ctrl+C 停止交易主程序..."

# 等待交易主程序结束
wait $TRADING_PID

# 清理
echo ""
echo "交易主程序已结束，停止净值计算服务..."
stop_services
