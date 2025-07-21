#!/bin/bash
# 使用新的策略模式启动 ETF 交易系统

# 检查参数
if [ $# -eq 0 ]; then
    echo "Usage: $0 <strategy> [additional options]"
    echo "Available strategies: stg3l, stg3s, stg5l, stg5s"
    exit 1
fi

STRATEGY=$1
shift  # 移除第一个参数，剩下的传递给 python

# 使用 PM2 启动策略
pm2 start run_etf.py --interpreter python3 \
    --name "etf_${STRATEGY}" \
    -- --strategy ${STRATEGY} "$@"

# 示例用法：
# ./run_strategy.sh stg3l
# ./run_strategy.sh stg5s --env qa
# ./run_strategy.sh stg3l --bid-ask-spread 0.02
