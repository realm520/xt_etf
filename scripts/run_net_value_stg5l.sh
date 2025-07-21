#!/bin/bash
# 运行 STG5L 净值计算器

cd "$(dirname "$0")/.."
echo "启动 STG5L (5倍做多) 净值计算器..."
python run_net_value.py --strategy stg5l
