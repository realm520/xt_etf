#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试ETF净值推送API

使用方法:
    # 从.env文件读取（默认）
    python scripts/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0234

    # 从策略配置文件读取
    python scripts/test_update_net_worth.py --symbol STG3L_USDT --net-worth 0.9876 --strategy stg3l

    # 指定环境
    python scripts/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0 --env prod
"""

import argparse
import json
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# 添加项目根目录到路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from etf.xt import Spot


def load_api_key_from_env() -> dict:
    """从.env文件加载API密钥"""
    env_file = project_root / ".env"
    if not env_file.exists():
        return None

    load_dotenv(env_file)
    access_key = os.getenv("access_key")
    secret_key = os.getenv("secret_key")

    if access_key and secret_key:
        return {"access_key": access_key, "secret_key": secret_key}
    return None


def load_api_key_from_strategy(strategy: str) -> dict:
    """从策略配置文件加载API密钥"""
    # 支持的策略文件
    key_files = [
        project_root / f"APIKey_{strategy}.json",  # APIKey_stg3l.json
        project_root / "APIKey.json",  # APIKey.json（多策略）
    ]

    for key_file in key_files:
        if not key_file.exists():
            continue

        with open(key_file, "r") as f:
            config = json.load(f)

        # 如果是单策略文件，直接返回
        if "access_key" in config and "secret_key" in config:
            return config

        # 如果是多策略文件，查找对应策略
        strategy_key = f"xt_{strategy}"
        if strategy_key in config:
            return config[strategy_key]

    return None


def load_api_key(strategy: str = None) -> dict:
    """
    加载API密钥（优先级）:
    1. 如果指定strategy，从APIKey_{strategy}.json加载
    2. 从.env文件加载
    3. 从APIKey.json加载
    """
    # 1. 尝试从策略文件加载
    if strategy:
        api_key = load_api_key_from_strategy(strategy)
        if api_key:
            print(f"✅ 从策略配置加载密钥: {strategy}")
            return api_key

    # 2. 尝试从.env加载
    api_key = load_api_key_from_env()
    if api_key:
        print(f"✅ 从.env文件加载密钥")
        return api_key

    # 3. 尝试从APIKey.json加载第一个策略
    key_file = project_root / "APIKey.json"
    if key_file.exists():
        with open(key_file, "r") as f:
            config = json.load(f)

        # 取第一个策略的密钥
        for strategy_name, creds in config.items():
            if isinstance(creds, dict) and "access_key" in creds:
                print(f"✅ 从APIKey.json加载密钥: {strategy_name}")
                return creds

    print(f"❌ 未找到API密钥配置")
    print(f"请检查以下文件之一:")
    print(f"  - .env")
    print(f"  - APIKey_{strategy}.json (如果指定了--strategy)")
    print(f"  - APIKey.json")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="测试ETF净值推送API")
    parser.add_argument(
        "--symbol", type=str, required=True, help="ETF交易对符号，如 TON3L_USDT"
    )
    parser.add_argument("--net-worth", type=float, required=True, help="净值（必须>0）")
    parser.add_argument(
        "--env", type=str, choices=["qa", "prod"], default="qa", help="环境（qa/prod）"
    )
    parser.add_argument(
        "--strategy",
        type=str,
        help="策略名称（如stg3l/ton3l），用于从APIKey_{strategy}.json加载密钥",
    )

    args = parser.parse_args()

    # 加载API密钥
    api_key = load_api_key(args.strategy)

    # 确定API主机
    if args.env == "qa":
        host = "https://sapi.xt-qa2.com"
    else:
        host = "https://sapi.xt.com"

    print(f"🔧 配置信息:")
    print(f"  环境: {args.env}")
    print(f"  主机: {host}")
    print(f"  交易对: {args.symbol}")
    print(f"  净值: {args.net_worth}")
    print()

    # 创建客户端
    client = Spot(
        host=host,
        access_key=api_key["access_key"],
        secret_key=api_key["secret_key"],
    )

    try:
        # 推送净值
        print(f"📤 正在推送净值到交易所...")
        result = client.update_etf_net_worth(
            symbol=args.symbol, net_worth=args.net_worth
        )

        print(f"✅ 推送成功!")
        print(f"响应结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n❌ 推送失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")

        # 如果是HTTP错误，给出可能的原因
        if "502" in str(e):
            print(f"\n💡 502错误可能的原因:")
            print(f"  1. 接口路径可能不对（当前: /v4/etf/net-worth）")
            print(f"  2. QA环境该接口可能未部署")
            print(f"  3. 需要联系XT确认接口地址和权限")
            print(f"\n建议:")
            print(f"  - 联系XT技术支持确认接口路径")
            print(f"  - 尝试生产环境: --env prod")
            print(f"  - 检查API密钥是否有ETF净值更新权限")
        elif "401" in str(e) or "403" in str(e):
            print(f"\n💡 认证/权限错误可能的原因:")
            print(f"  1. API密钥无效或过期")
            print(f"  2. 缺少ETF净值更新权限")
            print(f"  3. 签名计算错误")
        elif "404" in str(e):
            print(f"\n💡 404错误说明接口路径不存在")
            print(f"  当前路径: /v4/etf/net-worth")
            print(f"  请联系XT确认正确的接口路径")

        sys.exit(1)


if __name__ == "__main__":
    main()
