#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""测试订单簿分布是否对称"""

import sys
sys.path.insert(0, '.')

from etf.orderbook import get_orderbook

# 模拟参数
mid_price = 0.70
bid_ask_spread = 0.008
min_order_value = 20.0
init_amount_multiplier = 1.5
amount_growth_rate = 0.08
layer = 30

print(f"\n订单簿分布测试 (净值={mid_price})")
print("=" * 80)

# 生成订单簿
batch_order_bid, batch_order_ask = get_orderbook(
    mid_price=mid_price,
    bid_ask_spread=bid_ask_spread,
    min_order_value=min_order_value,
    init_amount_multiplier=init_amount_multiplier,
    amount_growth_rate=amount_growth_rate,
    layer=layer
)

# 买盘前5档
print("\n买盘前5档:")
for i, order in enumerate(batch_order_bid[:5], 1):
    value = order['price'] * order['amount']
    print(f"  {i}. 价格={order['price']:.6f}, 数量={order['amount']:.2f}, 金额={value:.2f} USDT")

# 卖盘前5档
print("\n卖盘前5档:")
for i, order in enumerate(batch_order_ask[:5], 1):
    value = order['price'] * order['amount']
    print(f"  {i}. 价格={order['price']:.6f}, 数量={order['amount']:.2f}, 金额={value:.2f} USDT")

# 总金额
total_bid = sum(o['price'] * o['amount'] for o in batch_order_bid)
total_ask = sum(o['price'] * o['amount'] for o in batch_order_ask)

print(f"\n总金额对比:")
print(f"  买盘总金额: {total_bid:.2f} USDT")
print(f"  卖盘总金额: {total_ask:.2f} USDT")
print(f"  比率: {total_ask/total_bid:.4f}")
