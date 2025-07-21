#!/bin/bash

# ETF 5倍做多策略完整启动脚本
# 包含依赖检查、服务启动和监控

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m' # No Color

# 日志函数
log() {
    echo -e "${GREEN}[$(date '+%Y-%m-%d %H:%M:%S')]${NC} $1"
}

error() {
    echo -e "${RED}[$(date '+%Y-%m-%d %H:%M:%S')] ERROR:${NC} $1" >&2
}

warning() {
    echo -e "${YELLOW}[$(date '+%Y-%m-%d %H:%M:%S')] WARNING:${NC} $1"
}

# 检查Python环境
check_python() {
    log "检查Python环境..."
    if ! command -v python &> /dev/null; then
        error "Python未安装或未激活虚拟环境"
        exit 1
    fi

    PYTHON_VERSION=$(python -c 'import sys; print(".".join(map(str, sys.version_info[:2])))')
    log "Python版本: $PYTHON_VERSION"

    # 检查虚拟环境
    if [[ -z "${VIRTUAL_ENV}" ]]; then
        warning "未激活虚拟环境，尝试激活..."
        if [ -f .venv/bin/activate ]; then
            source .venv/bin/activate
            log "虚拟环境已激活"
        else
            error "找不到虚拟环境，请先运行 ./scripts/setup_uv.sh"
            exit 1
        fi
    fi
}

# 检查Redis服务
check_redis() {
    log "检查Redis服务..."
    if ! redis-cli ping &> /dev/null; then
        error "Redis服务未运行"
        warning "尝试启动Redis..."
        if command -v redis-server &> /dev/null; then
            redis-server --daemonize yes
            sleep 2
            if redis-cli ping &> /dev/null; then
                log "Redis服务已启动"
            else
                error "无法启动Redis服务"
                exit 1
            fi
        else
            error "Redis未安装，请先安装Redis"
            exit 1
        fi
    else
        log "Redis服务运行正常"
    fi
}

# 检查必要的文件
check_files() {
    log "检查必要文件..."

    # 检查配置文件
    if [ ! -f "config/strategies.yaml" ]; then
        error "策略配置文件不存在: config/strategies.yaml"
        exit 1
    fi

    # 检查API密钥文件
    if [ ! -f "APIKey.json" ] && [ ! -f "APIKey_qa.json" ]; then
        error "API密钥文件不存在"
        exit 1
    fi

    log "文件检查通过"
}

# 创建日志目录
setup_logs() {
    log "设置日志目录..."
    mkdir -p logs/pm2
    mkdir -p logs/etf
    log "日志目录已创建"
}

# 启动净值计算服务
start_net_value() {
    log "启动净值计算服务..."

    # 检查是否已经在运行
    if pgrep -f "run_net_value.py" > /dev/null; then
        warning "净值计算服务已在运行"
    else
        python run_net_value.py --strategy stg5l > logs/etf/net_value_stg5l.log 2>&1 &
        NET_VALUE_PID=$!
        sleep 2
        if kill -0 $NET_VALUE_PID 2>/dev/null; then
            log "净值计算服务已启动 (PID: $NET_VALUE_PID)"
        else
            error "净值计算服务启动失败"
            exit 1
        fi
    fi
}

# 启动主策略
start_strategy() {
    log "启动5倍做多策略..."

    # 使用exec替换当前shell，让信号能正确传递
    exec python run_etf.py --strategy stg5l
}

# 清理函数
cleanup() {
    log "收到退出信号，清理中..."

    # 停止净值计算服务
    if [ ! -z "$NET_VALUE_PID" ]; then
        kill $NET_VALUE_PID 2>/dev/null || true
    fi

    # 给策略一些时间清理
    sleep 2

    log "清理完成"
    exit 0
}

# 设置信号处理
trap cleanup SIGINT SIGTERM

# 主流程
main() {
    log "========== ETF 5倍做多策略启动 =========="

    check_python
    check_redis
    check_files
    setup_logs
    start_net_value

    log "所有检查通过，启动主策略..."
    log "========================================="

    start_strategy
}

# 运行主流程
main
