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


# 使用共享的配置加载模块
from etf.config.loader import (
    load_config,
    load_strategy_config,
    get_available_strategies,
)


def get_strategy_params(strategy_name: str) -> Dict[str, Any]:
    """根据策略名称获取净值计算参数"""
    # 从策略名称解析参数（约定：{symbol}{leverage}{direction}）
    # 例如: stg3l -> symbol=stg, leverage=3, direction=l
    #      ton3s -> symbol=ton, leverage=3, direction=s

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
    # 首先获取可用策略列表（用于 argparse choices）
    available_strategies = get_available_strategies()
    
    parser = argparse.ArgumentParser(description="统一的ETF净值计算程序")

    # 必需参数 - 动态从配置文件读取策略列表
    parser.add_argument(
        "--strategy",
        type=str,
        required=True,
        choices=available_strategies,
        help=f"策略名称 (可用策略: {', '.join(available_strategies)})",
    )

    # 环境参数（用于区分QA/生产环境，虽然净值计算器不直接使用，但保持接口一致性）
    parser.add_argument(
        "--env",
        type=str,
        choices=["qa", "uat", "prod"],
        default="prod",
        help="运行环境 (qa/uat/prod)，默认: prod",
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

    # 获取全局净值推送配置
    global_push_config = full_config.get("net_value_push", {})
    enable_push = global_push_config.get("enabled", False)

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

    # 添加推送参数（如果启用）
    if enable_push:
        # 尝试多种方式加载API密钥（优先级：.env > APIKey.json）
        api_key = None
        
        # 方式1: 从 .env 文件加载（推荐）
        from dotenv import load_dotenv
        load_dotenv()
        
        access_key_env = os.getenv("access_key")
        secret_key_env = os.getenv("secret_key")
        
        if access_key_env and secret_key_env:
            api_key = {
                "access_key": access_key_env,
                "secret_key": secret_key_env
            }
            logging.info("✅ 从 .env 文件加载API密钥")
        else:
            # 方式2: 从 APIKey.json 加载（降级方案）
            api_key_file = strategy_config.get("apikey", "APIKey.json")
            api_key_path = os.path.join(os.path.dirname(__file__), api_key_file)
            
            if os.path.exists(api_key_path):
                with open(api_key_path, "r") as f:
                    api_keys = json.load(f)
                
                # 查找策略对应的密钥
                strategy_key = f"xt_{args.strategy}"
                if strategy_key in api_keys:
                    api_key = api_keys[strategy_key]
                    logging.info(f"✅ 从 {api_key_file} 加载API密钥: {strategy_key}")
                elif "access_key" in api_keys:
                    # 单策略文件格式
                    api_key = api_keys
                    logging.info(f"✅ 从 {api_key_file} 加载API密钥（单策略格式）")
                else:
                    logging.warning(f"⚠️ 未找到策略 {args.strategy} 的API密钥")
            else:
                logging.warning(f"⚠️ API密钥文件不存在: {api_key_path}")
        
        # 根据是否成功加载密钥来决定是否启用推送
        if api_key and api_key.get("access_key") and api_key.get("secret_key"):
            # 从全局配置确定主机地址（根据环境自动选择）
            env_config = global_push_config.get("environments", {})
            if args.env == "qa":
                push_host = env_config.get("qa", {}).get("host", "https://sapi.xt-qa2.com")
            elif args.env == "uat":
                push_host = env_config.get("uat", {}).get("host", "https://sapi.xt-uat.com")
            else:
                push_host = env_config.get("prod", {}).get("host", "https://sapi.xt.com")
            
            # 从全局配置的symbol映射中查找，如果没有则自动生成
            symbol_mapping = global_push_config.get("symbol_mapping", {})
            push_symbol = symbol_mapping.get(args.strategy)  # 可能是None，会自动生成
            
            net_value_params.update({
                "enable_push_to_exchange": True,
                "push_interval": global_push_config.get("interval", 60),
                "push_host": push_host,
                "push_access_key": api_key.get("access_key"),
                "push_secret_key": api_key.get("secret_key"),
                "push_symbol": push_symbol,  # 如果配置了symbol则使用，否则自动生成
            })
            logging.info(f"✅ 净值推送已启用 - 主机: {push_host}, 推送间隔: {global_push_config.get('interval', 60)}秒")
        else:
            logging.warning("⚠️  净值推送配置已启用，但未找到有效的API密钥，推送将被禁用")
            logging.warning("请确保以下任一方式配置API密钥:")
            logging.warning("  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx")
            logging.warning("  2. 在 APIKey.json 文件中配置相应的密钥")
    else:
        net_value_params["enable_push_to_exchange"] = False

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
