#!/bin/bash
# 运行 STG5S 净值计算器

cd "$(dirname "$0")/.."
echo "启动 STG5S (5倍做空) 净值计算器..."
python run_net_value.py --strategy stg5s
