#!/bin/bash
# 运行 STG3S 净值计算器

cd "$(dirname "$0")/.."
echo "启动 STG3S (3倍做空) 净值计算器..."
python run_net_value.py --strategy stg3s
