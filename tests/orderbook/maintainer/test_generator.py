"""
OrderbookGenerator 单元测试
"""

import pytest
from decimal import Decimal

from etf.orderbook.maintainer import (
    MaintainerConfig,
    OrderbookGenerator,
)


class TestOrderbookGenerator:
    """OrderbookGenerator 测试"""

    def test_generate_basic(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试基本生成"""
        snapshot = generator.generate(sample_nav, small_config)

        assert len(snapshot.bids) > 0
        assert len(snapshot.asks) > 0
        assert snapshot.algorithm == "maintainer"

    def test_generate_order_count(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试订单数量"""
        snapshot = generator.generate(sample_nav, small_config)

        expected_per_side = small_config.total_orders_per_side
        assert len(snapshot.bids) == expected_per_side
        assert len(snapshot.asks) == expected_per_side

    def test_generate_value_balance(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试价值平衡"""
        snapshot = generator.generate(sample_nav, small_config)

        v_bid = sum(o.price * o.quantity for o in snapshot.bids)
        v_ask = sum(o.price * o.quantity for o in snapshot.asks)

        # 允许 5% 误差（由于四舍五入）
        ratio = v_bid / v_ask if v_ask > 0 else Decimal("0")
        assert Decimal("0.95") <= ratio <= Decimal("1.05"), f"Value ratio: {ratio}"

    def test_generate_price_order(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试价格排序"""
        snapshot = generator.generate(sample_nav, small_config)

        # 买单应该按价格降序
        bid_prices = [o.price for o in snapshot.bids]
        assert bid_prices == sorted(bid_prices, reverse=True)

        # 卖单应该按价格升序
        ask_prices = [o.price for o in snapshot.asks]
        assert ask_prices == sorted(ask_prices)

    def test_generate_spread_respected(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试价差设置"""
        snapshot = generator.generate(sample_nav, small_config)

        best_bid = max(o.price for o in snapshot.bids)
        best_ask = min(o.price for o in snapshot.asks)

        actual_spread = (best_ask - best_bid) / sample_nav
        expected_spread = small_config.spread

        # 允许 10% 误差
        assert abs(actual_spread - expected_spread) <= expected_spread * Decimal("0.1")

    def test_generate_layer_metadata(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试层元数据"""
        snapshot = generator.generate(sample_nav, small_config)

        near_bids = [o for o in snapshot.bids if o.metadata.get("layer") == "near"]
        far_bids = [o for o in snapshot.bids if o.metadata.get("layer") == "far"]

        assert len(near_bids) == small_config.near_layer.order_count
        assert len(far_bids) == small_config.far_layer.order_count

    def test_generate_different_navs(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
    ):
        """测试不同 NAV"""
        nav1 = Decimal("1.0")
        nav2 = Decimal("2.0")

        snapshot1 = generator.generate(nav1, small_config)
        snapshot2 = generator.generate(nav2, small_config)

        # NAV 翻倍，最佳买价也应该接近翻倍
        best_bid1 = max(o.price for o in snapshot1.bids)
        best_bid2 = max(o.price for o in snapshot2.bids)

        ratio = best_bid2 / best_bid1
        assert Decimal("1.9") <= ratio <= Decimal("2.1")

    def test_generate_invalid_nav(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
    ):
        """测试无效 NAV"""
        with pytest.raises(ValueError, match="nav must be positive"):
            generator.generate(Decimal("0"), small_config)

        with pytest.raises(ValueError, match="nav must be positive"):
            generator.generate(Decimal("-1"), small_config)

    def test_generate_float_nav(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
    ):
        """测试 float NAV 自动转换"""
        snapshot = generator.generate(1.5, small_config)  # float, not Decimal
        assert len(snapshot.bids) > 0

    def test_near_layer_arithmetic(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试近盘口等差分布"""
        snapshot = generator.generate(sample_nav, small_config)

        near_bids = sorted(
            [o for o in snapshot.bids if o.metadata.get("layer") == "near"],
            key=lambda x: x.price,
            reverse=True,
        )

        if len(near_bids) >= 3:
            # 检查等差：相邻价格差应该相近
            diffs = [
                near_bids[i].price - near_bids[i + 1].price
                for i in range(len(near_bids) - 1)
            ]
            if diffs:
                avg_diff = sum(diffs) / len(diffs)
                for d in diffs:
                    assert abs(d - avg_diff) <= avg_diff * Decimal("0.1")

    def test_far_layer_geometric(
        self,
        generator: OrderbookGenerator,
        small_config: MaintainerConfig,
        sample_nav: Decimal,
    ):
        """测试远盘口等比分布"""
        snapshot = generator.generate(sample_nav, small_config)

        far_bids = sorted(
            [o for o in snapshot.bids if o.metadata.get("layer") == "far"],
            key=lambda x: x.price,
            reverse=True,
        )

        if len(far_bids) >= 3:
            # 检查等比：相邻价格比应该相近
            ratios = [
                far_bids[i].price / far_bids[i + 1].price
                for i in range(len(far_bids) - 1)
                if far_bids[i + 1].price > 0
            ]
            if ratios:
                avg_ratio = sum(ratios) / len(ratios)
                for r in ratios:
                    assert abs(r - avg_ratio) <= avg_ratio * Decimal("0.15")
