#!/bin/bash
# 统一的开发环境启动脚本
# 用于同时启动净值计算服务和主交易策略
#
# 使用方法:
#   ./scripts/dev_start.sh stg3l  # 启动3倍做多策略
#   ./scripts/dev_start.sh stg3s  # 启动3倍做空策略
#   ./scripts/dev_start.sh stg5l  # 启动5倍做多策略
#   ./scripts/dev_start.sh stg5s  # 启动5倍做空策略

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 获取脚本所在目录的父目录（项目根目录）
cd "$(dirname "$0")/.."

# 检查参数
STRATEGY=$1
if [ -z "$STRATEGY" ]; then
    echo -e "${RED}错误: 请指定策略名称${NC}"
    echo "使用方法: $0 [stg3l|stg3s|stg5l|stg5s]"
    exit 1
fi

# 验证策略名称
case "$STRATEGY" in
    stg3l|stg3s|stg5l|stg5s)
        ;;
    *)
        echo -e "${RED}错误: 不支持的策略: $STRATEGY${NC}"
        echo "支持的策略: stg3l, stg3s, stg5l, stg5s"
        exit 1
        ;;
esac

echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')] 启动 $STRATEGY 策略开发环境${NC}"

# 检查虚拟环境
if [ -z "${VIRTUAL_ENV}" ]; then
    if [ -f ".venv/bin/activate" ]; then
        echo -e "${YELLOW}激活虚拟环境...${NC}"
        source .venv/bin/activate
    else
        echo -e "${RED}错误: 未找到虚拟环境，请先运行 ./scripts/setup_uv.sh${NC}"
        exit 1
    fi
fi

# 检查Redis
echo -e "${GREEN}检查Redis服务...${NC}"
if ! redis-cli ping &> /dev/null; then
    echo -e "${RED}错误: Redis服务未运行${NC}"
    echo "请启动Redis服务: redis-server"
    exit 1
fi

# 创建日志目录
mkdir -p logs

# 启动净值计算服务（后台）
echo -e "${GREEN}启动净值计算服务...${NC}"
python run_net_value.py --strategy $STRATEGY > logs/net_value_${STRATEGY}.log 2>&1 &
NETVALUE_PID=$!
echo -e "${GREEN}净值计算服务已启动 (PID: $NETVALUE_PID)${NC}"

# 等待净值初始化
echo -e "${YELLOW}等待净值初始化...${NC}"
sleep 3

# 清理函数
cleanup() {
    echo -e "\n${YELLOW}收到退出信号，停止服务...${NC}"
    if [ ! -z "$NETVALUE_PID" ]; then
        kill $NETVALUE_PID 2>/dev/null || true
        echo -e "${GREEN}净值计算服务已停止${NC}"
    fi
    exit 0
}

# 设置信号处理
trap cleanup SIGINT SIGTERM

# 启动主策略（前台）
echo -e "${GREEN}启动交易主程序...${NC}"
echo -e "${YELLOW}提示: 按 Ctrl+C 停止所有服务${NC}\n"
python run_etf.py --strategy $STRATEGY

# 清理
cleanup
