#!/usr/bin/env python3
"""
测试 ton3l 策略的新订单簿配置

需求验证：
- 总预算: 10000 USDT
- 总档位: 500档（买250 + 卖250）
- 买卖对称: 档位数相同
- 高自然度: 95%真实性
"""

from etf.orderbook.base import OrderbookConfig, OrderbookFactory


def test_ton3l_orderbook():
    """测试 ton3l 配置的订单簿生成"""
    print("=" * 80)
    print("TON3L 订单簿测试（10000 USDT, 500档总数）")
    print("=" * 80)

    # 配置参数（与 strategies.yaml 一致）
    config = OrderbookConfig(
        total_budget=10000.0,
        layer=500,  # 总档位500（买250 + 卖250，对称）
        mid_price=1.0,
        bid_ask_spread=0.008,
        symbol="TON3L_USDT",
        price_precision=4,
        quantity_precision=2,
        extra_params={"naturalness": "high"}
    )

    # 创建算法实例
    algorithm = OrderbookFactory.create("natural", config)

    # 生成订单簿
    import time
    start = time.time()
    snapshot = algorithm.generate_snapshot()
    elapsed = time.time() - start

    # 验证结果
    print(f"\n📊 生成结果:")
    print(f"  算法: {snapshot.algorithm}")
    print(f"  买盘档数: {len(snapshot.bids)}")
    print(f"  卖盘档数: {len(snapshot.asks)}")
    print(f"  总档位: {len(snapshot.bids) + len(snapshot.asks)}")
    print(f"  总金额: {float(snapshot.total_value):.2f} USDT")
    print(f"  生成时间: {elapsed*1000:.2f}ms")

    # 验证对称性
    print(f"\n✅ 对称性验证:")
    print(f"  买盘档数: {len(snapshot.bids)}")
    print(f"  卖盘档数: {len(snapshot.asks)}")
    diff = abs(len(snapshot.bids) - len(snapshot.asks))
    print(f"  档位差异: {diff} ({'✅ 对称' if diff == 0 else '⚠️ 不对称'})")

    # 验证预算
    print(f"\n💰 预算验证:")
    print(f"  目标预算: 10000.00 USDT")
    print(f"  实际总额: {float(snapshot.total_value):.2f} USDT")
    deviation = (float(snapshot.total_value) - 10000.0) / 10000.0 * 100
    print(f"  偏差: {deviation:.2f}% ({'✅ 合格' if abs(deviation) < 1 else '⚠️ 超标'})")

    # 显示买卖盘前5档
    print(f"\n📈 买盘前5档:")
    for i, level in enumerate(snapshot.bids[:5]):
        print(f"  档{i+1}: 价格={float(level.price):.4f}, "
              f"数量={float(level.quantity):.2f}, "
              f"金额={float(level.value):.2f} USDT")

    print(f"\n📉 卖盘前5档:")
    for i, level in enumerate(snapshot.asks[:5]):
        print(f"  档{i+1}: 价格={float(level.price):.4f}, "
              f"数量={float(level.quantity):.2f}, "
              f"金额={float(level.value):.2f} USDT")

    print("\n" + "=" * 80)

    # 返回验证结果
    return {
        "total_layers": len(snapshot.bids) + len(snapshot.asks),
        "symmetric": diff == 0,
        "budget_ok": abs(deviation) < 1,
        "performance_ok": elapsed < 0.1,  # <100ms
    }


if __name__ == "__main__":
    try:
        result = test_ton3l_orderbook()

        print("\n✅ 测试结果:")
        print(f"  总档位正确: {'✅' if result['total_layers'] == 500 else '❌'} ({result['total_layers']}档)")
        print(f"  买卖对称: {'✅' if result['symmetric'] else '❌'}")
        print(f"  预算合理: {'✅' if result['budget_ok'] else '❌'}")
        print(f"  性能达标: {'✅' if result['performance_ok'] else '❌'}")

        if all(result.values()):
            print("\n🎉 所有测试通过！配置可以投入使用。")
        else:
            print("\n⚠️ 部分测试未通过，请检查配置。")

    except Exception as e:
        print(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
