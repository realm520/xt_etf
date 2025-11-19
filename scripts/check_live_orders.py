#!/usr/bin/env python3
"""查询交易所实际的活跃订单数量"""

import sys
import os
from pathlib import Path

# 添加项目路径
sys.path.insert(0, str(Path(__file__).parent.parent))

import argparse
from collections import defaultdict
from etf.xt import Spot

def load_client(env='qa', symbol='ton3l_usdt'):
    """根据环境加载XT客户端"""

    if env == 'qa':
        # QA环境：从.env读取
        from dotenv import load_dotenv
        load_dotenv()

        access_key = os.getenv("access_key")
        secret_key = os.getenv("secret_key")

        if not access_key or not secret_key:
            print("❌ 错误: .env文件中未找到access_key或secret_key")
            print("请确保.env文件包含以下配置:")
            print("  access_key=your_access_key")
            print("  secret_key=your_secret_key")
            sys.exit(1)

        client = Spot(
            host="https://sapi.xt-qa2.com",
            access_key=access_key,
            secret_key=secret_key,
        )
        print(f"✅ QA环境客户端初始化成功")

    elif env == 'prod':
        # 生产环境：从APIKey.json读取
        from etf.utils.crypto import load_api_keys

        try:
            apikey_file = "APIKey.json"
            apikey = load_api_keys(apikey_file)

            # 从symbol提取prefix (例如 ton3l_usdt -> ton3l)
            prefix = symbol.split('_')[0]

            client = Spot(
                host="https://sapi.xt.com",
                access_key=apikey[f"xt_{prefix}"]["access_key"],
                secret_key=apikey[f"xt_{prefix}"]["secret_key"],
            )
            print(f"✅ 生产环境客户端初始化成功 (prefix: {prefix})")

        except Exception as e:
            print(f"❌ 加载API密钥失败: {e}")
            sys.exit(1)

    else:
        print(f"❌ 不支持的环境: {env}")
        sys.exit(1)

    return client

def analyze_orders(symbol='ton3l_usdt', env='qa'):
    """分析活跃订单"""

    print(f"\n{'='*80}")
    print(f"查询 {symbol.upper()} 活跃订单")
    print(f"环境: {env.upper()}")
    print(f"{'='*80}\n")

    # 加载客户端
    client = load_client(env, symbol)

    try:
        # 查询活跃订单
        orders = client.get_open_orders(symbol=symbol)

        # 分类订单
        buy_orders = [o for o in orders if o['side'] == 'BUY']
        sell_orders = [o for o in orders if o['side'] == 'SELL']

        # 按价格排序
        buy_orders.sort(key=lambda x: float(x['price']), reverse=True)
        sell_orders.sort(key=lambda x: float(x['price']))

        # 统计订单状态
        buy_states = defaultdict(int)
        sell_states = defaultdict(int)

        for order in buy_orders:
            buy_states[order.get('state', 'UNKNOWN')] += 1

        for order in sell_orders:
            sell_states[order.get('state', 'UNKNOWN')] += 1

        # 输出统计
        print(f"\n📊 订单统计:")
        print(f"  总订单数: {len(orders)}")
        print(f"  买单: {len(buy_orders)} 档")
        print(f"  卖单: {len(sell_orders)} 档")

        if buy_states:
            print(f"\n  买单状态分布:")
            for state, count in buy_states.items():
                print(f"    {state}: {count}")

        if sell_states:
            print(f"  卖单状态分布:")
            for state, count in sell_states.items():
                print(f"    {state}: {count}")

        # 显示买盘档位
        print(f"\n{'─'*80}")
        print(f"💰 买盘档位 (共{len(buy_orders)}档):")
        print(f"{'─'*80}")

        if buy_orders:
            print(f"{'档位':<6} {'价格':>12} {'数量':>12} {'状态':<15}")
            print(f"{'─'*80}")

            # 显示所有买单
            for i, order in enumerate(buy_orders, 1):
                price = float(order['price'])
                qty = float(order.get('origQty', order.get('quantity', 0)))
                state = order.get('state', 'UNKNOWN')

                marker = "✅" if state == "NEW" else "⚠️"
                print(f"{marker} {i:<4} {price:>12.6f} {qty:>12.2f} {state:<15}")
        else:
            print("  ⚠️  没有买单")

        # 显示卖盘档位
        print(f"\n{'─'*80}")
        print(f"💵 卖盘档位 (共{len(sell_orders)}档):")
        print(f"{'─'*80}")

        if sell_orders:
            print(f"{'档位':<6} {'价格':>12} {'数量':>12} {'状态':<15}")
            print(f"{'─'*80}")

            # 显示所有卖单
            for i, order in enumerate(sell_orders, 1):
                price = float(order['price'])
                qty = float(order.get('origQty', order.get('quantity', 0)))
                state = order.get('state', 'UNKNOWN')

                marker = "✅" if state == "NEW" else "⚠️"
                print(f"{marker} {i:<4} {price:>12.6f} {qty:>12.2f} {state:<15}")
        else:
            print("  ⚠️  没有卖单")

        # 诊断信息
        print(f"\n{'='*80}")
        print(f"🔍 诊断结果:")
        print(f"{'='*80}")

        expected_levels = 30

        if len(buy_orders) < expected_levels:
            print(f"⚠️  买盘档位不足: {len(buy_orders)}/{expected_levels} (缺少 {expected_levels - len(buy_orders)} 档)")
            print(f"    可能原因:")
            print(f"    1. 订单被成交了")
            print(f"    2. 订单优化算法跳过了某些档位")
            print(f"    3. 洗盘订单占用了某些价位")
        else:
            print(f"✅ 买盘档位正常: {len(buy_orders)}/{expected_levels}")

        if len(sell_orders) < expected_levels:
            print(f"⚠️  卖盘档位不足: {len(sell_orders)}/{expected_levels} (缺少 {expected_levels - len(sell_orders)} 档)")
        else:
            print(f"✅ 卖盘档位正常: {len(sell_orders)}/{expected_levels}")

        # 检查价格连续性
        if len(buy_orders) >= 2:
            gaps = []
            for i in range(len(buy_orders) - 1):
                p1 = float(buy_orders[i]['price'])
                p2 = float(buy_orders[i+1]['price'])
                gap_pct = abs((p1 - p2) / p2) * 100
                if gap_pct > 2:
                    gaps.append((i+1, p1, p2, gap_pct))

            if gaps:
                print(f"\n⚠️  买盘价格跳跃 (>2%):")
                for idx, p1, p2, gap in gaps[:10]:
                    print(f"    档位{idx}-{idx+1}: {p1:.6f} → {p2:.6f} (跳跃{gap:.2f}%)")

        print(f"\n{'='*80}")

    except Exception as e:
        print(f"❌ 查询失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

def main():
    parser = argparse.ArgumentParser(description='查询交易所实际活跃订单')
    parser.add_argument('--symbol', default='ton3l_usdt', help='交易对符号')
    parser.add_argument('--env', default='qa', choices=['qa', 'prod'], help='环境(qa/prod)')

    args = parser.parse_args()

    analyze_orders(symbol=args.symbol, env=args.env)

if __name__ == '__main__':
    main()
