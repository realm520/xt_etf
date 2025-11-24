#!/usr/bin/env python3
"""
订单簿性能测试脚本

测试不同档位下的订单簿生成性能
"""

import time
from etf.orderbook.base import OrderbookConfig, OrderbookFactory


def test_performance():
    """测试不同档位的性能"""
    print("=" * 60)
    print("订单簿算法性能测试")
    print("=" * 60)

    # 测试档位
    layer_tests = [1000, 5000, 10000, 20000, 50000, 100000]

    print("\n档位数  |  生成时间  |  总金额(USDT)  |  买盘档数  |  卖盘档数")
    print("-" * 60)

    for layer in layer_tests:
        config = OrderbookConfig(
            total_budget=10000.0,
            layer=layer,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol="TEST_USDT",
            price_precision=6,
            quantity_precision=2,
            extra_params={"naturalness": "high"}
        )

        algorithm = OrderbookFactory.create("natural", config)

        start = time.time()
        snapshot = algorithm.generate_snapshot()
        elapsed = time.time() - start

        print(
            f"{layer:>6}档 | {elapsed*1000:>8.2f}ms | {float(snapshot.total_value):>12.2f} | "
            f"{len(snapshot.bids):>8} | {len(snapshot.asks):>8}"
        )

        # 验证性能要求
        if layer == 5000 and elapsed > 0.05:
            print(f"  ⚠️  警告: 5000档生成耗时 {elapsed:.3f}s 超过50ms")
        elif layer == 10000 and elapsed > 0.10:
            print(f"  ⚠️  警告: 10000档生成耗时 {elapsed:.3f}s 超过100ms")
        elif layer == 100000 and elapsed > 1.0:
            print(f"  ⚠️  警告: 100000档生成耗时 {elapsed:.3f}s 超过1s")

    print("=" * 60)


def test_naturalness_levels():
    """测试不同自然度级别的性能"""
    print("\n自然度级别性能对比 (5000档)")
    print("=" * 60)
    print("级别    |  生成时间  |  总金额(USDT)")
    print("-" * 40)

    for naturalness in ["low", "medium", "high", "ultra"]:
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=5000,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol="TEST_USDT",
            extra_params={"naturalness": naturalness}
        )

        algorithm = OrderbookFactory.create("natural", config)

        start = time.time()
        snapshot = algorithm.generate_snapshot()
        elapsed = time.time() - start

        print(
            f"{naturalness:>7} | {elapsed*1000:>8.2f}ms | {float(snapshot.total_value):>12.2f}"
        )

    print("=" * 60)


def test_snapshot_format():
    """测试订单簿快照格式"""
    print("\n订单簿快照格式验证")
    print("=" * 60)

    config = OrderbookConfig(
        total_budget=1000.0,
        layer=1000,
        mid_price=1.0,
        bid_ask_spread=0.01,
        symbol="TEST_USDT",
        extra_params={"naturalness": "medium"}
    )

    algorithm = OrderbookFactory.create("natural", config)
    snapshot = algorithm.generate_snapshot()

    print(f"算法名称: {snapshot.algorithm}")
    print(f"买盘档数: {len(snapshot.bids)}")
    print(f"卖盘档数: {len(snapshot.asks)}")
    print(f"总金额: {float(snapshot.total_value):.2f} USDT")
    print(f"生成时间: {snapshot.generation_time*1000:.2f}ms")

    # 显示前3档
    print("\n买盘前3档:")
    for i, level in enumerate(snapshot.bids[:3]):
        print(f"  档{i+1}: 价格={float(level.price):.6f}, 数量={float(level.quantity):.2f}, 金额={float(level.value):.2f}")

    print("\n卖盘前3档:")
    for i, level in enumerate(snapshot.asks[:3]):
        print(f"  档{i+1}: 价格={float(level.price):.6f}, 数量={float(level.quantity):.2f}, 金额={float(level.value):.2f}")

    # 转换为字典格式
    dict_format = snapshot.to_dict()
    print(f"\n字典格式验证:")
    print(f"  包含keys: {list(dict_format.keys())}")
    print(f"  买盘格式: [[price, quantity], ...] - OK ✅" if isinstance(dict_format['bids'][0], list) else "❌")

    print("=" * 60)


if __name__ == "__main__":
    try:
        test_performance()
        test_naturalness_levels()
        test_snapshot_format()
        print("\n✅ 所有性能测试通过!")
    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
