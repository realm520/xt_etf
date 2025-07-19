#!/bin/bash
# 启动 STG5L 策略
# 使用新的策略模式，行为与原 run_etf_stg5l.py 完全一致

cd "$(dirname "$0")/.."
python run_etf.py --strategy stg5l "$@"