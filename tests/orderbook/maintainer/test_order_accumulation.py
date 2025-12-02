"""
订单累积和限制操作测试

覆盖场景：
1. 多周期订单累积测试
2. _limit_operations 截断 cancel 的测试
3. 大规模订单缩减测试
4. NAV 大幅变化导致完全重建测试
"""

import pytest
from decimal import Decimal
from typing import List

from etf.orderbook.base import OrderLevel, OrderOperation
from etf.orderbook.maintainer import (
    MaintainerConfig,
    LayerSpec,
    OrderbookMaintainer,
    CurrentOrderbook,
    ExistingOrder,
    MaintenanceResult,
)


@pytest.fixture
def production_like_config() -> MaintainerConfig:
    """模拟生产环境的配置"""
    near_layer = LayerSpec(
        name="near",
        distance_range=(Decimal("0"), Decimal("0.005")),
        order_count=50,  # 近盘口 50 个
        budget_ratio=Decimal("0.5"),
        distribution="arithmetic",
    )
    far_layer = LayerSpec(
        name="far",
        distance_range=(Decimal("0.005"), Decimal("0.10")),
        order_count=50,  # 远盘口 50 个
        budget_ratio=Decimal("0.5"),
        distribution="geometric",
    )
    return MaintainerConfig(
        spread=Decimal("0.008"),
        max_distance=Decimal("0.10"),
        total_budget=Decimal("10000"),
        near_layer=near_layer,
        far_layer=far_layer,
        price_precision=6,
        quantity_precision=4,
        min_price_change=Decimal("0.002"),
        max_operations_per_cycle=30,  # 关键：限制每周期操作数
    )


@pytest.fixture
def small_limit_config() -> MaintainerConfig:
    """小操作限制配置（用于测试截断逻辑）"""
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
    return MaintainerConfig(
        spread=Decimal("0.01"),
        max_distance=Decimal("0.05"),
        total_budget=Decimal("1000"),
        near_layer=near_layer,
        far_layer=far_layer,
        price_precision=4,
        quantity_precision=2,
        min_price_change=Decimal("0.001"),
        max_operations_per_cycle=10,  # 非常小的限制
    )


def create_existing_orders(
    count: int,
    base_price: Decimal,
    side: str,
    spread: Decimal = Decimal("0.001"),
) -> List[ExistingOrder]:
    """创建指定数量的现有订单"""
    orders = []
    for i in range(count):
        if side == "bid":
            price = base_price * (1 - spread * (i + 1))
        else:
            price = base_price * (1 + spread * (i + 1))
        
        orders.append(
            ExistingOrder(
                order_id=f"{side}_{i}",
                price=price,
                quantity=Decimal("100"),
                side=side,
            )
        )
    return orders


def simulate_execution(
    current: CurrentOrderbook,
    operations: List[OrderOperation],
    partial_cancel: bool = False,
) -> CurrentOrderbook:
    """
    模拟操作执行
    
    Args:
        current: 当前订单簿
        operations: 操作列表
        partial_cancel: 是否模拟部分 cancel 失败
    """
    new_bids = list(current.bids)
    new_asks = list(current.asks)
    
    order_counter = len(new_bids) + len(new_asks)
    
    for op in operations:
        if op.action == "add":
            order_counter += 1
            new_order = ExistingOrder(
                order_id=f"new_{order_counter}",
                price=op.price,
                quantity=op.quantity,
                side=op.side,
            )
            if op.side == "bid":
                new_bids.append(new_order)
            else:
                new_asks.append(new_order)
        
        elif op.action == "cancel":
            # 模拟部分失败：跳过某些 cancel
            if partial_cancel and order_counter % 3 == 0:
                continue
            
            if op.side == "bid":
                new_bids = [o for o in new_bids if o.order_id != op.order_id]
            else:
                new_asks = [o for o in new_asks if o.order_id != op.order_id]
    
    return CurrentOrderbook(bids=new_bids, asks=new_asks)


class TestOrderAccumulation:
    """订单累积测试"""

    def test_no_accumulation_over_cycles(
        self,
        production_like_config: MaintainerConfig,
    ):
        """测试多周期后订单不会无限累积"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.0")
        
        # 初始化
        maintainer.generate_initial(nav)
        current = CurrentOrderbook.empty()
        
        max_expected = production_like_config.total_orders_per_side * 2 * 2  # 目标的 2 倍
        
        # 运行 50 个周期
        for i in range(50):
            # 微小 NAV 变化
            nav = Decimal("1.0") * (1 + Decimal("0.002") * (i % 10))
            result = maintainer.maintain(current, nav)
            
            # 模拟执行
            current = simulate_execution(current, result.operations)
            
            # 关键断言：订单数不应超过预期上限
            total_orders = len(current.bids) + len(current.asks)
            assert total_orders <= max_expected, (
                f"周期 {i}: 订单数 {total_orders} 超过上限 {max_expected}"
            )

    def test_accumulation_with_partial_execution(
        self,
        production_like_config: MaintainerConfig,
    ):
        """测试部分执行失败时的订单累积"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        current = CurrentOrderbook.empty()
        
        max_expected = production_like_config.total_orders_per_side * 2 * 3  # 目标的 3 倍（更宽松）
        
        # 运行 30 个周期，模拟部分 cancel 失败
        for i in range(30):
            nav = Decimal("1.0") * (1 + Decimal("0.003") * (i % 5))
            result = maintainer.maintain(current, nav)
            
            # 模拟部分 cancel 失败
            current = simulate_execution(current, result.operations, partial_cancel=True)
            
            total_orders = len(current.bids) + len(current.asks)
            assert total_orders <= max_expected, (
                f"周期 {i}: 订单数 {total_orders} 超过上限 {max_expected}"
            )

    def test_recovery_from_high_order_count(
        self,
        production_like_config: MaintainerConfig,
    ):
        """测试从高订单数恢复"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建超量的现有订单（模拟累积后的状态）
        excessive_bids = create_existing_orders(150, nav, "bid")
        excessive_asks = create_existing_orders(150, nav, "ask")
        current = CurrentOrderbook(bids=excessive_bids, asks=excessive_asks)
        
        initial_count = current.total_orders  # 300
        
        # 运行 20 个周期
        for i in range(20):
            result = maintainer.maintain(current, nav)
            current = simulate_execution(current, result.operations)
        
        # 订单数应该显著减少
        final_count = current.total_orders
        target_count = production_like_config.total_orders_per_side * 2
        
        # 应该接近目标（允许 50% 误差）
        assert final_count < initial_count, "订单数应该减少"
        assert final_count < target_count * 1.5, (
            f"订单数 {final_count} 应接近目标 {target_count}"
        )


class TestLimitOperations:
    """_limit_operations 测试"""

    def test_cancel_not_completely_dropped(
        self,
        small_limit_config: MaintainerConfig,
    ):
        """测试 cancel 操作不会被完全丢弃"""
        maintainer = OrderbookMaintainer(small_limit_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建大量需要取消的订单
        old_bids = create_existing_orders(50, nav, "bid")
        old_asks = create_existing_orders(50, nav, "ask")
        current = CurrentOrderbook(bids=old_bids, asks=old_asks)
        
        # NAV 大幅变化，导致所有现有订单都需要取消
        new_nav = nav * Decimal("1.10")  # 10% 变化
        result = maintainer.maintain(current, new_nav)
        
        # 统计操作
        cancel_count = sum(1 for op in result.operations if op.action == "cancel")
        add_count = sum(1 for op in result.operations if op.action == "add")
        
        # 关键断言：cancel 不应为 0
        assert cancel_count > 0, (
            f"cancel 操作不应为 0，当前 add={add_count}, cancel={cancel_count}"
        )
        
        # cancel 应至少占 30%（根据新逻辑）
        if add_count + cancel_count > 0:
            cancel_ratio = cancel_count / (add_count + cancel_count)
            # 如果有很多 cancel 需求，至少应该有 20%
            if len(old_bids) + len(old_asks) > small_limit_config.max_operations_per_cycle:
                assert cancel_ratio >= 0.2, (
                    f"cancel 比例 {cancel_ratio:.1%} 过低"
                )

    def test_balanced_allocation(
        self,
        small_limit_config: MaintainerConfig,
    ):
        """测试 add 和 cancel 的平衡分配"""
        maintainer = OrderbookMaintainer(small_limit_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建需要部分更新的订单簿
        existing_bids = create_existing_orders(30, nav, "bid")
        existing_asks = create_existing_orders(30, nav, "ask")
        current = CurrentOrderbook(bids=existing_bids, asks=existing_asks)
        
        # 小幅 NAV 变化
        new_nav = nav * Decimal("1.02")
        result = maintainer.maintain(current, new_nav)
        
        # 操作应该被限制
        assert len(result.operations) <= small_limit_config.max_operations_per_cycle
        
        # 如果被限制了，应该有 cancel 操作
        if result.stats.operations_limited:
            cancel_count = sum(1 for op in result.operations if op.action == "cancel")
            # 不要求必须有 cancel（如果原始 cancel 很少），但如果有很多需要取消的，应该有
            total_existing = len(existing_bids) + len(existing_asks)
            if total_existing > small_limit_config.total_orders_per_side * 2:
                assert cancel_count > 0, "应该有 cancel 操作"


class TestLargeScaleReduction:
    """大规模订单缩减测试"""

    def test_shrink_large_orderbook(
        self,
        production_like_config: MaintainerConfig,
    ):
        """测试从大订单簿缩减到目标规模"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建超大订单簿（模拟 286 个订单）
        large_bids = create_existing_orders(143, nav, "bid")
        large_asks = create_existing_orders(143, nav, "ask")
        current = CurrentOrderbook(bids=large_bids, asks=large_asks)
        
        initial_count = current.total_orders  # 286
        target_per_side = production_like_config.total_orders_per_side
        
        result = maintainer.maintain(current, nav)
        
        # 应该生成 cancel 操作
        cancel_count = sum(1 for op in result.operations if op.action == "cancel")
        assert cancel_count > 0, (
            f"应该有 cancel 操作来减少订单数，当前 {initial_count} 个"
        )

    def test_gradual_reduction(
        self,
        production_like_config: MaintainerConfig,
    ):
        """测试逐步缩减订单"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建超大订单簿
        current = CurrentOrderbook(
            bids=create_existing_orders(200, nav, "bid"),
            asks=create_existing_orders(200, nav, "ask"),
        )
        
        initial_count = current.total_orders  # 400
        target_count = production_like_config.total_orders_per_side * 2
        
        # 运行多个周期
        counts = [initial_count]
        for _ in range(10):
            result = maintainer.maintain(current, nav)
            current = simulate_execution(current, result.operations)
            counts.append(current.total_orders)
        
        # 订单数应该逐步减少
        assert counts[-1] < counts[0], "订单数应该减少"
        
        # 检查是否有下降趋势
        decreasing_count = sum(1 for i in range(1, len(counts)) if counts[i] <= counts[i-1])
        assert decreasing_count >= len(counts) // 2, "应该有持续的下降趋势"


class TestNavShift:
    """NAV 大幅变化测试"""

    def test_large_nav_shift_generates_cancels(
        self,
        production_like_config: MaintainerConfig,
    ):
        """测试 NAV 大幅变化时生成足够的 cancel"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建基于旧 NAV 的订单
        old_bids = create_existing_orders(50, nav, "bid")
        old_asks = create_existing_orders(50, nav, "ask")
        current = CurrentOrderbook(bids=old_bids, asks=old_asks)
        
        # NAV 大幅变化 15%
        new_nav = nav * Decimal("1.15")
        result = maintainer.maintain(current, new_nav)
        
        # 复用率应该很低
        assert result.stats.reuse_ratio < 0.2, (
            f"大幅 NAV 变化后复用率应很低，当前 {result.stats.reuse_ratio:.1%}"
        )
        
        # 应该有 cancel 操作
        cancel_count = sum(1 for op in result.operations if op.action == "cancel")
        assert cancel_count > 0, "应该有 cancel 操作"

    def test_complete_rebuild_scenario(
        self,
        small_limit_config: MaintainerConfig,
    ):
        """测试完全重建场景"""
        maintainer = OrderbookMaintainer(small_limit_config)
        nav = Decimal("1.0")
        
        maintainer.generate_initial(nav)
        
        # 创建完全不匹配的订单（价格差距大）
        mismatched_bids = [
            ExistingOrder(
                order_id=f"old_bid_{i}",
                price=Decimal("0.5") + Decimal("0.01") * i,  # 价格在 0.5 附近
                quantity=Decimal("100"),
                side="bid",
            )
            for i in range(20)
        ]
        mismatched_asks = [
            ExistingOrder(
                order_id=f"old_ask_{i}",
                price=Decimal("1.5") + Decimal("0.01") * i,  # 价格在 1.5 附近
                quantity=Decimal("100"),
                side="ask",
            )
            for i in range(20)
        ]
        current = CurrentOrderbook(bids=mismatched_bids, asks=mismatched_asks)
        
        # 新 NAV 在 1.0 附近
        result = maintainer.maintain(current, nav)
        
        # 所有现有订单都应该被取消
        cancel_count = sum(1 for op in result.operations if op.action == "cancel")
        
        # 考虑到限制，至少应该有一些 cancel
        assert cancel_count > 0, "完全不匹配的订单应该被取消"


class TestRealisticScenarios:
    """真实场景测试"""

    def test_production_scenario_286_orders(
        self,
        production_like_config: MaintainerConfig,
    ):
        """模拟生产环境 286 个订单的场景"""
        maintainer = OrderbookMaintainer(production_like_config)
        nav = Decimal("1.697")  # 模拟实际 NAV
        
        maintainer.generate_initial(nav)
        
        # 模拟生产环境：286 个订单，价格分散
        bids = []
        asks = []
        for i in range(127):
            bids.append(
                ExistingOrder(
                    order_id=f"mm_bid_{i}",
                    price=nav * (1 - Decimal("0.001") * (i + 1)),
                    quantity=Decimal("100"),
                    side="bid",
                )
            )
        for i in range(159):
            asks.append(
                ExistingOrder(
                    order_id=f"mm_ask_{i}",
                    price=nav * (1 + Decimal("0.001") * (i + 1)),
                    quantity=Decimal("100"),
                    side="ask",
                )
            )
        
        current = CurrentOrderbook(bids=bids, asks=asks)
        
        # 微小 NAV 变化
        new_nav = nav * Decimal("1.001")
        result = maintainer.maintain(current, new_nav)
        
        add_count = sum(1 for op in result.operations if op.action == "add")
        cancel_count = sum(1 for op in result.operations if op.action == "cancel")
        
        # 关键：不应该是 +30 add, -0 cancel
        if current.total_orders > production_like_config.total_orders_per_side * 2:
            assert cancel_count > 0, (
                f"订单数 {current.total_orders} 超过目标时，"
                f"不应该只有 add ({add_count}) 没有 cancel ({cancel_count})"
            )
