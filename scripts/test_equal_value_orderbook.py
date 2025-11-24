#!/usr/bin/env python3
"""
测试等价值订单簿生成功能

功能：
1. 对比原始订单簿 vs 等价值订单簿
2. 验证资金使用效率
3. 检查资金不足时的自动调整
"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from etf.orderbook import get_orderbook, get_orderbook_equal_value
import logging

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s"
)

def analyze_orderbook(batch_bid, batch_ask, name="订单簿"):
    """分析订单簿资金分布"""
    print(f"\n{'=' * 60}")
    print(f"📊 {name} 分析")
    print(f"{'=' * 60}")

    # === 买单分析 ===
    bid_values = [order['price'] * order['amount'] for order in batch_bid]
    bid_total = sum(bid_values)
    bid_avg = bid_total / len(batch_bid) if batch_bid else 0
    bid_min = min(bid_values) if bid_values else 0
    bid_max = max(bid_values) if bid_values else 0

    print(f"\n🔵 买单 ({len(batch_bid)} 档):")
    print(f"   总金额: {bid_total:.2f} USDT")
    print(f"   平均金额: {bid_avg:.2f} USDT/档")
    print(f"   最小档: {bid_min:.2f} USDT (价格: {batch_bid[-1]['price']:.6f})")
    print(f"   最大档: {bid_max:.2f} USDT (价格: {batch_bid[0]['price']:.6f})")
    print(f"   金额跨度: {bid_max / bid_min:.2f}x" if bid_min > 0 else "   金额跨度: N/A")

    # === 卖单分析 ===
    ask_values = [order['price'] * order['amount'] for order in batch_ask]
    ask_total = sum(ask_values)
    ask_avg = ask_total / len(batch_ask) if batch_ask else 0
    ask_min = min(ask_values) if ask_values else 0
    ask_max = max(ask_values) if ask_values else 0

    print(f"\n🔴 卖单 ({len(batch_ask)} 档):")
    print(f"   总金额: {ask_total:.2f} USDT")
    print(f"   平均金额: {ask_avg:.2f} USDT/档")
    print(f"   最小档: {ask_min:.2f} USDT (价格: {batch_ask[0]['price']:.6f})")
    print(f"   最大档: {ask_max:.2f} USDT (价格: {batch_ask[-1]['price']:.6f})")
    print(f"   金额跨度: {ask_max / ask_min:.2f}x" if ask_min > 0 else "   金额跨度: N/A")

    # === 总计 ===
    total_value = bid_total + ask_total
    print(f"\n💰 总计:")
    print(f"   总占用: {total_value:.2f} USDT")
    if total_value > 0:
        print(f"   买单占比: {bid_total / total_value * 100:.1f}%")
        print(f"   卖单占比: {ask_total / total_value * 100:.1f}%")
    else:
        print(f"   ⚠️ 警告：订单总金额为0（可能是精度问题）")

    return total_value


def test_comparison():
    """对比测试：原始 vs 等价值"""
    print("\n" + "=" * 70)
    print("🔬 测试1：原始订单簿 vs 等价值订单簿对比")
    print("=" * 70)

    mid_price = 5.0
    bid_ask_spread = 0.01

    # === 原始订单簿 ===
    print("\n📌 生成原始订单簿（指数递增）...")
    batch_bid_old, batch_ask_old = get_orderbook(
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        min_order_value=1.2,
    )
    total_old = analyze_orderbook(batch_bid_old, batch_ask_old, "原始订单簿（指数递增）")

    # === 等价值订单簿 ===
    print("\n📌 生成等价值订单簿（每档2 USDT）...")
    batch_bid_new, batch_ask_new = get_orderbook_equal_value(
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        target_value_per_order=2.0,
        layer=30,
    )
    total_new = analyze_orderbook(batch_bid_new, batch_ask_new, "等价值订单簿")

    # === 对比结果 ===
    print(f"\n{'=' * 60}")
    print(f"📊 对比结果")
    print(f"{'=' * 60}")
    print(f"原始订单簿总占用: {total_old:.2f} USDT")
    print(f"等价值订单簿总占用: {total_new:.2f} USDT")
    print(f"资金节省: {total_old - total_new:.2f} USDT ({(1 - total_new / total_old) * 100:.1f}%)")


def test_budget_constraint():
    """测试预算限制功能"""
    print("\n" + "=" * 70)
    print("🔬 测试2：预算限制功能")
    print("=" * 70)

    mid_price = 5.0
    bid_ask_spread = 0.01
    target_value = 2.0
    layer = 30

    # === 场景1：预算充足 ===
    print("\n📌 场景1：预算充足（500 USDT）")
    batch_bid, batch_ask = get_orderbook_equal_value(
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        target_value_per_order=target_value,
        total_budget=500,
        layer=layer,
    )
    analyze_orderbook(batch_bid, batch_ask, "预算充足")

    # === 场景2：预算紧张 ===
    print("\n📌 场景2：预算紧张（80 USDT）")
    batch_bid, batch_ask = get_orderbook_equal_value(
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        target_value_per_order=target_value,
        total_budget=80,
        layer=layer,
    )
    analyze_orderbook(batch_bid, batch_ask, "预算紧张（自动调整）")

    # === 场景3：无预算限制 ===
    print("\n📌 场景3：无预算限制")
    batch_bid, batch_ask = get_orderbook_equal_value(
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        target_value_per_order=target_value,
        total_budget=None,
        layer=layer,
    )
    analyze_orderbook(batch_bid, batch_ask, "无预算限制")


def test_edge_cases():
    """测试边缘情况"""
    print("\n" + "=" * 70)
    print("🔬 测试3：边缘情况")
    print("=" * 70)

    # === 极小价格 ===
    print("\n📌 场景1：极小价格（0.001 USDT）")
    batch_bid, batch_ask = get_orderbook_equal_value(
        mid_price=0.001,
        bid_ask_spread=0.02,
        target_value_per_order=1.5,
        layer=10,
    )
    analyze_orderbook(batch_bid, batch_ask, "极小价格")

    # === 极大价格 ===
    print("\n📌 场景2：极大价格（50000 USDT）")
    batch_bid, batch_ask = get_orderbook_equal_value(
        mid_price=50000,
        bid_ask_spread=0.005,
        target_value_per_order=10.0,
        layer=10,
    )
    analyze_orderbook(batch_bid, batch_ask, "极大价格")


if __name__ == "__main__":
    print("\n" + "🚀" * 35)
    print("等价值订单簿测试工具")
    print("🚀" * 35)

    try:
        test_comparison()
        test_budget_constraint()
        test_edge_cases()

        print("\n" + "=" * 70)
        print("✅ 所有测试完成！")
        print("=" * 70)

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
