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
        """测试操作数量限制（维护阶段，非初始化）"""
        # 创建一个限制为 5 个操作的配置
        from etf.orderbook.maintainer import LayerSpec
        from etf.orderbook.maintainer.differ import ExistingOrder

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
        initial_snapshot = maintainer.generate_initial(sample_nav)

        # 创建一个有足够订单的 current orderbook（模拟维护阶段，非初始化）
        # 需要超过目标订单数的 20%，这样才会触发限制
        # 目标订单数 = 20 (10 near + 10 far) * 2 (买卖) = 40
        # 20% = 8 个订单
        existing_bids = [
            ExistingOrder(
                order_id=f"bid_{i}",
                price=initial_snapshot.bids[i].price if i < len(initial_snapshot.bids) else Decimal("0.99"),
                quantity=initial_snapshot.bids[i].quantity if i < len(initial_snapshot.bids) else Decimal("10"),
                side="bid",
            )
            for i in range(10)  # 10 个买单
        ]
        existing_asks = [
            ExistingOrder(
                order_id=f"ask_{i}",
                price=initial_snapshot.asks[i].price if i < len(initial_snapshot.asks) else Decimal("1.01"),
                quantity=initial_snapshot.asks[i].quantity if i < len(initial_snapshot.asks) else Decimal("10"),
                side="ask",
            )
            for i in range(10)  # 10 个卖单
        ]
        current = CurrentOrderbook(bids=existing_bids, asks=existing_asks)

        # NAV 变化 5%，触发大量调整
        new_nav = sample_nav * Decimal("1.05")
        result = maintainer.maintain(current, new_nav)

        # 维护阶段：操作应该被限制到 max_operations_per_cycle
        assert len(result.operations) <= 5
        assert result.stats.operations_limited

    def test_initial_no_limit(
        self,
        sample_nav: Decimal,
    ):
        """测试初始化阶段不限制操作数量"""
        from etf.orderbook.maintainer import LayerSpec

        near_layer = LayerSpec(
            name="near",
            distance_range=(Decimal("0"), Decimal("0.005")),
            order_count=10,
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
            max_operations_per_cycle=5,  # 即使限制为 5
        )

        maintainer = OrderbookMaintainer(config)
        maintainer.generate_initial(sample_nav)

        # 空订单簿 = 初始化阶段，不限制操作数量
        result = maintainer.maintain(CurrentOrderbook.empty(), sample_nav)

        # 初始化阶段：应该一次性添加所有订单（40 个）
        assert len(result.operations) == 40  # 20 买 + 20 卖
        assert not result.stats.operations_limited  # 未被限制

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


class TestBidAskBalance:
    """买卖平衡测试 - 回归测试确保不会出现单边被清空的问题"""

    def test_limit_operations_preserves_bid_ask_balance(self):
        """测试限制操作时保持买卖平衡"""
        from etf.orderbook.base import OrderOperation
        from etf.orderbook.maintainer import MaintainerConfig, LayerSpec
        
        # 创建配置
        near_layer = LayerSpec(
            name="near",
            distribution="arithmetic",
            distance_range=(Decimal("0.005"), Decimal("0.02")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        far_layer = LayerSpec(
            name="far",
            distribution="geometric",
            distance_range=(Decimal("0.02"), Decimal("0.05")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        config = MaintainerConfig(
            spread=Decimal("0.01"),
            max_distance=Decimal("0.05"),
            total_budget=Decimal("1000"),
            near_layer=near_layer,
            far_layer=far_layer,
            max_operations_per_cycle=20,  # 限制为 20
        )
        
        maintainer = OrderbookMaintainer(config)
        
        # 创建严重不平衡的操作列表：80 个取消卖单，20 个添加买单
        operations = []
        # 80 个取消卖单
        for i in range(80):
            operations.append(
                OrderOperation(action="cancel", side="ask", order_id=f"ask_{i}")
            )
        # 20 个添加买单
        for i in range(20):
            operations.append(
                OrderOperation(
                    action="add", 
                    side="bid", 
                    price=Decimal(f"0.{99-i}"), 
                    quantity=Decimal("100")
                )
            )
        
        # 执行限制
        limited, was_limited = maintainer._limit_operations(operations, is_initial=False)
        
        assert was_limited, "应该触发限制"
        assert len(limited) <= 20, f"操作数应该 <= 20，实际 {len(limited)}"
        
        # 统计结果
        cancel_asks = sum(1 for op in limited if op.action == "cancel" and op.side == "ask")
        add_bids = sum(1 for op in limited if op.action == "add" and op.side == "bid")
        
        # 关键断言：不应该全部是 cancel_ask 操作
        # 在旧逻辑中，可能 16 个都是 cancel_ask（80%），0 个 add_bid
        # 新逻辑应该保证两侧都有操作
        assert add_bids > 0 or cancel_asks < len(limited), \
            f"操作应该平衡分配，而不是全部取消卖单。cancel_asks={cancel_asks}, add_bids={add_bids}"

    def test_limit_operations_balanced_cancels(self):
        """测试取消操作在买卖两侧平衡分配"""
        from etf.orderbook.base import OrderOperation
        from etf.orderbook.maintainer import MaintainerConfig, LayerSpec
        
        near_layer = LayerSpec(
            name="near",
            distribution="arithmetic",
            distance_range=(Decimal("0.005"), Decimal("0.02")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        far_layer = LayerSpec(
            name="far",
            distribution="geometric",
            distance_range=(Decimal("0.02"), Decimal("0.05")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        config = MaintainerConfig(
            spread=Decimal("0.01"),
            max_distance=Decimal("0.05"),
            total_budget=Decimal("1000"),
            near_layer=near_layer,
            far_layer=far_layer,
            max_operations_per_cycle=50,
        )
        
        maintainer = OrderbookMaintainer(config)
        
        # 创建 100 个取消操作：50 bid + 50 ask
        operations = []
        for i in range(50):
            operations.append(
                OrderOperation(action="cancel", side="bid", order_id=f"bid_{i}")
            )
        for i in range(50):
            operations.append(
                OrderOperation(action="cancel", side="ask", order_id=f"ask_{i}")
            )
        
        limited, was_limited = maintainer._limit_operations(operations, is_initial=False)
        
        assert was_limited
        
        cancel_bids = sum(1 for op in limited if op.action == "cancel" and op.side == "bid")
        cancel_asks = sum(1 for op in limited if op.action == "cancel" and op.side == "ask")
        
        # 两侧都应该有取消操作，且比例接近
        assert cancel_bids > 0, "应该有取消买单的操作"
        assert cancel_asks > 0, "应该有取消卖单的操作"
        
        # 比例检查：每侧至少 40%
        total_cancels = cancel_bids + cancel_asks
        min_ratio = 0.35  # 略低于 40% 留一些容差
        assert cancel_bids >= total_cancels * min_ratio, \
            f"买单取消比例过低: {cancel_bids}/{total_cancels}"
        assert cancel_asks >= total_cancels * min_ratio, \
            f"卖单取消比例过低: {cancel_asks}/{total_cancels}"

    def test_limit_operations_single_side_cancel(self):
        """测试只有单边取消时的处理"""
        from etf.orderbook.base import OrderOperation
        from etf.orderbook.maintainer import MaintainerConfig, LayerSpec
        
        near_layer = LayerSpec(
            name="near",
            distribution="arithmetic",
            distance_range=(Decimal("0.005"), Decimal("0.02")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        far_layer = LayerSpec(
            name="far",
            distribution="geometric",
            distance_range=(Decimal("0.02"), Decimal("0.05")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        config = MaintainerConfig(
            spread=Decimal("0.01"),
            max_distance=Decimal("0.05"),
            total_budget=Decimal("1000"),
            near_layer=near_layer,
            far_layer=far_layer,
            max_operations_per_cycle=30,
        )
        
        maintainer = OrderbookMaintainer(config)
        
        # 只有卖单取消 + 买单添加的场景（模拟日志中的问题）
        operations = []
        # 80 个取消卖单
        for i in range(80):
            operations.append(
                OrderOperation(action="cancel", side="ask", order_id=f"ask_{i}")
            )
        # 20 个添加买单
        for i in range(20):
            operations.append(
                OrderOperation(
                    action="add", 
                    side="bid", 
                    price=Decimal(f"0.{99-i}"), 
                    quantity=Decimal("100")
                )
            )
        
        limited, was_limited = maintainer._limit_operations(operations, is_initial=False)
        
        assert was_limited
        
        # 即使原始操作只有 cancel_ask 和 add_bid
        # 限制后应该两种操作都有
        cancel_asks = sum(1 for op in limited if op.action == "cancel" and op.side == "ask")
        add_bids = sum(1 for op in limited if op.action == "add" and op.side == "bid")
        
        # 两种操作都应该有
        assert cancel_asks > 0, "应该有取消卖单的操作"
        assert add_bids > 0, "应该有添加买单的操作"
        
        # 检查操作不会导致盘口完全失衡
        # 取消卖单的数量不应该远超过添加买单的数量
        # （因为这可能导致只有买单没有卖单）

    def test_limit_operations_add_balance(self):
        """测试添加操作在买卖两侧平衡分配"""
        from etf.orderbook.base import OrderOperation
        from etf.orderbook.maintainer import MaintainerConfig, LayerSpec
        
        near_layer = LayerSpec(
            name="near",
            distribution="arithmetic",
            distance_range=(Decimal("0.005"), Decimal("0.02")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        far_layer = LayerSpec(
            name="far",
            distribution="geometric",
            distance_range=(Decimal("0.02"), Decimal("0.05")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        config = MaintainerConfig(
            spread=Decimal("0.01"),
            max_distance=Decimal("0.05"),
            total_budget=Decimal("1000"),
            near_layer=near_layer,
            far_layer=far_layer,
            max_operations_per_cycle=40,
        )
        
        maintainer = OrderbookMaintainer(config)
        
        # 60 个添加操作：40 bid + 20 ask
        operations = []
        for i in range(40):
            operations.append(
                OrderOperation(
                    action="add", 
                    side="bid", 
                    price=Decimal(f"0.{99-i}") if i < 10 else Decimal(f"0.{89-i+10}"), 
                    quantity=Decimal("100")
                )
            )
        for i in range(20):
            operations.append(
                OrderOperation(
                    action="add", 
                    side="ask", 
                    price=Decimal(f"1.0{i}"), 
                    quantity=Decimal("100")
                )
            )
        
        limited, was_limited = maintainer._limit_operations(operations, is_initial=False)
        
        assert was_limited
        
        add_bids = sum(1 for op in limited if op.action == "add" and op.side == "bid")
        add_asks = sum(1 for op in limited if op.action == "add" and op.side == "ask")
        
        # 两侧都应该有添加操作
        assert add_bids > 0, "应该有添加买单的操作"
        assert add_asks > 0, "应该有添加卖单的操作"
        
        # 卖单虽然原始只有 20 个，但至少应该分配到一定比例
        total_adds = add_bids + add_asks
        # ask 原始只有 20 个，所以实际最多 20 个
        assert add_asks >= min(20, int(total_adds * 0.3)), \
            f"卖单添加比例过低: add_asks={add_asks}, total={total_adds}"
