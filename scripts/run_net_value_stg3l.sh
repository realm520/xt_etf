#!/bin/bash
# 运行 STG3L 净值计算器

cd "$(dirname "$0")/.."
echo "启动 STG3L (3倍做多) 净值计算器..."
python run_net_value.py --strategy stg3l
