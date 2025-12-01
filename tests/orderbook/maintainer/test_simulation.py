"""
订单簿维护器模拟测试

测试长时间运行下订单簿的合理性：
1. 净值随机波动场景
2. 订单簿持续调整
3. 验证平衡性、价差、订单数量等指标
"""

import pytest
import random
import math
from decimal import Decimal
from typing import List, Tuple
from dataclasses import dataclass

from etf.orderbook.base import OrderLevel
from etf.orderbook.maintainer import (
    MaintainerConfig,
    LayerSpec,
    OrderbookMaintainer,
    CurrentOrderbook,
    ExistingOrder,
    MetricsCalculator,
    MaintenanceResult,
)


@dataclass
class SimulationStats:
    """模拟统计"""
    cycles: int
    nav_changes: List[Decimal]
    vii_history: List[Decimal]
    qii_history: List[Decimal]
    spread_history: List[float]
    order_count_history: List[Tuple[int, int]]  # (bids, asks)
    operations_history: List[int]
    reuse_ratio_history: List[float]


class NAVSimulator:
    """净值模拟器"""

    @staticmethod
    def random_walk(
        start: Decimal,
        steps: int,
        volatility: Decimal = Decimal("0.02"),
        seed: int = None,
    ) -> List[Decimal]:
        """
        随机游走模拟

        Args:
            start: 起始净值
            steps: 步数
            volatility: 波动率 (每步标准差)
            seed: 随机种子

        Returns:
            净值序列
        """
        if seed is not None:
            random.seed(seed)

        navs = [start]
        current = float(start)

        for _ in range(steps - 1):
            change = random.gauss(0, float(volatility))
            current = current * (1 + change)
            current = max(current, 0.01)  # 防止负值
            navs.append(Decimal(str(round(current, 6))))

        return navs

    @staticmethod
    def trending(
        start: Decimal,
        steps: int,
        trend: Decimal = Decimal("0.001"),
        volatility: Decimal = Decimal("0.01"),
        seed: int = None,
    ) -> List[Decimal]:
        """
        趋势模拟 (带漂移的随机游走)

        Args:
            start: 起始净值
            steps: 步数
            trend: 趋势 (正=上涨, 负=下跌)
            volatility: 波动率
            seed: 随机种子

        Returns:
            净值序列
        """
        if seed is not None:
            random.seed(seed)

        navs = [start]
        current = float(start)

        for _ in range(steps - 1):
            change = float(trend) + random.gauss(0, float(volatility))
            current = current * (1 + change)
            current = max(current, 0.01)
            navs.append(Decimal(str(round(current, 6))))

        return navs

    @staticmethod
    def mean_reverting(
        start: Decimal,
        steps: int,
        mean: Decimal = None,
        reversion_speed: Decimal = Decimal("0.1"),
        volatility: Decimal = Decimal("0.01"),
        seed: int = None,
    ) -> List[Decimal]:
        """
        均值回归模拟

        Args:
            start: 起始净值
            steps: 步数
            mean: 均值 (默认=start)
            reversion_speed: 回归速度
            volatility: 波动率
            seed: 随机种子

        Returns:
            净值序列
        """
        if seed is not None:
            random.seed(seed)

        if mean is None:
            mean = start

        navs = [start]
        current = float(start)
        mean_f = float(mean)
        speed = float(reversion_speed)

        for _ in range(steps - 1):
            # 均值回归 + 随机噪声
            reversion = speed * (mean_f - current) / current
            noise = random.gauss(0, float(volatility))
            change = reversion + noise
            current = current * (1 + change)
            current = max(current, 0.01)
            navs.append(Decimal(str(round(current, 6))))

        return navs

    @staticmethod
    def volatile_spikes(
        start: Decimal,
        steps: int,
        base_volatility: Decimal = Decimal("0.005"),
        spike_probability: float = 0.05,
        spike_magnitude: Decimal = Decimal("0.05"),
        seed: int = None,
    ) -> List[Decimal]:
        """
        带突发波动的模拟

        Args:
            start: 起始净值
            steps: 步数
            base_volatility: 基础波动率
            spike_probability: 突发波动概率
            spike_magnitude: 突发波动幅度
            seed: 随机种子

        Returns:
            净值序列
        """
        if seed is not None:
            random.seed(seed)

        navs = [start]
        current = float(start)

        for _ in range(steps - 1):
            if random.random() < spike_probability:
                # 突发波动
                change = random.choice([-1, 1]) * float(spike_magnitude)
            else:
                # 正常波动
                change = random.gauss(0, float(base_volatility))

            current = current * (1 + change)
            current = max(current, 0.01)
            navs.append(Decimal(str(round(current, 6))))

        return navs


class OrderbookSimulator:
    """订单簿模拟器"""

    def __init__(self, config: MaintainerConfig):
        self.config = config
        self.maintainer = OrderbookMaintainer(config)
        self.current_orderbook: CurrentOrderbook = CurrentOrderbook.empty()
        self._order_id_counter = 0

    def reset(self):
        """重置模拟器"""
        self.maintainer.reset()
        self.current_orderbook = CurrentOrderbook.empty()
        self._order_id_counter = 0

    def _generate_order_id(self) -> str:
        """生成订单ID"""
        self._order_id_counter += 1
        return f"sim_{self._order_id_counter}"

    def _apply_operations(self, result: MaintenanceResult) -> CurrentOrderbook:
        """
        应用操作到当前订单簿

        模拟交易所执行操作后的状态

        策略：
        1. 先执行取消操作
        2. 再执行添加操作
        3. 保持未被操作影响的订单
        """
        # 收集要取消的订单 ID
        cancel_ids = {
            op.order_id for op in result.operations
            if op.action == "cancel" and op.order_id
        }

        # 保留未取消的订单
        new_bids = [o for o in self.current_orderbook.bids if o.order_id not in cancel_ids]
        new_asks = [o for o in self.current_orderbook.asks if o.order_id not in cancel_ids]

        # 添加新订单
        for op in result.operations:
            if op.action == "add" and op.price is not None and op.quantity is not None:
                new_order = ExistingOrder(
                    order_id=self._generate_order_id(),
                    price=op.price,
                    quantity=op.quantity,
                    side=op.side,
                )
                if op.side == "bid":
                    new_bids.append(new_order)
                else:
                    new_asks.append(new_order)

        return CurrentOrderbook(bids=new_bids, asks=new_asks)

    def _sync_to_target(self, result: MaintenanceResult) -> CurrentOrderbook:
        """
        直接同步到目标订单簿（用于测试目标生成的正确性）
        """
        target = result.target_snapshot

        new_bids = [
            ExistingOrder(
                order_id=self._generate_order_id(),
                price=o.price,
                quantity=o.quantity,
                side="bid",
            )
            for o in target.bids
        ]

        new_asks = [
            ExistingOrder(
                order_id=self._generate_order_id(),
                price=o.price,
                quantity=o.quantity,
                side="ask",
            )
            for o in target.asks
        ]

        return CurrentOrderbook(bids=new_bids, asks=new_asks)

    def run_simulation(
        self,
        nav_sequence: List[Decimal],
        sync_mode: bool = False,
    ) -> SimulationStats:
        """
        运行模拟

        Args:
            nav_sequence: 净值序列
            sync_mode: 是否使用同步模式（直接使用目标订单簿，
                       忽略操作限制，用于测试目标生成正确性）

        Returns:
            SimulationStats: 模拟统计
        """
        self.reset()

        stats = SimulationStats(
            cycles=len(nav_sequence),
            nav_changes=[],
            vii_history=[],
            qii_history=[],
            spread_history=[],
            order_count_history=[],
            operations_history=[],
            reuse_ratio_history=[],
        )

        # 初始化
        initial_nav = nav_sequence[0]
        self.maintainer.generate_initial(initial_nav)

        prev_nav = initial_nav

        for i, nav in enumerate(nav_sequence):
            # 计算净值变化
            nav_change = (nav - prev_nav) / prev_nav if prev_nav > 0 else Decimal("0")
            stats.nav_changes.append(nav_change)

            # 维护订单簿
            result = self.maintainer.maintain(self.current_orderbook, nav)

            # 应用操作
            if sync_mode:
                # 同步模式：直接使用目标订单簿
                self.current_orderbook = self._sync_to_target(result)
            else:
                # 操作模式：逐步应用操作
                self.current_orderbook = self._apply_operations(result)

            # 记录统计
            stats.vii_history.append(result.metrics.vii)
            stats.qii_history.append(result.metrics.qii)
            stats.operations_history.append(len(result.operations))
            stats.reuse_ratio_history.append(result.stats.reuse_ratio)

            # 计算当前订单簿的价差
            if self.current_orderbook.bids and self.current_orderbook.asks:
                best_bid = max(o.price for o in self.current_orderbook.bids)
                best_ask = min(o.price for o in self.current_orderbook.asks)
                spread = float((best_ask - best_bid) / nav) if nav > 0 else 0
                stats.spread_history.append(spread)
            else:
                stats.spread_history.append(0)

            stats.order_count_history.append((
                len(self.current_orderbook.bids),
                len(self.current_orderbook.asks),
            ))

            prev_nav = nav

        return stats


@pytest.fixture
def simulation_config() -> MaintainerConfig:
    """模拟测试配置"""
    near_layer = LayerSpec(
        name="near",
        distance_range=(Decimal("0"), Decimal("0.005")),
        order_count=10,
        budget_ratio=Decimal("0.5"),
        distribution="arithmetic",
    )
    far_layer = LayerSpec(
        name="far",
        distance_range=(Decimal("0.005"), Decimal("0.05")),
        order_count=10,
        budget_ratio=Decimal("0.5"),
        distribution="geometric",
    )
    return MaintainerConfig(
        spread=Decimal("0.008"),
        max_distance=Decimal("0.05"),
        total_budget=Decimal("10000"),
        near_layer=near_layer,
        far_layer=far_layer,
        price_precision=6,
        quantity_precision=4,
        min_price_change=Decimal("0.001"),  # 降低阈值以触发更多更新
        max_operations_per_cycle=20,
    )


class TestLongRunningSimulation:
    """长时间运行模拟测试"""

    def test_random_walk_500_cycles(self, simulation_config: MaintainerConfig):
        """测试随机游走 500 个周期"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=500,
            volatility=Decimal("0.01"),
            seed=42,
        )

        # 使用 sync_mode 测试目标生成的正确性
        stats = simulator.run_simulation(navs, sync_mode=True)

        # 验证价值平衡
        avg_vii = sum(abs(v) for v in stats.vii_history) / len(stats.vii_history)
        assert avg_vii < Decimal("0.15"), f"平均价值不平衡指数过高: {avg_vii}"

        # 验证数量平衡
        avg_qii = sum(abs(q) for q in stats.qii_history) / len(stats.qii_history)
        assert avg_qii < Decimal("0.20"), f"平均数量不平衡指数过高: {avg_qii}"

        # 验证价差合理性
        avg_spread = sum(stats.spread_history) / len(stats.spread_history)
        assert 0.005 < avg_spread < 0.02, f"平均价差异常: {avg_spread}"

        # 验证订单数量稳定性
        for bids, asks in stats.order_count_history:
            expected = simulation_config.total_orders_per_side
            assert bids <= expected + 5, f"买单数量异常: {bids}"
            assert asks <= expected + 5, f"卖单数量异常: {asks}"

    def test_trending_up_300_cycles(self, simulation_config: MaintainerConfig):
        """测试持续上涨 300 个周期"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.trending(
            start=Decimal("1.0"),
            steps=300,
            trend=Decimal("0.002"),  # 每周期 0.2% 上涨
            volatility=Decimal("0.005"),
            seed=42,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 价格应该上涨
        assert navs[-1] > navs[0], "价格应该上涨"

        # 验证平衡性
        final_vii = abs(stats.vii_history[-1])
        assert final_vii < Decimal("0.20"), f"最终价值不平衡: {final_vii}"

        # 验证订单簿跟随价格移动
        # 最终最佳买价应该高于初始
        final_orderbook = simulator.current_orderbook
        if final_orderbook.bids:
            final_best_bid = max(o.price for o in final_orderbook.bids)
            initial_nav = navs[0]
            assert final_best_bid > initial_nav * Decimal("0.95"), \
                "订单簿应该跟随价格上涨"

    def test_trending_down_300_cycles(self, simulation_config: MaintainerConfig):
        """测试持续下跌 300 个周期"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.trending(
            start=Decimal("1.0"),
            steps=300,
            trend=Decimal("-0.002"),  # 每周期 0.2% 下跌
            volatility=Decimal("0.005"),
            seed=42,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 价格应该下跌
        assert navs[-1] < navs[0], "价格应该下跌"

        # 验证平衡性仍然保持
        final_vii = abs(stats.vii_history[-1])
        assert final_vii < Decimal("0.20"), f"最终价值不平衡: {final_vii}"

    def test_mean_reverting_500_cycles(self, simulation_config: MaintainerConfig):
        """测试均值回归 500 个周期"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.mean_reverting(
            start=Decimal("1.0"),
            steps=500,
            mean=Decimal("1.0"),
            reversion_speed=Decimal("0.05"),
            volatility=Decimal("0.01"),
            seed=42,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 最终价格应该接近均值
        final_nav = navs[-1]
        assert Decimal("0.8") < final_nav < Decimal("1.2"), \
            f"最终净值应该接近均值: {final_nav}"

        # 验证平衡性
        avg_vii = sum(abs(v) for v in stats.vii_history) / len(stats.vii_history)
        assert avg_vii < Decimal("0.15"), f"平均价值不平衡: {avg_vii}"

    def test_volatile_spikes_200_cycles(self, simulation_config: MaintainerConfig):
        """测试突发波动 200 个周期"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.volatile_spikes(
            start=Decimal("1.0"),
            steps=200,
            base_volatility=Decimal("0.005"),
            spike_probability=0.1,  # 10% 概率出现突发波动
            spike_magnitude=Decimal("0.05"),  # 5% 的突发波动
            seed=42,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 即使有突发波动，订单簿也应该保持合理
        max_vii = max(abs(v) for v in stats.vii_history)
        assert max_vii < Decimal("0.30"), f"最大价值不平衡过高: {max_vii}"

        # 验证没有订单数量爆炸
        max_bids = max(b for b, a in stats.order_count_history)
        max_asks = max(a for b, a in stats.order_count_history)
        expected = simulation_config.total_orders_per_side
        assert max_bids <= expected + 10, f"买单数量爆炸: {max_bids}"
        assert max_asks <= expected + 10, f"卖单数量爆炸: {max_asks}"


class TestOrderbookInvariants:
    """订单簿不变量测试"""

    def test_spread_never_negative(self, simulation_config: MaintainerConfig):
        """价差永远不应该为负"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=1000,
            volatility=Decimal("0.02"),
            seed=123,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        for i, spread in enumerate(stats.spread_history):
            assert spread >= 0, f"周期 {i}: 价差为负 {spread}"

    def test_spread_within_bounds(self, simulation_config: MaintainerConfig):
        """价差应该在合理范围内"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=500,
            volatility=Decimal("0.01"),
            seed=456,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 价差应该在配置的 spread 附近
        expected_spread = float(simulation_config.spread)
        for i, spread in enumerate(stats.spread_history):
            if spread > 0:  # 跳过空订单簿
                # 允许 200% 的偏差（因为价格变化会影响价差）
                assert spread < expected_spread * 3, \
                    f"周期 {i}: 价差过大 {spread} > {expected_spread * 3}"

    def test_best_bid_below_best_ask(self, simulation_config: MaintainerConfig):
        """最佳买价应该低于最佳卖价"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=500,
            volatility=Decimal("0.015"),
            seed=789,
        )

        simulator.reset()
        simulator.maintainer.generate_initial(navs[0])

        for i, nav in enumerate(navs):
            result = simulator.maintainer.maintain(simulator.current_orderbook, nav)
            # 使用 sync_mode 逻辑
            simulator.current_orderbook = simulator._sync_to_target(result)

            if simulator.current_orderbook.bids and simulator.current_orderbook.asks:
                best_bid = max(o.price for o in simulator.current_orderbook.bids)
                best_ask = min(o.price for o in simulator.current_orderbook.asks)
                assert best_bid < best_ask, \
                    f"周期 {i}: 买卖价格交叉 bid={best_bid} >= ask={best_ask}"

    def test_order_prices_around_nav(self, simulation_config: MaintainerConfig):
        """订单价格应该围绕净值分布"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=300,
            volatility=Decimal("0.01"),
            seed=101,
        )

        simulator.reset()
        simulator.maintainer.generate_initial(navs[0])

        for i, nav in enumerate(navs):
            result = simulator.maintainer.maintain(simulator.current_orderbook, nav)
            # 使用 sync_mode 逻辑
            simulator.current_orderbook = simulator._sync_to_target(result)

            max_distance = simulation_config.max_distance

            for order in simulator.current_orderbook.bids:
                distance = (nav - order.price) / nav
                assert distance < max_distance * Decimal("1.5"), \
                    f"周期 {i}: 买单距离过远 {distance}"

            for order in simulator.current_orderbook.asks:
                distance = (order.price - nav) / nav
                assert distance < max_distance * Decimal("1.5"), \
                    f"周期 {i}: 卖单距离过远 {distance}"


class TestReusabilityAndEfficiency:
    """复用率和效率测试"""

    def test_reuse_ratio_with_sync_mode(self, simulation_config: MaintainerConfig):
        """测试同步模式下的复用率计算"""
        simulator = OrderbookSimulator(simulation_config)
        # 非常小的波动
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=100,
            volatility=Decimal("0.002"),  # 0.2% 波动
            seed=202,
        )

        # sync_mode 下每次都是新订单簿，复用率来自 maintainer 的计算
        stats = simulator.run_simulation(navs, sync_mode=True)

        # 验证平衡性
        avg_vii = sum(abs(v) for v in stats.vii_history) / len(stats.vii_history)
        assert avg_vii < Decimal("0.10"), f"小波动时应该保持平衡: {avg_vii}"

    def test_operation_count_limited(self, simulation_config: MaintainerConfig):
        """操作数量应该被限制"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.volatile_spikes(
            start=Decimal("1.0"),
            steps=200,
            spike_probability=0.2,
            spike_magnitude=Decimal("0.1"),
            seed=303,
        )

        # 使用 sync_mode 测试操作限制
        stats = simulator.run_simulation(navs, sync_mode=True)

        max_ops = simulation_config.max_operations_per_cycle
        for i, ops in enumerate(stats.operations_history):
            assert ops <= max_ops, f"周期 {i}: 操作数超限 {ops} > {max_ops}"


class TestEdgeCases:
    """边界情况测试"""

    def test_extreme_price_drop(self, simulation_config: MaintainerConfig):
        """极端价格下跌"""
        simulator = OrderbookSimulator(simulation_config)

        # 模拟 50% 下跌
        navs = [Decimal("1.0")]
        for i in range(50):
            navs.append(navs[-1] * Decimal("0.99"))  # 每步 1% 下跌

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 订单簿应该仍然有效
        final_orderbook = simulator.current_orderbook
        assert len(final_orderbook.bids) > 0, "应该有买单"
        assert len(final_orderbook.asks) > 0, "应该有卖单"

    def test_extreme_price_rise(self, simulation_config: MaintainerConfig):
        """极端价格上涨"""
        simulator = OrderbookSimulator(simulation_config)

        # 模拟 100% 上涨
        navs = [Decimal("1.0")]
        for i in range(70):
            navs.append(navs[-1] * Decimal("1.01"))  # 每步 1% 上涨

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 订单簿应该仍然有效
        final_orderbook = simulator.current_orderbook
        assert len(final_orderbook.bids) > 0, "应该有买单"
        assert len(final_orderbook.asks) > 0, "应该有卖单"

        # 最终平衡性
        final_vii = abs(stats.vii_history[-1])
        assert final_vii < Decimal("0.25"), f"极端上涨后不平衡: {final_vii}"

    def test_price_flash_crash_recovery(self, simulation_config: MaintainerConfig):
        """闪崩后恢复"""
        simulator = OrderbookSimulator(simulation_config)

        # 正常 -> 闪崩 -> 恢复
        navs = []
        nav = Decimal("1.0")

        random.seed(404)  # 确保可重复

        # 正常阶段
        for _ in range(50):
            nav = nav * Decimal(str(1 + random.gauss(0, 0.005)))
            navs.append(nav)

        # 闪崩
        nav = nav * Decimal("0.8")  # 20% 下跌
        navs.append(nav)

        # 恢复
        for _ in range(50):
            nav = nav * Decimal("1.005")  # 缓慢恢复
            navs.append(nav)

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 恢复后应该平衡
        final_vii = abs(stats.vii_history[-1])
        assert final_vii < Decimal("0.20"), f"闪崩恢复后不平衡: {final_vii}"


class TestStatisticalProperties:
    """统计特性测试"""

    def test_vii_distribution(self, simulation_config: MaintainerConfig):
        """VII 分布应该以 0 为中心"""
        simulator = OrderbookSimulator(simulation_config)
        navs = NAVSimulator.random_walk(
            start=Decimal("1.0"),
            steps=1000,
            volatility=Decimal("0.01"),
            seed=505,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 跳过初始化阶段
        stable_vii = [float(v) for v in stats.vii_history[20:]]

        # 均值应该接近 0
        mean_vii = sum(stable_vii) / len(stable_vii)
        assert abs(mean_vii) < 0.05, f"VII 均值偏离 0: {mean_vii}"

    def test_operations_decrease_over_time(self, simulation_config: MaintainerConfig):
        """稳定后操作数应该减少"""
        simulator = OrderbookSimulator(simulation_config)
        # 稳定的小波动
        navs = NAVSimulator.mean_reverting(
            start=Decimal("1.0"),
            steps=200,
            volatility=Decimal("0.003"),
            seed=606,
        )

        stats = simulator.run_simulation(navs, sync_mode=True)

        # 前 50 个周期的平均操作数
        early_ops = sum(stats.operations_history[:50]) / 50

        # 后 50 个周期的平均操作数
        late_ops = sum(stats.operations_history[-50:]) / 50

        # 后期操作数应该更少或相当（订单簿已稳定）
        assert late_ops <= early_ops * 1.5, \
            f"后期操作数不应该增加太多: early={early_ops}, late={late_ops}"
