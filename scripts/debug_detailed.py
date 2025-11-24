#!/usr/bin/env python3
"""
详细调试订单簿生成过程
"""

from etf.orderbook.base import OrderbookConfig, OrderbookFactory
import time

def debug_generation():
    """调试生成过程"""
    print("=" * 80)
    print("订单簿生成详细调试")
    print("=" * 80)

    config = OrderbookConfig(
        total_budget=10000.0,
        layer=250,  # 单边250档
        mid_price=1.0,
        bid_ask_spread=0.008,
        symbol="TON3L_USDT",
        price_precision=4,
        quantity_precision=2,
        extra_params={"naturalness": "high"}
    )

    algorithm = OrderbookFactory.create("natural", config)

    # 手动调用各个步骤
    print(f"\n配置:")
    print(f"  total_budget: {config.total_budget}")
    print(f"  layer: {config.layer}")
    print(f"  单边配置: {config.layer // 2} 档")

    # 生成价格
    print(f"\n生成价格...")
    n_bid = config.layer // 2
    n_ask = config.layer - n_bid
    print(f"  n_bid: {n_bid}")
    print(f"  n_ask: {n_ask}")

    bid_prices = algorithm._generate_prices(n_bid, side='bid')
    ask_prices = algorithm._generate_prices(n_ask, side='ask')

    print(f"  买盘价格档位数: {len(bid_prices)}")
    print(f"  卖盘价格档位数: {len(ask_prices)}")

    # 生成数量
    print(f"\n生成数量...")
    bid_quantities = algorithm._generate_quantities(bid_prices, "high")
    ask_quantities = algorithm._generate_quantities(ask_prices, "high")

    print(f"  买盘数量档位数: {len(bid_quantities)}")
    print(f"  卖盘数量档位数: {len(ask_quantities)}")

    # 应用特效
    print(f"\n应用特效...")
    bid_quantities = algorithm._apply_effects(bid_prices, bid_quantities, "high")
    ask_quantities = algorithm._apply_effects(ask_prices, ask_quantities, "high")

    print(f"  买盘数量档位数（特效后）: {len(bid_quantities)}")
    print(f"  卖盘数量档位数（特效后）: {len(ask_quantities)}")

    # 归一化
    print(f"\n归一化到预算...")
    bid_quantities = algorithm._normalize_to_budget(bid_prices, bid_quantities, 'bid')
    ask_quantities = algorithm._normalize_to_budget(ask_prices, ask_quantities, 'ask')

    print(f"  买盘数量档位数（归一化后）: {len(bid_quantities)}")
    print(f"  卖盘数量档位数（归一化后）: {len(ask_quantities)}")

    # 构建订单
    print(f"\n构建订单...")
    bids = algorithm._build_levels(bid_prices, bid_quantities, 'bid')
    asks = algorithm._build_levels(ask_prices, ask_quantities, 'ask')

    print(f"  买盘档位数（最终）: {len(bids)}")
    print(f"  卖盘档位数（最终）: {len(asks)}")
    print(f"  总档位数: {len(bids) + len(asks)}")

    # 完整生成
    print(f"\n完整生成测试...")
    snapshot = algorithm.generate_snapshot()
    print(f"  快照买盘档位数: {len(snapshot.bids)}")
    print(f"  快照卖盘档位数: {len(snapshot.asks)}")
    print(f"  快照总档位数: {len(snapshot.bids) + len(snapshot.asks)}")

    print("\n" + "=" * 80)

if __name__ == "__main__":
    debug_generation()
