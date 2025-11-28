#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
统一的净值计算程序
支持通过命令行参数选择不同的ETF策略
使用改进版净值计算器，支持断线恢复和异常保护

使用方法:
    # 正常运行净值计算
    python run_net_value.py --strategy stg3l  # STG 3倍做多
    python run_net_value.py --strategy stg3s  # STG 3倍做空
    python run_net_value.py --strategy stg5l  # STG 5倍做多
    python run_net_value.py --strategy stg5s  # STG 5倍做空
    python run_net_value.py --strategy ton3l --env qa  # TON 3倍做多
    
    # 查看当前净值
    python run_net_value.py --strategy stg3l --show-netvalue
    
    # 修改净值（合并/拆分）
    python run_net_value.py --strategy stg3l --set-netvalue 1.0
    
合并/拆分操作流程:
    1. pm2 stop net-value-stg3l          # 停止净值计算器
    2. python run_net_value.py --strategy stg3l --set-netvalue 1.0  # 设置新净值
    3. pm2 start net-value-stg3l         # 重启净值计算器
"""

import argparse
import json
import logging
import os
import sys
import time
import yaml
from typing import Dict, Any

import redis

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


def set_netvalue_in_redis(strategy_name: str, new_netvalue: float) -> bool:
    """
    直接修改 Redis 中的净值（用于合并/拆分操作）
    
    Args:
        strategy_name: 策略名称 (如 stg3l, ton3s)
        new_netvalue: 新的净值
        
    Returns:
        bool: 是否成功
    """
    # 解析策略参数
    leverage = int(strategy_name[3])
    direction = "l" if strategy_name[4] == "l" else "s"
    
    if strategy_name.startswith("ton"):
        symbol_prefix = "ton"
    else:
        symbol_prefix = "stg"
    
    # Redis keys
    redis_key = f"netvalue_{symbol_prefix}{leverage}{direction}"
    redis_detail_key = f"{redis_key}_detail"
    
    try:
        r = redis.Redis(host="localhost", port=6379, db=0)
        
        # 读取当前值（用于日志）
        old_value = r.get(redis_key)
        old_netvalue = float(old_value.decode()) if old_value else None
        
        # 读取详细数据
        detail_data = r.get(redis_detail_key)
        if detail_data:
            data = json.loads(detail_data)
        else:
            data = {
                "net_value": new_netvalue,
                "last_price": None,
                "last_update_ts": time.time(),
                "create_ts": time.time(),
                "update_count": 0,
                "total_fee_deducted": 0.0,
                "abnormal_events": [],
            }
        
        # 记录合并/拆分事件
        split_merge_event = {
            "type": "manual_adjustment",
            "old_net_value": old_netvalue,
            "new_net_value": new_netvalue,
            "timestamp": time.time(),
            "reason": "手动设置净值（合并/拆分）",
        }
        
        # 更新数据
        data["net_value"] = new_netvalue
        data["last_price"] = None  # 重置价格，让下次启动重新初始化
        data["last_update_ts"] = time.time()
        data["abnormal_events"].append(split_merge_event)
        
        # 写入 Redis
        r.set(redis_key, str(new_netvalue))
        r.set(redis_detail_key, json.dumps(data))
        
        logging.info("=" * 60)
        logging.info("✅ 净值修改成功")
        logging.info(f"   策略: {strategy_name}")
        logging.info(f"   Redis Key: {redis_key}")
        logging.info(f"   旧净值: {old_netvalue}")
        logging.info(f"   新净值: {new_netvalue}")
        if old_netvalue:
            ratio = new_netvalue / old_netvalue
            if ratio > 1:
                logging.info(f"   操作类型: 合并 (比例 {1/ratio:.2f}:1)")
            else:
                logging.info(f"   操作类型: 拆分 (比例 1:{1/ratio:.2f})")
        logging.info("=" * 60)
        logging.info("⚠️  请重启净值计算器以使用新净值")
        
        return True
        
    except Exception as e:
        logging.error(f"❌ 修改净值失败: {e}")
        return False


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
    
    # 净值修改参数（用于合并/拆分）
    parser.add_argument(
        "--set-netvalue",
        type=float,
        help="直接设置Redis中的净值（用于合并/拆分），设置后退出程序",
    )
    parser.add_argument(
        "--show-netvalue",
        action="store_true",
        help="显示当前Redis中的净值，然后退出",
    )

    args = parser.parse_args()
    
    # 处理 --show-netvalue：显示当前净值
    if args.show_netvalue:
        strategy_params = get_strategy_params(args.strategy)
        leverage = int(args.strategy[3])
        direction = "l" if args.strategy[4] == "l" else "s"
        symbol_prefix = "ton" if args.strategy.startswith("ton") else "stg"
        
        redis_key = f"netvalue_{symbol_prefix}{leverage}{direction}"
        redis_detail_key = f"{redis_key}_detail"
        
        try:
            r = redis.Redis(host="localhost", port=6379, db=0)
            
            # 读取简单净值
            simple_value = r.get(redis_key)
            netvalue = float(simple_value.decode()) if simple_value else None
            
            # 读取详细数据
            detail_data = r.get(redis_detail_key)
            
            logging.info("=" * 60)
            logging.info(f"📊 当前净值信息 - 策略: {args.strategy}")
            logging.info(f"   Redis Key: {redis_key}")
            logging.info(f"   净值: {netvalue}")
            
            if detail_data:
                data = json.loads(detail_data)
                logging.info(f"   上次更新: {time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(data.get('last_update_ts', 0)))}")
                logging.info(f"   更新次数: {data.get('update_count', 0)}")
                logging.info(f"   累计扣费: {data.get('total_fee_deducted', 0):.6f}")
            logging.info("=" * 60)
        except Exception as e:
            logging.error(f"❌ 读取净值失败: {e}")
        sys.exit(0)
    
    # 处理 --set-netvalue：设置净值并退出
    if args.set_netvalue is not None:
        success = set_netvalue_in_redis(args.strategy, args.set_netvalue)
        sys.exit(0 if success else 1)

    # 加载策略配置（合并全局默认 + 策略特定配置）
    strategy_config = load_strategy_config(args.strategy)
    
    # 加载全局配置用于数据库等设置
    full_config = load_config()

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

    # 加载API密钥用于净值推送（从 .env 或环境变量）
    from dotenv import load_dotenv
    # 显式从当前工作目录加载 .env 文件
    env_path = os.path.join(os.getcwd(), ".env")
    if os.path.exists(env_path):
        load_dotenv(dotenv_path=env_path)
        logging.info(f"✅ 从 {env_path} 加载环境变量")
    else:
        load_dotenv()  # 降级到默认行为
    
    access_key = os.getenv("access_key")
    secret_key = os.getenv("secret_key")
    
    if not access_key or not secret_key:
        logging.error("❌ 未找到有效的API密钥，净值推送无法启用")
        logging.error("请配置API密钥:")
        logging.error("  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx")
        logging.error("  2. 或设置环境变量: export access_key=xxx && export secret_key=xxx")
        raise ValueError("API密钥配置缺失，无法启动净值推送")
    
    logging.info("✅ 从环境变量加载API密钥")
    
    # 根据环境选择主机地址
    if args.env == "qa":
        push_host = "https://sapi.xt-qa2.com"
    elif args.env == "uat":
        push_host = "https://sapi.xt-uat.com"
    else:
        push_host = "https://sapi.xt.com"
    
    net_value_params.update({
        "push_host": push_host,
        "push_access_key": access_key,
        "push_secret_key": secret_key,
    })
    logging.info(f"✅ 净值推送已启用 - 主机: {push_host}")

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
