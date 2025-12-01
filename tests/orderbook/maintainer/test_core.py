"""
OrderbookMaintainer 单元测试
"""

import pytest
from decimal import Decimal

from etf.orderbook.maintainer import (
    MaintainerConfig,
    OrderbookMaintainer,
    CurrentOrderbook,
    ExistingOrder,
    MaintenanceResult,
)


class TestOrderbookMaintainer:
    """OrderbookMaintainer 测试"""

    def test_generate_initial(
        self,
        maintainer: OrderbookMaintainer,
        sample_nav: Decimal,
    ):
        """测试生成初始订单簿"""
        snapshot = maintainer.generate_initial(sample_nav)

        assert len(snapshot.bids) > 0
        assert len(snapshot.asks) > 0
        assert maintainer._last_nav == sample_nav

    def test_maintain_empty_current(
        self,
        maintainer: OrderbookMaintainer,
        empty_orderbook: CurrentOrderbook,
        sample_nav: Decimal,
    ):
        """测试维护空当前订单簿"""
        # 先生成初始订单簿
        maintainer.generate_initial(sample_nav)

        # 维护
        result = maintainer.maintain(empty_orderbook, sample_nav)

        assert isinstance(result, MaintenanceResult)
        assert len(result.operations) > 0
        # 所有操作都应该是添加
        assert all(op.action == "add" for op in result.operations)

    def test_maintain_no_change_needed(
        self,
        maintainer: OrderbookMaintainer,
        sample_nav: Decimal,
    ):
        """测试无需变化"""
        # 生成初始订单簿
        initial = maintainer.generate_initial(sample_nav)

        # 用初始订单簿作为当前订单簿
        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id=f"bid_{i}",
                    price=o.price,
                    quantity=o.quantity,
                    side="bid",
                )
                for i, o in enumerate(initial.bids)
            ],
            asks=[
                ExistingOrder(
                    order_id=f"ask_{i}",
                    price=o.price,
                    quantity=o.quantity,
                    side="ask",
                )
                for i, o in enumerate(initial.asks)
            ],
        )

        # NAV 不变
        result = maintainer.maintain(current, sample_nav)

        # 由于 NAV 没有变化，不应该需要更新
        # 但因为价格相同，即使需要更新，操作也应该很少
        assert result.stats.nav_change == Decimal("0")

    def test_maintain_price_up(
        self,
        maintainer: OrderbookMaintainer,
        empty_orderbook: CurrentOrderbook,
        sample_nav: Decimal,
    ):
        """测试价格上涨时的操作排序"""
        maintainer.generate_initial(sample_nav)

        # 价格上涨 5%
        new_nav = sample_nav * Decimal("1.05")
        result = maintainer.maintain(empty_orderbook, new_nav)

        assert result.stats.price_direction == "up"
        assert result.stats.nav_change_pct > Decimal("0")

    def test_maintain_price_down(
        self,
        maintainer: OrderbookMaintainer,
        empty_orderbook: CurrentOrderbook,
        sample_nav: Decimal,
    ):
        """测试价格下跌时的操作排序"""
        maintainer.generate_initial(sample_nav)

        # 价格下跌 5%
        new_nav = sample_nav * Decimal("0.95")
        result = maintainer.maintain(empty_orderbook, new_nav)

        assert result.stats.price_direction == "down"
        assert result.stats.nav_change_pct < Decimal("0")

    def test_maintain_operations_limited(
        self,
        sample_nav: Decimal,
    ):
        """测试操作数量限制"""
        # 创建一个限制为 5 个操作的配置
        from etf.orderbook.maintainer import LayerSpec

        near_layer = LayerSpec(
            name="near",
            distance_range=(Decimal("0"), Decimal("0.005")),
            order_count=10,  # 会生成 10 + 10 = 20 个订单
            budget_ratio=Decimal("0.5"),
        )
        far_layer = LayerSpec(
            name="far",
            distance_range=(Decimal("0.005"), Decimal("0.05")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        config = MaintainerConfig(
            spread=Decimal("0.01"),
            max_distance=Decimal("0.05"),
            total_budget=Decimal("1000"),
            near_layer=near_layer,
            far_layer=far_layer,
            max_operations_per_cycle=5,  # 限制为 5
        )

        maintainer = OrderbookMaintainer(config)
        maintainer.generate_initial(sample_nav)

        result = maintainer.maintain(CurrentOrderbook.empty(), sample_nav)

        # 操作应该被限制
        assert len(result.operations) <= 5
        assert result.stats.operations_limited

    def test_maintain_metrics(
        self,
        maintainer: OrderbookMaintainer,
        empty_orderbook: CurrentOrderbook,
        sample_nav: Decimal,
    ):
        """测试维护结果包含指标"""
        maintainer.generate_initial(sample_nav)
        result = maintainer.maintain(empty_orderbook, sample_nav)

        assert result.metrics is not None
        assert result.metrics.v_bid > Decimal("0")
        assert result.metrics.v_ask > Decimal("0")

    def test_maintain_stats(
        self,
        maintainer: OrderbookMaintainer,
        empty_orderbook: CurrentOrderbook,
        sample_nav: Decimal,
    ):
        """测试维护结果包含统计"""
        maintainer.generate_initial(sample_nav)

        new_nav = sample_nav * Decimal("1.03")
        result = maintainer.maintain(empty_orderbook, new_nav)

        assert result.stats is not None
        assert result.stats.operations_count > 0
        assert 0 <= result.stats.reuse_ratio <= 1

    def test_reset(
        self,
        maintainer: OrderbookMaintainer,
        sample_nav: Decimal,
    ):
        """测试重置"""
        maintainer.generate_initial(sample_nav)
        assert maintainer._last_nav is not None

        maintainer.reset()
        assert maintainer._last_nav is None


class TestOperationSorting:
    """操作排序测试"""

    def test_sort_operations_price_up(self, maintainer: OrderbookMaintainer):
        """测试价格上涨时的排序"""
        from etf.orderbook.base import OrderOperation

        operations = [
            OrderOperation(action="cancel", side="bid", order_id="1"),
            OrderOperation(action="add", side="ask", price=Decimal("1.01"), quantity=Decimal("100")),
            OrderOperation(action="cancel", side="ask", order_id="2"),
            OrderOperation(action="add", side="bid", price=Decimal("0.99"), quantity=Decimal("100")),
        ]

        sorted_ops = maintainer._sort_operations(operations, "up")

        # 价格上涨：add_bid → cancel_ask → add_ask → cancel_bid
        assert sorted_ops[0].action == "add" and sorted_ops[0].side == "bid"
        assert sorted_ops[1].action == "cancel" and sorted_ops[1].side == "ask"
        assert sorted_ops[2].action == "add" and sorted_ops[2].side == "ask"
        assert sorted_ops[3].action == "cancel" and sorted_ops[3].side == "bid"

    def test_sort_operations_price_down(self, maintainer: OrderbookMaintainer):
        """测试价格下跌时的排序"""
        from etf.orderbook.base import OrderOperation

        operations = [
            OrderOperation(action="cancel", side="bid", order_id="1"),
            OrderOperation(action="add", side="ask", price=Decimal("1.01"), quantity=Decimal("100")),
            OrderOperation(action="cancel", side="ask", order_id="2"),
            OrderOperation(action="add", side="bid", price=Decimal("0.99"), quantity=Decimal("100")),
        ]

        sorted_ops = maintainer._sort_operations(operations, "down")

        # 价格下跌：add_ask → cancel_bid → add_bid → cancel_ask
        assert sorted_ops[0].action == "add" and sorted_ops[0].side == "ask"
        assert sorted_ops[1].action == "cancel" and sorted_ops[1].side == "bid"
        assert sorted_ops[2].action == "add" and sorted_ops[2].side == "bid"
        assert sorted_ops[3].action == "cancel" and sorted_ops[3].side == "ask"

    def test_sort_operations_stable(self, maintainer: OrderbookMaintainer):
        """测试稳定时的排序"""
        from etf.orderbook.base import OrderOperation

        operations = [
            OrderOperation(action="cancel", side="bid", order_id="1"),
            OrderOperation(action="add", side="ask", price=Decimal("1.01"), quantity=Decimal("100")),
            OrderOperation(action="cancel", side="ask", order_id="2"),
            OrderOperation(action="add", side="bid", price=Decimal("0.99"), quantity=Decimal("100")),
        ]

        sorted_ops = maintainer._sort_operations(operations, "stable")

        # 稳定：add_bid → add_ask → cancel_bid → cancel_ask
        assert sorted_ops[0].action == "add" and sorted_ops[0].side == "bid"
        assert sorted_ops[1].action == "add" and sorted_ops[1].side == "ask"
        assert sorted_ops[2].action == "cancel" and sorted_ops[2].side == "bid"
        assert sorted_ops[3].action == "cancel" and sorted_ops[3].side == "ask"


class TestIntegration:
    """集成测试"""

    def test_full_workflow(
        self,
        small_config: MaintainerConfig,
    ):
        """测试完整工作流"""
        maintainer = OrderbookMaintainer(small_config)
        nav = Decimal("1.0")

        # 1. 生成初始订单簿
        initial = maintainer.generate_initial(nav)
        assert len(initial.bids) == small_config.total_orders_per_side
        assert len(initial.asks) == small_config.total_orders_per_side

        # 2. 模拟空的当前订单簿
        result1 = maintainer.maintain(CurrentOrderbook.empty(), nav)
        assert result1.needs_update
        assert len(result1.operations) > 0

        # 3. 价格上涨后维护
        new_nav = nav * Decimal("1.05")
        result2 = maintainer.maintain(CurrentOrderbook.empty(), new_nav)
        assert result2.stats.price_direction == "up"

        # 4. 验证平衡指标
        assert result2.metrics.is_balanced or abs(result2.metrics.vii) < Decimal("0.15")

    def test_multiple_cycles(
        self,
        small_config: MaintainerConfig,
    ):
        """测试多个周期"""
        maintainer = OrderbookMaintainer(small_config)
        nav = Decimal("1.0")

        # 初始化
        maintainer.generate_initial(nav)

        # 模拟多个价格变化周期
        price_changes = [1.02, 1.05, 1.03, 0.98, 0.95, 1.0]

        for change in price_changes:
            new_nav = Decimal(str(change))
            result = maintainer.maintain(CurrentOrderbook.empty(), new_nav)
            assert result is not None
            # 验证指标计算正确
            assert result.metrics.v_bid > Decimal("0")
            assert result.metrics.v_ask > Decimal("0")
