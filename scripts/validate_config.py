#!/usr/bin/env python3
"""
验证新的策略配置与原始硬编码配置的一致性
"""

import yaml
import os
import sys

# 原始硬编码的配置值
original_configs = {
    "stg3l": {
        "prefix": "stg3l",
        "env": "prod",
        "clientOrderId": "1655",
        "apikey": "APIKey.json",
        "bnsymbol": "STGUSDT",
        "currencies": ["USDT", "STG5L", "STG5S", "STG3L", "STG3S"],
        "precision": 6,
        "prec_amount": 2,
        "Hedging_interval": 20,
        "washing_interval": 5,  # STG3L 特有
        "kline_continuity_interval": 60,
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": False,
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 0,
        "precision_price": 4,
        "Enable_hedging": False,
        "Exit_with_cancel_all_open_orders": False,
        "wash": "mid_price",
        "anti_pin_usdt": 300,
        "anti_pin_rate": 0.2,
        "Enable_market_making": True,
        "bid_ask_spread": 0.01,
        "sleep_interval": 5  # STG3L 特有
    },
    "stg3s": {
        "prefix": "stg3s",
        "env": "prod",
        "clientOrderId": "1655",
        "apikey": "APIKey.json",
        "bnsymbol": "STGUSDT",
        "currencies": ["USDT", "STG5L", "STG5S", "STG3L", "STG3S"],
        "precision": 6,
        "prec_amount": 2,
        "Hedging_interval": 20,
        "washing_interval": 1,
        "kline_continuity_interval": 60,
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": False,
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 0,
        "precision_price": 4,
        "Enable_hedging": False,
        "Exit_with_cancel_all_open_orders": False,
        "wash": "mid_price",
        "anti_pin_usdt": 300,
        "anti_pin_rate": 0.2,
        "Enable_market_making": True,
        "bid_ask_spread": 0.01,
        "sleep_interval": 1
    },
    "stg5l": {
        "prefix": "stg5l",
        "env": "prod",
        "clientOrderId": "1655",
        "apikey": "APIKey.json",
        "bnsymbol": "STGUSDT",
        "currencies": ["USDT", "STG5L", "STG5S", "STG3L", "STG3S"],
        "precision": 6,
        "prec_amount": 2,
        "Hedging_interval": 20,
        "washing_interval": 1,
        "kline_continuity_interval": 60,
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": True,  # STG5L 特有
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 0,
        "precision_price": 4,
        "Enable_hedging": False,
        "Exit_with_cancel_all_open_orders": False,
        "wash": "mid_price",
        "anti_pin_usdt": 300,
        "anti_pin_rate": 0.2,
        "Enable_market_making": True,
        "bid_ask_spread": 0.01,
        "sleep_interval": 1
    },
    "stg5s": {
        "prefix": "stg5s",
        "env": "prod",
        "clientOrderId": "1655",
        "apikey": "APIKey.json",
        "bnsymbol": "STGUSDT",
        "currencies": ["USDT", "STG5L", "STG5S", "STG3L", "STG3S"],
        "precision": 6,
        "prec_amount": 2,
        "Hedging_interval": 20,
        "washing_interval": 1,
        "kline_continuity_interval": 60,
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": False,
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 0,
        "precision_price": 4,
        "Enable_hedging": False,
        "Exit_with_cancel_all_open_orders": False,
        "wash": "mid_price",
        "anti_pin_usdt": 300,
        "anti_pin_rate": 0.2,
        "Enable_market_making": True,
        "bid_ask_spread": 0.05,  # STG5S 特有
        "sleep_interval": 1
    }
}

def validate_config():
    """验证配置文件与原始配置的一致性"""
    config_file = os.path.join(os.path.dirname(__file__), "../config/strategies.yaml")
    
    if not os.path.exists(config_file):
        print(f"❌ 配置文件不存在: {config_file}")
        return False
    
    with open(config_file, 'r', encoding='utf8') as f:
        config_data = yaml.safe_load(f)
    
    strategies = config_data.get('strategies', {})
    all_valid = True
    
    for strategy_name, original_config in original_configs.items():
        print(f"\n检查策略: {strategy_name}")
        
        if strategy_name not in strategies:
            print(f"❌ 策略 {strategy_name} 在配置文件中不存在")
            all_valid = False
            continue
        
        yaml_config = strategies[strategy_name]
        
        # 检查每个参数
        for key, expected_value in original_config.items():
            if key not in yaml_config:
                print(f"❌ 参数 {key} 在配置文件中缺失")
                all_valid = False
            elif yaml_config[key] != expected_value:
                print(f"❌ 参数 {key} 不匹配: 期望 {expected_value}, 实际 {yaml_config[key]}")
                all_valid = False
        
        # 检查是否有额外的参数
        for key in yaml_config:
            if key not in original_config:
                print(f"⚠️  配置文件中有额外参数: {key}")
        
        if all(yaml_config.get(k) == v for k, v in original_config.items()):
            print(f"✅ 策略 {strategy_name} 配置完全一致")
    
    return all_valid

def compare_runtime_config():
    """比较运行时生成的配置"""
    print("\n=== 运行时配置比较 ===")
    
    # 模拟 run_etf.py 的配置生成逻辑
    for strategy in ["stg3l", "stg3s", "stg5l", "stg5s"]:
        print(f"\n策略 {strategy}:")
        print(f"  原始文件: python run_etf_{strategy}.py")
        print(f"  新方式: python run_etf.py --strategy {strategy}")
        print(f"  脚本方式: ./scripts/run_{strategy}.sh")
    
    print("\n特殊行为提醒:")
    print("- STG3L: 主循环间隔 5秒，洗盘间隔 5秒")
    print("- STG5L: 启动时自动取消所有订单")
    print("- STG5S: 买卖价差 5%，订单取消逻辑略有不同")

if __name__ == "__main__":
    print("=== ETF 策略配置验证工具 ===")
    
    if validate_config():
        print("\n✅ 所有配置验证通过！")
        compare_runtime_config()
        sys.exit(0)
    else:
        print("\n❌ 配置验证失败，请检查并修正")
        sys.exit(1)