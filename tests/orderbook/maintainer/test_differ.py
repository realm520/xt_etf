"""
OrderbookDiffer 单元测试
"""

import pytest
from decimal import Decimal

from etf.orderbook.base import OrderLevel
from etf.orderbook.maintainer import (
    MaintainerConfig,
    OrderbookDiffer,
    CurrentOrderbook,
    ExistingOrder,
)


class TestExistingOrder:
    """ExistingOrder 测试"""

    def test_create_existing_order(self):
        """测试创建现有订单"""
        order = ExistingOrder(
            order_id="123",
            price=Decimal("1.0"),
            quantity=Decimal("100"),
            side="bid",
        )
        assert order.order_id == "123"
        assert order.price == Decimal("1.0")
        assert order.quantity == Decimal("100")
        assert order.side == "bid"

    def test_auto_type_conversion(self):
        """测试自动类型转换"""
        order = ExistingOrder(
            order_id="123",
            price=1.0,  # float
            quantity=100,  # int
            side="ask",
        )
        assert isinstance(order.price, Decimal)
        assert isinstance(order.quantity, Decimal)


class TestCurrentOrderbook:
    """CurrentOrderbook 测试"""

    def test_from_exchange_orders(self, sample_exchange_orders: list):
        """测试从交易所订单转换"""
        orderbook = CurrentOrderbook.from_exchange_orders(sample_exchange_orders)

        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 2
        assert orderbook.total_orders == 4
        assert not orderbook.is_empty

    def test_empty_orderbook(self):
        """测试空订单簿"""
        orderbook = CurrentOrderbook.empty()
        assert orderbook.total_orders == 0
        assert orderbook.is_empty

    def test_mixed_sides(self):
        """测试混合方向"""
        orders = [
            {"orderId": "1", "price": "1.0", "origQty": "100", "side": "BUY"},
            {"orderId": "2", "price": "1.1", "origQty": "100", "side": "SELL"},
            {"orderId": "3", "price": "0.9", "origQty": "100", "side": "BUY"},
        ]
        orderbook = CurrentOrderbook.from_exchange_orders(orders)
        assert len(orderbook.bids) == 2
        assert len(orderbook.asks) == 1

    def test_unknown_side_skipped(self):
        """测试跳过未知方向"""
        orders = [
            {"orderId": "1", "price": "1.0", "origQty": "100", "side": "UNKNOWN"},
        ]
        orderbook = CurrentOrderbook.from_exchange_orders(orders)
        assert orderbook.is_empty


class TestOrderbookDiffer:
    """OrderbookDiffer 测试"""

    def test_compute_diff_empty_current(
        self,
        differ: OrderbookDiffer,
        empty_orderbook: CurrentOrderbook,
        sample_bids: list,
        sample_asks: list,
        small_config: MaintainerConfig,
    ):
        """测试空当前订单簿"""
        ops = differ.compute_diff(
            empty_orderbook,
            sample_bids,
            sample_asks,
            Decimal("1.0"),
            small_config,
        )

        # 所有目标订单都应该添加
        add_ops = [op for op in ops if op.action == "add"]
        assert len(add_ops) == len(sample_bids) + len(sample_asks)

        # 没有取消操作
        cancel_ops = [op for op in ops if op.action == "cancel"]
        assert len(cancel_ops) == 0

    def test_compute_diff_no_change(
        self,
        differ: OrderbookDiffer,
        small_config: MaintainerConfig,
    ):
        """测试无变化"""
        # 创建相同的当前和目标订单簿
        target_bids = [
            OrderLevel(
                price=Decimal("0.995"),
                quantity=Decimal("100"),
                value=Decimal("99.5"),
                side="bid",
            ),
        ]
        target_asks = [
            OrderLevel(
                price=Decimal("1.005"),
                quantity=Decimal("100"),
                value=Decimal("100.5"),
                side="ask",
            ),
        ]

        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id="1",
                    price=Decimal("0.995"),
                    quantity=Decimal("100"),
                    side="bid",
                ),
            ],
            asks=[
                ExistingOrder(
                    order_id="2",
                    price=Decimal("1.005"),
                    quantity=Decimal("100"),
                    side="ask",
                ),
            ],
        )

        ops = differ.compute_diff(
            current,
            target_bids,
            target_asks,
            Decimal("1.0"),
            small_config,
        )

        # 应该没有操作（订单被复用）
        assert len(ops) == 0

    def test_compute_diff_quantity_tolerance(
        self,
        differ: OrderbookDiffer,
        small_config: MaintainerConfig,
    ):
        """测试数量容差"""
        target_bids = [
            OrderLevel(
                price=Decimal("0.995"),
                quantity=Decimal("100"),
                value=Decimal("99.5"),
                side="bid",
            ),
        ]

        # 数量差 5%，在 10% 容差内
        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id="1",
                    price=Decimal("0.995"),
                    quantity=Decimal("105"),  # 5% 差异
                    side="bid",
                ),
            ],
            asks=[],
        )

        ops = differ.compute_diff(
            current, target_bids, [], Decimal("1.0"), small_config
        )

        # 应该被复用
        assert len(ops) == 0

    def test_compute_diff_quantity_out_of_tolerance(
        self,
        differ: OrderbookDiffer,
        small_config: MaintainerConfig,
    ):
        """测试超出数量容差"""
        target_bids = [
            OrderLevel(
                price=Decimal("0.995"),
                quantity=Decimal("100"),
                value=Decimal("99.5"),
                side="bid",
            ),
        ]

        # 数量差 20%，超出 10% 容差
        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id="1",
                    price=Decimal("0.995"),
                    quantity=Decimal("120"),  # 20% 差异
                    side="bid",
                ),
            ],
            asks=[],
        )

        ops = differ.compute_diff(
            current, target_bids, [], Decimal("1.0"), small_config
        )

        # 应该取消旧订单，添加新订单
        assert len(ops) == 2
        assert any(op.action == "cancel" for op in ops)
        assert any(op.action == "add" for op in ops)

    def test_compute_diff_unmatched_current(
        self,
        differ: OrderbookDiffer,
        small_config: MaintainerConfig,
    ):
        """测试未匹配的现有订单"""
        target_bids = []  # 空目标

        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id="1",
                    price=Decimal("0.995"),
                    quantity=Decimal("100"),
                    side="bid",
                ),
            ],
            asks=[],
        )

        ops = differ.compute_diff(
            current, target_bids, [], Decimal("1.0"), small_config
        )

        # 应该取消现有订单
        assert len(ops) == 1
        assert ops[0].action == "cancel"
        assert ops[0].order_id == "1"

    def test_compute_reuse_ratio_full_reuse(
        self,
        differ: OrderbookDiffer,
        small_config: MaintainerConfig,
    ):
        """测试完全复用"""
        target_bids = [
            OrderLevel(
                price=Decimal("0.995"),
                quantity=Decimal("100"),
                value=Decimal("99.5"),
                side="bid",
            ),
        ]

        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id="1",
                    price=Decimal("0.995"),
                    quantity=Decimal("100"),
                    side="bid",
                ),
            ],
            asks=[],
        )

        ratio = differ.compute_reuse_ratio(current, target_bids, [], small_config)
        assert ratio == 1.0

    def test_compute_reuse_ratio_no_reuse(
        self,
        differ: OrderbookDiffer,
        small_config: MaintainerConfig,
    ):
        """测试无复用"""
        target_bids = [
            OrderLevel(
                price=Decimal("0.800"),  # 完全不同的价格
                quantity=Decimal("100"),
                value=Decimal("80"),
                side="bid",
            ),
        ]

        current = CurrentOrderbook(
            bids=[
                ExistingOrder(
                    order_id="1",
                    price=Decimal("0.995"),
                    quantity=Decimal("100"),
                    side="bid",
                ),
            ],
            asks=[],
        )

        ratio = differ.compute_reuse_ratio(current, target_bids, [], small_config)
        assert ratio == 0.0

    def test_compute_reuse_ratio_empty_current(
        self,
        differ: OrderbookDiffer,
        empty_orderbook: CurrentOrderbook,
        sample_bids: list,
        small_config: MaintainerConfig,
    ):
        """测试空当前订单簿的复用率"""
        ratio = differ.compute_reuse_ratio(
            empty_orderbook, sample_bids, [], small_config
        )
        assert ratio == 0.0
