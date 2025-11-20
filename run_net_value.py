#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一的净值计算程序
支持通过命令行参数选择不同的ETF策略
使用改进版净值计算器，支持断线恢复和异常保护

使用方法:
    python run_net_value.py --strategy stg3l  # STG 3倍做多
    python run_net_value.py --strategy stg3s  # STG 3倍做空
    python run_net_value.py --strategy stg5l  # STG 5倍做多
    python run_net_value.py --strategy stg5s  # STG 5倍做空
    python run_net_value.py --strategy ton3l --env qa  # TON 3倍做多
"""

import argparse
import json
import logging
import os
import sys
import yaml
from typing import Dict, Any

from etf.net_value_improved import ImprovedNetValue

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def load_config(config_file: str = "config/strategies.yaml") -> Dict[str, Any]:
    """加载完整配置文件（包括策略和全局配置）"""
    if not os.path.exists(config_file):
        logging.error(f"配置文件 {config_file} 不存在")
        sys.exit(1)

    with open(config_file, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    return config


def load_strategy_config(
    strategy_name: str, config_file: str = "config/strategies.yaml"
) -> Dict[str, Any]:
    """加载策略配置文件"""
    config = load_config(config_file)

    if "strategies" not in config or strategy_name not in config["strategies"]:
        logging.error(f"策略 {strategy_name} 在配置文件中不存在")
        sys.exit(1)

    return config["strategies"][strategy_name]


def get_strategy_params(strategy_name: str) -> Dict[str, Any]:
    """根据策略名称获取净值计算参数"""
    # 支持的策略列表
    supported_strategies = ["stg3l", "stg3s", "stg5l", "stg5s", "ton3l"]

    if strategy_name not in supported_strategies:
        raise ValueError(f"不支持的策略: {strategy_name}，支持的策略: {supported_strategies}")

    # 提取杠杆倍数和方向
    leverage = int(strategy_name[3])  # 3 或 5
    is_long = strategy_name[4] == "l"  # True 或 False

    # 根据策略名称确定交易对
    if strategy_name.startswith("ton"):
        symbol = "ton_usdt"
    else:
        symbol = "stg_usdt"

    return {
        "m_lever": leverage,
        "long": is_long,
        "symbol": symbol,
    }


def main():
    """主函数"""
    parser = argparse.ArgumentParser(description="统一的ETF净值计算程序")

    # 必需参数
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=["stg3l", "stg3s", "stg5l", "stg5s", "ton3l"],
        help="策略名称 (stg3l/stg3s/stg5l/stg5s/ton3l)",
    )

    # 环境参数（用于区分QA/生产环境，虽然净值计算器不直接使用，但保持接口一致性）
    parser.add_argument(
        "--env",
        type=str,
        choices=["qa", "prod"],
        default="prod",
        help="运行环境 (qa/prod)，默认: prod",
    )

    # 可选参数（可覆盖配置文件中的值）
    parser.add_argument("--symbol", type=str, help="交易对符号")
    parser.add_argument("--init-net-value", type=float, help="初始净值")
    parser.add_argument("--daily-fee", type=float, help="日管理费率")
    parser.add_argument("--time-gap-second", type=int, help="净值更新间隔（秒）")
    parser.add_argument("--rebalance", type=float, help="再平衡阈值")
    parser.add_argument("--max-single-change", type=float, help="最大单次变化率限制")
    parser.add_argument("--max-restart-gap", type=int, help="最大重启间隔（秒）")

    args = parser.parse_args()

    # 加载完整配置（包括数据库配置）
    full_config = load_config()
    strategy_config = full_config["strategies"][args.strategy]

    # 获取策略特定参数
    strategy_params = get_strategy_params(args.strategy)

    # 获取数据库持久化配置
    db_config = full_config.get("database", {}).get("net_value_persistence", {})
    enable_db_persistence = db_config.get("enabled", False)

    # 构建净值计算参数
    net_value_params = {
        "symbol": args.symbol or strategy_params["symbol"],
        "m_lever": strategy_params["m_lever"],
        "long": strategy_params["long"],
        "init_net_value": args.init_net_value
        or strategy_config.get("init_net_value", 1.0),
        "daily_fee": args.daily_fee or strategy_config.get("daily_fee", 0.001),
        "time_gap_second": args.time_gap_second
        or strategy_config.get("net_value_interval", 1),
        "rebalance": args.rebalance or strategy_config.get("rebalance_threshold", 0.05),
        "max_single_change": args.max_single_change
        or strategy_config.get("max_single_change", 0.10),
        "max_restart_gap": args.max_restart_gap
        or strategy_config.get("max_restart_gap", 300),
        # 数据库持久化参数
        "enable_db_persistence": enable_db_persistence,
        "strategy_name": args.strategy,
    }

    # 日志输出配置信息
    logging.info(f"启动净值计算器 - 策略: {args.strategy}")
    logging.info(
        f"参数配置: {json.dumps({k: v for k, v in net_value_params.items() if k != 'strategy_name'}, indent=2, ensure_ascii=False)}"
    )
    if enable_db_persistence:
        logging.info(f"✅ 数据库持久化已启用 - 批量大小: {db_config.get('batch_size', 40)}, 刷新间隔: {db_config.get('flush_interval', 10)}秒")
    else:
        logging.info("⚠️  数据库持久化已禁用 - 仅使用Redis存储")

    # 创建并运行改进版净值计算器
    try:
        net_value_calculator = ImprovedNetValue(**net_value_params)
        net_value_calculator.run()
    except KeyboardInterrupt:
        logging.info("净值计算器被用户中断")
    except Exception as e:
        logging.error(f"净值计算器运行出错: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
