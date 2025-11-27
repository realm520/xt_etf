#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
测试ETF净值推送API

使用方法:
    # 从.env文件读取
    python tests/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0234

    # 指定环境
    python tests/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0 --env prod
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


def load_api_key() -> dict:
    """
    从 .env 或环境变量加载 API 密钥
    """
    # 显式从当前工作目录或项目根目录加载 .env 文件
    env_paths = [
        Path.cwd() / ".env",
        project_root / ".env",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path)
            print(f"✅ 从 {env_path} 加载环境变量")
            break
    else:
        load_dotenv()  # 默认查找
    
    access_key = os.getenv("access_key")
    secret_key = os.getenv("secret_key")

    if access_key and secret_key:
        return {"access_key": access_key, "secret_key": secret_key}
    
    print("❌ 未找到 API 密钥配置")
    print("请配置：")
    print("  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx")
    print("  2. 或设置环境变量: export access_key=xxx && export secret_key=xxx")
    sys.exit(1)


def main():
    parser = argparse.ArgumentParser(description="测试ETF净值推送API")
    parser.add_argument(
        "--symbol", type=str, required=True, help="ETF交易对符号，如 TON3L_USDT"
    )
    parser.add_argument("--net-worth", type=float, required=True, help="净值（必须>0）")
    parser.add_argument(
        "--env", type=str, choices=["qa", "uat", "prod"], default="qa", help="环境（qa/uat/prod）"
    )

    args = parser.parse_args()

    # 加载API密钥
    api_key = load_api_key()

    # 确定API主机
    if args.env == "qa":
        host = "https://sapi.xt-qa2.com"
    elif args.env == "uat":
        host = "https://sapi.xt-uat.com"
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
        print("📤 正在推送净值到交易所...")
        result = client.update_etf_net_worth(
            symbol=args.symbol, net_worth=args.net_worth
        )

        print("✅ 推送成功!")
        print("响应结果:")
        print(json.dumps(result, indent=2, ensure_ascii=False))

    except Exception as e:
        print(f"\n❌ 推送失败")
        print(f"错误类型: {type(e).__name__}")
        print(f"错误信息: {str(e)}")

        # 如果是HTTP错误，给出可能的原因
        if "502" in str(e):
            print("\n💡 502错误可能的原因:")
            print("  1. 接口路径可能不对（当前: /v4/etf/net-worth）")
            print("  2. QA环境该接口可能未部署")
            print("  3. 需要联系XT确认接口地址和权限")
            print("\n建议:")
            print("  - 联系XT技术支持确认接口路径")
            print("  - 尝试生产环境: --env prod")
            print("  - 检查API密钥是否有ETF净值更新权限")
        elif "401" in str(e) or "403" in str(e):
            print("\n💡 认证/权限错误可能的原因:")
            print("  1. API密钥无效或过期")
            print("  2. 缺少ETF净值更新权限")
            print("  3. 签名计算错误")
        elif "404" in str(e):
            print("\n💡 404错误说明接口路径不存在")
            print("  当前路径: /v4/etf/net-worth")
            print("  请联系XT确认正确的接口路径")

        sys.exit(1)


if __name__ == "__main__":
    main()
