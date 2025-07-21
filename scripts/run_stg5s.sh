#!/bin/bash
# 启动 STG5S 策略
# 使用新的策略模式，行为与原 run_etf_stg5s.py 完全一致

cd "$(dirname "$0")/.."

# 如果存在 uv 管理的虚拟环境，则激活它
if [ -f ".venv/bin/activate" ]; then
    source .venv/bin/activate
fi

python run_etf.py --strategy stg5s "$@"
