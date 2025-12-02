"""
订单簿维护器大规模压力测试

测试100万次以上净值波动和订单簿调整，验证长期稳定性

注意：
- 百万级测试标记为 @pytest.mark.slow，默认跳过
- 运行慢速测试: pytest -m slow --timeout=600
- 千万级测试标记为 @pytest.mark.stress，需要更长时间
"""

import pytest
import random
import time
from decimal import Decimal
from typing import List, Tuple, Dict, Any
from dataclasses import dataclass, field

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


# 跳过慢速测试的标记
pytestmark = [
    pytest.mark.skipif(
        not pytest.config.getoption("--runslow", default=False) if hasattr(pytest, 'config') else True,
        reason="需要 --runslow 选项运行慢速测试"
    ) if False else pytest.mark.filterwarnings("ignore"),  # 保持测试启用但需要足够超时
]


@dataclass
class StressTestStats:
    """压力测试统计"""

    total_cycles: int = 0
    total_time_seconds: float = 0.0

    # 性能统计
    avg_cycle_time_ms: float = 0.0
    max_cycle_time_ms: float = 0.0
    min_cycle_time_ms: float = float("inf")

    # 平衡性统计
    avg_vii: float = 0.0
    max_vii: float = 0.0
    vii_violations: int = 0  # VII > 0.2 的次数

    avg_qii: float = 0.0
    max_qii: float = 0.0

    # 价差统计
    avg_spread: float = 0.0
    max_spread: float = 0.0
    min_spread: float = float("inf")
    negative_spread_count: int = 0

    # 订单数量统计
    order_count_violations: int = 0
    max_bid_count: int = 0
    max_ask_count: int = 0

    # 价格交叉统计
    price_cross_count: int = 0

    # 净值统计
    start_nav: Decimal = Decimal("0")
    end_nav: Decimal = Decimal("0")
    max_nav: Decimal = Decimal("0")
    min_nav: Decimal = Decimal("inf")
    total_nav_changes: int = 0

    # 采样数据（用于详细分析）
    sampled_vii: List[float] = field(default_factory=list)
    sampled_spreads: List[float] = field(default_factory=list)

    def summary(self) -> str:
        """生成摘要报告"""
        return f"""
========== 压力测试报告 ==========
总周期数: {self.total_cycles:,}
总耗时: {self.total_time_seconds:.2f}秒
平均每周期: {self.avg_cycle_time_ms:.4f}ms
最大周期耗时: {self.max_cycle_time_ms:.4f}ms

--- 平衡性 ---
平均VII: {self.avg_vii:.6f}
最大VII: {self.max_vii:.6f}
VII违规次数 (>0.2): {self.vii_violations}
平均QII: {self.avg_qii:.6f}
最大QII: {self.max_qii:.6f}

--- 价差 ---
平均价差: {self.avg_spread:.6f}
最大价差: {self.max_spread:.6f}
最小价差: {self.min_spread:.6f}
负价差次数: {self.negative_spread_count}

--- 订单数量 ---
订单数违规次数: {self.order_count_violations}
最大买单数: {self.max_bid_count}
最大卖单数: {self.max_ask_count}

--- 价格交叉 ---
价格交叉次数: {self.price_cross_count}

--- 净值 ---
起始净值: {self.start_nav}
结束净值: {self.end_nav}
最高净值: {self.max_nav}
最低净值: {self.min_nav}
净值变化次数: {self.total_nav_changes}
=====================================
"""


class HighPerformanceNAVGenerator:
    """高性能净值生成器（内存优化）"""

    def __init__(self, seed: int = None):
        if seed is not None:
            random.seed(seed)
        self._rng = random.Random(seed)
        self._mean_target = 1.0  # 用于均值回归

    def generate_batch(
        self,
        start: float,
        batch_size: int,
        volatility: float = 0.01,
        trend: float = 0.0,
    ) -> List[Decimal]:
        """
        批量生成净值 - 随机游走/趋势

        Args:
            start: 起始净值
            batch_size: 批量大小
            volatility: 波动率
            trend: 趋势（正=上涨，负=下跌）

        Returns:
            净值列表
        """
        navs = []
        current = start

        for _ in range(batch_size):
            change = trend + self._rng.gauss(0, volatility)
            current = current * (1 + change)
            current = max(current, 0.001)  # 防止过小
            navs.append(Decimal(str(round(current, 6))))

        return navs

    def generate_mean_reverting_batch(
        self,
        start: float,
        batch_size: int,
        mean: float = 1.0,
        reversion_speed: float = 0.05,
        volatility: float = 0.01,
    ) -> List[Decimal]:
        """
        批量生成净值 - 均值回归

        Args:
            start: 起始净值
            batch_size: 批量大小
            mean: 回归目标均值
            reversion_speed: 回归速度 (0-1)
            volatility: 波动率

        Returns:
            净值列表
        """
        navs = []
        current = start

        for _ in range(batch_size):
            # 均值回归力 + 随机噪声
            reversion = reversion_speed * (mean - current) / current if current > 0 else 0
            noise = self._rng.gauss(0, volatility)
            change = reversion + noise
            current = current * (1 + change)
            current = max(current, 0.001)
            navs.append(Decimal(str(round(current, 6))))

        return navs

    def generate_volatile_spikes_batch(
        self,
        start: float,
        batch_size: int,
        base_volatility: float = 0.005,
        spike_probability: float = 0.05,
        spike_magnitude: float = 0.05,
    ) -> List[Decimal]:
        """
        批量生成净值 - 带突发波动

        Args:
            start: 起始净值
            batch_size: 批量大小
            base_volatility: 基础波动率
            spike_probability: 突发波动概率
            spike_magnitude: 突发波动幅度

        Returns:
            净值列表
        """
        navs = []
        current = start

        for _ in range(batch_size):
            if self._rng.random() < spike_probability:
                # 突发波动（随机方向）
                change = self._rng.choice([-1, 1]) * spike_magnitude
            else:
                # 正常波动
                change = self._rng.gauss(0, base_volatility)

            current = current * (1 + change)
            current = max(current, 0.001)
            navs.append(Decimal(str(round(current, 6))))

        return navs

    def generate_flash_crash_batch(
        self,
        start: float,
        batch_size: int,
        crash_probability: float = 0.0001,
        crash_magnitude: float = 0.2,
        recovery_speed: float = 0.01,
        base_volatility: float = 0.005,
    ) -> List[Decimal]:
        """
        批量生成净值 - 闪崩与恢复

        Args:
            start: 起始净值
            batch_size: 批量大小
            crash_probability: 闪崩概率 (每步)
            crash_magnitude: 闪崩幅度 (如0.2表示20%下跌)
            recovery_speed: 恢复速度
            base_volatility: 基础波动率

        Returns:
            净值列表
        """
        navs = []
        current = start
        pre_crash_level = start
        in_recovery = False

        for _ in range(batch_size):
            if not in_recovery and self._rng.random() < crash_probability:
                # 触发闪崩
                pre_crash_level = current
                change = -crash_magnitude
                in_recovery = True
            elif in_recovery:
                # 恢复阶段
                recovery_target = pre_crash_level * 0.95  # 恢复到崩前95%
                if current < recovery_target:
                    change = recovery_speed + self._rng.gauss(0, base_volatility * 0.5)
                else:
                    in_recovery = False
                    change = self._rng.gauss(0, base_volatility)
            else:
                # 正常波动
                change = self._rng.gauss(0, base_volatility)

            current = current * (1 + change)
            current = max(current, 0.001)
            navs.append(Decimal(str(round(current, 6))))

        return navs


class StressTestSimulator:
    """压力测试模拟器"""

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
        return f"s_{self._order_id_counter}"

    def _sync_to_target(self, result: MaintenanceResult) -> CurrentOrderbook:
        """直接同步到目标订单簿（仅用于指标计算测试）"""
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

    def _execute_operations(self, result: MaintenanceResult) -> CurrentOrderbook:
        """
        模拟真实执行操作（用于订单累积测试）
        
        根据 result.operations 实际执行 add/cancel，
        而不是直接同步到目标订单簿。
        """
        new_bids = list(self.current_orderbook.bids)
        new_asks = list(self.current_orderbook.asks)
        
        # 构建 order_id 索引
        bid_ids = {o.order_id for o in new_bids}
        ask_ids = {o.order_id for o in new_asks}
        
        for op in result.operations:
            if op.action == "add":
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
            
            elif op.action == "cancel":
                if op.side == "bid" and op.order_id in bid_ids:
                    new_bids = [o for o in new_bids if o.order_id != op.order_id]
                    bid_ids.discard(op.order_id)
                elif op.side == "ask" and op.order_id in ask_ids:
                    new_asks = [o for o in new_asks if o.order_id != op.order_id]
                    ask_ids.discard(op.order_id)
        
        return CurrentOrderbook(bids=new_bids, asks=new_asks)

    def run_stress_test(
        self,
        total_cycles: int,
        batch_size: int = 10000,
        volatility: float = 0.01,
        trend: float = 0.0,
        seed: int = 42,
        sample_interval: int = 10000,
        progress_interval: int = 100000,
    ) -> StressTestStats:
        """
        运行压力测试

        Args:
            total_cycles: 总周期数（如 1_000_000）
            batch_size: 批量生成净值大小
            volatility: 波动率
            trend: 趋势
            seed: 随机种子
            sample_interval: 采样间隔（每N周期采样一次）
            progress_interval: 进度输出间隔

        Returns:
            StressTestStats: 统计结果
        """
        self.reset()

        stats = StressTestStats()
        stats.total_cycles = total_cycles

        nav_generator = HighPerformanceNAVGenerator(seed)
        expected_orders = self.config.total_orders_per_side

        # 初始化
        start_nav = Decimal("1.0")
        stats.start_nav = start_nav
        stats.min_nav = start_nav
        stats.max_nav = start_nav
        self.maintainer.generate_initial(start_nav)

        current_nav = float(start_nav)
        prev_nav = current_nav

        # 累计统计
        total_vii = 0.0
        total_qii = 0.0
        total_spread = 0.0
        total_cycle_time = 0.0
        spread_count = 0

        start_time = time.perf_counter()
        processed = 0

        while processed < total_cycles:
            # 批量生成净值
            remaining = total_cycles - processed
            current_batch_size = min(batch_size, remaining)

            navs = nav_generator.generate_batch(
                start=current_nav,
                batch_size=current_batch_size,
                volatility=volatility,
                trend=trend,
            )

            for nav in navs:
                cycle_start = time.perf_counter()

                # 更新净值统计
                if nav > stats.max_nav:
                    stats.max_nav = nav
                if nav < stats.min_nav:
                    stats.min_nav = nav

                # 检查净值变化
                nav_float = float(nav)
                if abs(nav_float - prev_nav) / prev_nav > 0.001:
                    stats.total_nav_changes += 1

                # 维护订单簿
                result = self.maintainer.maintain(self.current_orderbook, nav)
                self.current_orderbook = self._sync_to_target(result)

                cycle_time = (time.perf_counter() - cycle_start) * 1000  # ms

                # 更新性能统计
                total_cycle_time += cycle_time
                if cycle_time > stats.max_cycle_time_ms:
                    stats.max_cycle_time_ms = cycle_time
                if cycle_time < stats.min_cycle_time_ms:
                    stats.min_cycle_time_ms = cycle_time

                # 更新平衡性统计
                vii = float(abs(result.metrics.vii))
                qii = float(abs(result.metrics.qii))
                total_vii += vii
                total_qii += qii

                if vii > stats.max_vii:
                    stats.max_vii = vii
                if qii > stats.max_qii:
                    stats.max_qii = qii
                if vii > 0.2:
                    stats.vii_violations += 1

                # 更新价差统计
                if self.current_orderbook.bids and self.current_orderbook.asks:
                    best_bid = max(o.price for o in self.current_orderbook.bids)
                    best_ask = min(o.price for o in self.current_orderbook.asks)

                    if best_bid >= best_ask:
                        stats.price_cross_count += 1

                    spread = float((best_ask - best_bid) / nav)
                    total_spread += spread
                    spread_count += 1

                    if spread > stats.max_spread:
                        stats.max_spread = spread
                    if spread < stats.min_spread:
                        stats.min_spread = spread
                    if spread < 0:
                        stats.negative_spread_count += 1

                # 更新订单数量统计
                bid_count = len(self.current_orderbook.bids)
                ask_count = len(self.current_orderbook.asks)

                if bid_count > stats.max_bid_count:
                    stats.max_bid_count = bid_count
                if ask_count > stats.max_ask_count:
                    stats.max_ask_count = ask_count

                if bid_count > expected_orders + 5 or ask_count > expected_orders + 5:
                    stats.order_count_violations += 1

                # 采样
                if processed % sample_interval == 0:
                    stats.sampled_vii.append(vii)
                    if spread_count > 0:
                        stats.sampled_spreads.append(spread)

                prev_nav = nav_float
                current_nav = nav_float
                processed += 1

            # 进度输出
            if processed % progress_interval == 0:
                elapsed = time.perf_counter() - start_time
                rate = processed / elapsed
                eta = (total_cycles - processed) / rate if rate > 0 else 0
                print(
                    f"进度: {processed:,}/{total_cycles:,} "
                    f"({100*processed/total_cycles:.1f}%) "
                    f"速率: {rate:,.0f}/s "
                    f"预计剩余: {eta:.1f}s"
                )

        # 计算最终统计
        end_time = time.perf_counter()
        stats.total_time_seconds = end_time - start_time
        stats.avg_cycle_time_ms = total_cycle_time / total_cycles
        stats.avg_vii = total_vii / total_cycles
        stats.avg_qii = total_qii / total_cycles
        stats.avg_spread = total_spread / spread_count if spread_count > 0 else 0
        stats.end_nav = Decimal(str(round(current_nav, 6)))

        return stats

    def run_mean_reverting_test(
        self,
        total_cycles: int,
        batch_size: int = 10000,
        mean: float = 1.0,
        reversion_speed: float = 0.05,
        volatility: float = 0.01,
        seed: int = 42,
        sample_interval: int = 10000,
        progress_interval: int = 100000,
    ) -> StressTestStats:
        """运行均值回归压力测试"""
        self.reset()
        stats = StressTestStats()
        stats.total_cycles = total_cycles

        nav_generator = HighPerformanceNAVGenerator(seed)
        expected_orders = self.config.total_orders_per_side

        start_nav = Decimal("1.0")
        stats.start_nav = start_nav
        stats.min_nav = start_nav
        stats.max_nav = start_nav
        self.maintainer.generate_initial(start_nav)

        current_nav = float(start_nav)
        prev_nav = current_nav

        total_vii = 0.0
        total_qii = 0.0
        total_spread = 0.0
        total_cycle_time = 0.0
        spread_count = 0

        start_time = time.perf_counter()
        processed = 0

        while processed < total_cycles:
            remaining = total_cycles - processed
            current_batch_size = min(batch_size, remaining)

            navs = nav_generator.generate_mean_reverting_batch(
                start=current_nav,
                batch_size=current_batch_size,
                mean=mean,
                reversion_speed=reversion_speed,
                volatility=volatility,
            )

            for nav in navs:
                cycle_start = time.perf_counter()

                if nav > stats.max_nav:
                    stats.max_nav = nav
                if nav < stats.min_nav:
                    stats.min_nav = nav

                nav_float = float(nav)
                if abs(nav_float - prev_nav) / prev_nav > 0.001:
                    stats.total_nav_changes += 1

                result = self.maintainer.maintain(self.current_orderbook, nav)
                self.current_orderbook = self._sync_to_target(result)

                cycle_time = (time.perf_counter() - cycle_start) * 1000

                total_cycle_time += cycle_time
                if cycle_time > stats.max_cycle_time_ms:
                    stats.max_cycle_time_ms = cycle_time
                if cycle_time < stats.min_cycle_time_ms:
                    stats.min_cycle_time_ms = cycle_time

                vii = float(abs(result.metrics.vii))
                qii = float(abs(result.metrics.qii))
                total_vii += vii
                total_qii += qii

                if vii > stats.max_vii:
                    stats.max_vii = vii
                if qii > stats.max_qii:
                    stats.max_qii = qii
                if vii > 0.2:
                    stats.vii_violations += 1

                if self.current_orderbook.bids and self.current_orderbook.asks:
                    best_bid = max(o.price for o in self.current_orderbook.bids)
                    best_ask = min(o.price for o in self.current_orderbook.asks)

                    if best_bid >= best_ask:
                        stats.price_cross_count += 1

                    spread = float((best_ask - best_bid) / nav)
                    total_spread += spread
                    spread_count += 1

                    if spread > stats.max_spread:
                        stats.max_spread = spread
                    if spread < stats.min_spread:
                        stats.min_spread = spread
                    if spread < 0:
                        stats.negative_spread_count += 1

                bid_count = len(self.current_orderbook.bids)
                ask_count = len(self.current_orderbook.asks)

                if bid_count > stats.max_bid_count:
                    stats.max_bid_count = bid_count
                if ask_count > stats.max_ask_count:
                    stats.max_ask_count = ask_count

                if bid_count > expected_orders + 5 or ask_count > expected_orders + 5:
                    stats.order_count_violations += 1

                if processed % sample_interval == 0:
                    stats.sampled_vii.append(vii)
                    if spread_count > 0:
                        stats.sampled_spreads.append(spread)

                prev_nav = nav_float
                current_nav = nav_float
                processed += 1

            if processed % progress_interval == 0:
                elapsed = time.perf_counter() - start_time
                rate = processed / elapsed
                eta = (total_cycles - processed) / rate if rate > 0 else 0
                print(f"均值回归: {processed:,}/{total_cycles:,} ({100*processed/total_cycles:.1f}%) 速率: {rate:,.0f}/s")

        end_time = time.perf_counter()
        stats.total_time_seconds = end_time - start_time
        stats.avg_cycle_time_ms = total_cycle_time / total_cycles
        stats.avg_vii = total_vii / total_cycles
        stats.avg_qii = total_qii / total_cycles
        stats.avg_spread = total_spread / spread_count if spread_count > 0 else 0
        stats.end_nav = Decimal(str(round(current_nav, 6)))

        return stats

    def run_volatile_spikes_test(
        self,
        total_cycles: int,
        batch_size: int = 10000,
        base_volatility: float = 0.005,
        spike_probability: float = 0.05,
        spike_magnitude: float = 0.05,
        seed: int = 42,
        sample_interval: int = 10000,
        progress_interval: int = 100000,
    ) -> StressTestStats:
        """运行突发波动压力测试"""
        self.reset()
        stats = StressTestStats()
        stats.total_cycles = total_cycles

        nav_generator = HighPerformanceNAVGenerator(seed)
        expected_orders = self.config.total_orders_per_side

        start_nav = Decimal("1.0")
        stats.start_nav = start_nav
        stats.min_nav = start_nav
        stats.max_nav = start_nav
        self.maintainer.generate_initial(start_nav)

        current_nav = float(start_nav)
        prev_nav = current_nav

        total_vii = 0.0
        total_qii = 0.0
        total_spread = 0.0
        total_cycle_time = 0.0
        spread_count = 0

        start_time = time.perf_counter()
        processed = 0

        while processed < total_cycles:
            remaining = total_cycles - processed
            current_batch_size = min(batch_size, remaining)

            navs = nav_generator.generate_volatile_spikes_batch(
                start=current_nav,
                batch_size=current_batch_size,
                base_volatility=base_volatility,
                spike_probability=spike_probability,
                spike_magnitude=spike_magnitude,
            )

            for nav in navs:
                cycle_start = time.perf_counter()

                if nav > stats.max_nav:
                    stats.max_nav = nav
                if nav < stats.min_nav:
                    stats.min_nav = nav

                nav_float = float(nav)
                if abs(nav_float - prev_nav) / prev_nav > 0.001:
                    stats.total_nav_changes += 1

                result = self.maintainer.maintain(self.current_orderbook, nav)
                self.current_orderbook = self._sync_to_target(result)

                cycle_time = (time.perf_counter() - cycle_start) * 1000

                total_cycle_time += cycle_time
                if cycle_time > stats.max_cycle_time_ms:
                    stats.max_cycle_time_ms = cycle_time
                if cycle_time < stats.min_cycle_time_ms:
                    stats.min_cycle_time_ms = cycle_time

                vii = float(abs(result.metrics.vii))
                qii = float(abs(result.metrics.qii))
                total_vii += vii
                total_qii += qii

                if vii > stats.max_vii:
                    stats.max_vii = vii
                if qii > stats.max_qii:
                    stats.max_qii = qii
                if vii > 0.2:
                    stats.vii_violations += 1

                if self.current_orderbook.bids and self.current_orderbook.asks:
                    best_bid = max(o.price for o in self.current_orderbook.bids)
                    best_ask = min(o.price for o in self.current_orderbook.asks)

                    if best_bid >= best_ask:
                        stats.price_cross_count += 1

                    spread = float((best_ask - best_bid) / nav)
                    total_spread += spread
                    spread_count += 1

                    if spread > stats.max_spread:
                        stats.max_spread = spread
                    if spread < stats.min_spread:
                        stats.min_spread = spread
                    if spread < 0:
                        stats.negative_spread_count += 1

                bid_count = len(self.current_orderbook.bids)
                ask_count = len(self.current_orderbook.asks)

                if bid_count > stats.max_bid_count:
                    stats.max_bid_count = bid_count
                if ask_count > stats.max_ask_count:
                    stats.max_ask_count = ask_count

                if bid_count > expected_orders + 5 or ask_count > expected_orders + 5:
                    stats.order_count_violations += 1

                if processed % sample_interval == 0:
                    stats.sampled_vii.append(vii)
                    if spread_count > 0:
                        stats.sampled_spreads.append(spread)

                prev_nav = nav_float
                current_nav = nav_float
                processed += 1

            if processed % progress_interval == 0:
                elapsed = time.perf_counter() - start_time
                rate = processed / elapsed
                eta = (total_cycles - processed) / rate if rate > 0 else 0
                print(f"突发波动: {processed:,}/{total_cycles:,} ({100*processed/total_cycles:.1f}%) 速率: {rate:,.0f}/s")

        end_time = time.perf_counter()
        stats.total_time_seconds = end_time - start_time
        stats.avg_cycle_time_ms = total_cycle_time / total_cycles
        stats.avg_vii = total_vii / total_cycles
        stats.avg_qii = total_qii / total_cycles
        stats.avg_spread = total_spread / spread_count if spread_count > 0 else 0
        stats.end_nav = Decimal(str(round(current_nav, 6)))

        return stats

    def run_flash_crash_test(
        self,
        total_cycles: int,
        batch_size: int = 10000,
        crash_probability: float = 0.0001,
        crash_magnitude: float = 0.2,
        recovery_speed: float = 0.01,
        base_volatility: float = 0.005,
        seed: int = 42,
        sample_interval: int = 10000,
        progress_interval: int = 100000,
    ) -> StressTestStats:
        """运行闪崩恢复压力测试"""
        self.reset()
        stats = StressTestStats()
        stats.total_cycles = total_cycles

        nav_generator = HighPerformanceNAVGenerator(seed)
        expected_orders = self.config.total_orders_per_side

        start_nav = Decimal("1.0")
        stats.start_nav = start_nav
        stats.min_nav = start_nav
        stats.max_nav = start_nav
        self.maintainer.generate_initial(start_nav)

        current_nav = float(start_nav)
        prev_nav = current_nav

        total_vii = 0.0
        total_qii = 0.0
        total_spread = 0.0
        total_cycle_time = 0.0
        spread_count = 0

        start_time = time.perf_counter()
        processed = 0

        while processed < total_cycles:
            remaining = total_cycles - processed
            current_batch_size = min(batch_size, remaining)

            navs = nav_generator.generate_flash_crash_batch(
                start=current_nav,
                batch_size=current_batch_size,
                crash_probability=crash_probability,
                crash_magnitude=crash_magnitude,
                recovery_speed=recovery_speed,
                base_volatility=base_volatility,
            )

            for nav in navs:
                cycle_start = time.perf_counter()

                if nav > stats.max_nav:
                    stats.max_nav = nav
                if nav < stats.min_nav:
                    stats.min_nav = nav

                nav_float = float(nav)
                if abs(nav_float - prev_nav) / prev_nav > 0.001:
                    stats.total_nav_changes += 1

                result = self.maintainer.maintain(self.current_orderbook, nav)
                self.current_orderbook = self._sync_to_target(result)

                cycle_time = (time.perf_counter() - cycle_start) * 1000

                total_cycle_time += cycle_time
                if cycle_time > stats.max_cycle_time_ms:
                    stats.max_cycle_time_ms = cycle_time
                if cycle_time < stats.min_cycle_time_ms:
                    stats.min_cycle_time_ms = cycle_time

                vii = float(abs(result.metrics.vii))
                qii = float(abs(result.metrics.qii))
                total_vii += vii
                total_qii += qii

                if vii > stats.max_vii:
                    stats.max_vii = vii
                if qii > stats.max_qii:
                    stats.max_qii = qii
                if vii > 0.2:
                    stats.vii_violations += 1

                if self.current_orderbook.bids and self.current_orderbook.asks:
                    best_bid = max(o.price for o in self.current_orderbook.bids)
                    best_ask = min(o.price for o in self.current_orderbook.asks)

                    if best_bid >= best_ask:
                        stats.price_cross_count += 1

                    spread = float((best_ask - best_bid) / nav)
                    total_spread += spread
                    spread_count += 1

                    if spread > stats.max_spread:
                        stats.max_spread = spread
                    if spread < stats.min_spread:
                        stats.min_spread = spread
                    if spread < 0:
                        stats.negative_spread_count += 1

                bid_count = len(self.current_orderbook.bids)
                ask_count = len(self.current_orderbook.asks)

                if bid_count > stats.max_bid_count:
                    stats.max_bid_count = bid_count
                if ask_count > stats.max_ask_count:
                    stats.max_ask_count = ask_count

                if bid_count > expected_orders + 5 or ask_count > expected_orders + 5:
                    stats.order_count_violations += 1

                if processed % sample_interval == 0:
                    stats.sampled_vii.append(vii)
                    if spread_count > 0:
                        stats.sampled_spreads.append(spread)

                prev_nav = nav_float
                current_nav = nav_float
                processed += 1

            if processed % progress_interval == 0:
                elapsed = time.perf_counter() - start_time
                rate = processed / elapsed
                eta = (total_cycles - processed) / rate if rate > 0 else 0
                print(f"闪崩恢复: {processed:,}/{total_cycles:,} ({100*processed/total_cycles:.1f}%) 速率: {rate:,.0f}/s")

        end_time = time.perf_counter()
        stats.total_time_seconds = end_time - start_time
        stats.avg_cycle_time_ms = total_cycle_time / total_cycles
        stats.avg_vii = total_vii / total_cycles
        stats.avg_qii = total_qii / total_cycles
        stats.avg_spread = total_spread / spread_count if spread_count > 0 else 0
        stats.end_nav = Decimal(str(round(current_nav, 6)))

        return stats


@pytest.fixture
def stress_config() -> MaintainerConfig:
    """压力测试配置"""
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
        min_price_change=Decimal("0.001"),
        max_operations_per_cycle=20,
    )


@pytest.mark.slow
@pytest.mark.timeout(600)  # 10 分钟超时
class TestMillionCycleStress:
    """百万级周期压力测试
    
    需要较长时间运行，默认 pytest 超时会导致失败。
    运行方式: pytest tests/orderbook/maintainer/test_stress.py -m slow --timeout=600 -v
    """

    def test_1_million_random_walk(self, stress_config: MaintainerConfig):
        """
        100万次随机游走压力测试

        预期:
        - 平均VII < 0.10
        - 最大VII < 0.25
        - 无价格交叉
        - 无负价差
        - 订单数量稳定
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_stress_test(
            total_cycles=1_000_000,
            batch_size=10000,
            volatility=0.01,  # 1% 每步波动
            trend=0.0,
            seed=42,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 断言
        assert stats.avg_vii < 0.10, f"平均VII过高: {stats.avg_vii}"
        assert stats.max_vii < 0.25, f"最大VII过高: {stats.max_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"
        assert stats.negative_spread_count == 0, f"发生负价差: {stats.negative_spread_count}次"
        assert stats.order_count_violations < 100, f"订单数量违规过多: {stats.order_count_violations}"

    def test_1_million_trending_up(self, stress_config: MaintainerConfig):
        """
        100万次趋势上涨压力测试

        模拟长期牛市：每步 +0.001% 趋势
        预期100万步后价格约为初始的 e^10 ≈ 22026 倍
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_stress_test(
            total_cycles=1_000_000,
            batch_size=10000,
            volatility=0.005,
            trend=0.00001,  # 微小趋势，累计效应大
            seed=43,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 断言
        assert stats.end_nav > stats.start_nav, "价格应该上涨"
        assert stats.avg_vii < 0.12, f"平均VII过高: {stats.avg_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"

    def test_1_million_trending_down(self, stress_config: MaintainerConfig):
        """
        100万次趋势下跌压力测试

        模拟长期熊市
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_stress_test(
            total_cycles=1_000_000,
            batch_size=10000,
            volatility=0.005,
            trend=-0.00001,  # 微小下跌趋势
            seed=44,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 断言
        assert stats.end_nav < stats.start_nav, "价格应该下跌"
        assert stats.avg_vii < 0.12, f"平均VII过高: {stats.avg_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"
        assert stats.min_nav > Decimal("0.001"), "净值不应过低"

    def test_1_million_high_volatility(self, stress_config: MaintainerConfig):
        """
        100万次高波动压力测试

        模拟极端市场：5%波动率
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_stress_test(
            total_cycles=1_000_000,
            batch_size=10000,
            volatility=0.05,  # 5% 高波动
            trend=0.0,
            seed=45,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 高波动下放宽要求
        assert stats.avg_vii < 0.15, f"平均VII过高: {stats.avg_vii}"
        assert stats.max_vii < 0.35, f"最大VII过高: {stats.max_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"

    def test_1_million_mean_reverting(self, stress_config: MaintainerConfig):
        """
        100万次均值回归压力测试

        模拟震荡市场：价格围绕均值波动
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_mean_reverting_test(
            total_cycles=1_000_000,
            batch_size=10000,
            mean=1.0,
            reversion_speed=0.05,
            volatility=0.01,
            seed=46,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 均值回归应该保持稳定
        assert stats.avg_vii < 0.10, f"平均VII过高: {stats.avg_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"
        # 最终价格应该接近均值
        assert Decimal("0.5") < stats.end_nav < Decimal("2.0"), f"最终净值偏离均值过远: {stats.end_nav}"

    def test_1_million_volatile_spikes(self, stress_config: MaintainerConfig):
        """
        100万次突发波动压力测试

        模拟间歇性大波动：5%概率出现5%的突发波动
        预期100万步中约有5万次突发波动
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_volatile_spikes_test(
            total_cycles=1_000_000,
            batch_size=10000,
            base_volatility=0.005,
            spike_probability=0.05,  # 5%概率
            spike_magnitude=0.05,     # 5%幅度
            seed=47,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 突发波动下放宽要求
        assert stats.avg_vii < 0.12, f"平均VII过高: {stats.avg_vii}"
        assert stats.max_vii < 0.30, f"最大VII过高: {stats.max_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"

    def test_1_million_flash_crash(self, stress_config: MaintainerConfig):
        """
        100万次闪崩恢复压力测试

        模拟极端事件：0.01%概率发生20%闪崩
        预期100万步中约有100次闪崩
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_flash_crash_test(
            total_cycles=1_000_000,
            batch_size=10000,
            crash_probability=0.0001,  # 0.01%概率
            crash_magnitude=0.2,        # 20%闪崩
            recovery_speed=0.01,
            base_volatility=0.005,
            seed=48,
            sample_interval=10000,
            progress_interval=100000,
        )

        print(stats.summary())

        # 闪崩场景下放宽要求
        assert stats.avg_vii < 0.15, f"平均VII过高: {stats.avg_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"
        assert stats.negative_spread_count == 0, f"发生负价差: {stats.negative_spread_count}次"


@pytest.mark.slow
@pytest.mark.stress
@pytest.mark.timeout(3600)  # 1 小时超时
class TestTenMillionCycleStress:
    """千万级周期压力测试
    
    运行方式: pytest tests/orderbook/maintainer/test_stress.py -m stress --timeout=3600 -v
    """

    def test_10_million_cycles(self, stress_config: MaintainerConfig):
        """
        1000万次超长压力测试

        验证系统在超长运行下的稳定性
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_stress_test(
            total_cycles=10_000_000,
            batch_size=50000,
            volatility=0.01,
            trend=0.0,
            seed=100,
            sample_interval=100000,
            progress_interval=1000000,
        )

        print(stats.summary())

        # 断言
        assert stats.avg_vii < 0.10, f"平均VII过高: {stats.avg_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"
        assert stats.negative_spread_count == 0, f"发生负价差: {stats.negative_spread_count}次"


@pytest.mark.timeout(120)  # 2 分钟超时
class TestQuickStress:
    """快速压力测试（用于CI）
    
    这个测试较快，可以在CI中常规运行。
    """

    def test_100k_quick_stress(self, stress_config: MaintainerConfig):
        """
        10万次快速压力测试

        用于CI环境快速验证
        """
        simulator = StressTestSimulator(stress_config)

        stats = simulator.run_stress_test(
            total_cycles=100_000,
            batch_size=10000,
            volatility=0.01,
            trend=0.0,
            seed=999,
            sample_interval=5000,
            progress_interval=20000,
        )

        print(stats.summary())

        # 断言
        assert stats.avg_vii < 0.10, f"平均VII过高: {stats.avg_vii}"
        assert stats.price_cross_count == 0, f"发生价格交叉: {stats.price_cross_count}次"
        assert stats.negative_spread_count == 0, f"发生负价差: {stats.negative_spread_count}次"


@pytest.mark.timeout(300)  # 5 分钟超时
class TestRealisticExecutionStress:
    """
    真实执行逻辑的压力测试

    与 TestMillionCycleStress 不同，这里使用 _execute_operations
    模拟真实的操作执行，而不是直接同步到目标订单簿。
    
    运行方式: pytest tests/orderbook/maintainer/test_stress.py::TestRealisticExecutionStress -v
    """

    def test_realistic_10k_cycles(self, stress_config: MaintainerConfig):
        """
        1万次真实执行压力测试

        验证订单不会无限累积
        """
        simulator = StressTestSimulator(stress_config)
        simulator.reset()

        nav = Decimal("1.0")
        simulator.maintainer.generate_initial(nav)

        expected_per_side = stress_config.total_orders_per_side
        max_allowed = expected_per_side * 4  # 允许最多 4 倍

        max_order_count = 0
        accumulation_violations = 0

        for i in range(10_000):
            # 随机 NAV 变化
            nav_change = Decimal(str(random.uniform(-0.02, 0.02)))
            nav = nav * (1 + nav_change)
            nav = max(nav, Decimal("0.1"))

            result = simulator.maintainer.maintain(simulator.current_orderbook, nav)

            # 使用真实执行逻辑
            simulator.current_orderbook = simulator._execute_operations(result)

            current_count = simulator.current_orderbook.total_orders
            max_order_count = max(max_order_count, current_count)

            if current_count > max_allowed:
                accumulation_violations += 1

        print(f"\n真实执行压力测试结果:")
        print(f"  最大订单数: {max_order_count}")
        print(f"  目标订单数: {expected_per_side * 2}")
        print(f"  累积违规次数: {accumulation_violations}")

        # 关键断言：订单不应无限累积
        assert accumulation_violations < 100, (
            f"订单累积违规 {accumulation_violations} 次，"
            f"最大订单数 {max_order_count}"
        )

    def test_realistic_with_large_initial(self, stress_config: MaintainerConfig):
        """
        从大量初始订单开始的真实执行测试

        验证系统能够逐步减少过量订单
        """
        simulator = StressTestSimulator(stress_config)
        simulator.reset()

        nav = Decimal("1.0")
        simulator.maintainer.generate_initial(nav)

        # 创建过量的初始订单
        initial_bids = []
        initial_asks = []
        for i in range(150):
            initial_bids.append(
                ExistingOrder(
                    order_id=f"init_bid_{i}",
                    price=nav * (1 - Decimal("0.001") * (i + 1)),
                    quantity=Decimal("100"),
                    side="bid",
                )
            )
            initial_asks.append(
                ExistingOrder(
                    order_id=f"init_ask_{i}",
                    price=nav * (1 + Decimal("0.001") * (i + 1)),
                    quantity=Decimal("100"),
                    side="ask",
                )
            )

        simulator.current_orderbook = CurrentOrderbook(
            bids=initial_bids,
            asks=initial_asks,
        )

        initial_count = simulator.current_orderbook.total_orders  # 300
        expected_per_side = stress_config.total_orders_per_side
        target_count = expected_per_side * 2

        counts = [initial_count]

        # 运行 100 个周期
        for i in range(100):
            nav_change = Decimal(str(random.uniform(-0.01, 0.01)))
            nav = nav * (1 + nav_change)

            result = simulator.maintainer.maintain(simulator.current_orderbook, nav)
            simulator.current_orderbook = simulator._execute_operations(result)

            counts.append(simulator.current_orderbook.total_orders)

        final_count = counts[-1]

        print(f"\n大初始订单测试结果:")
        print(f"  初始订单数: {initial_count}")
        print(f"  最终订单数: {final_count}")
        print(f"  目标订单数: {target_count}")

        # 订单数应该减少
        assert final_count < initial_count, (
            f"订单数应该减少: {initial_count} -> {final_count}"
        )

        # 应该趋向目标
        assert final_count < target_count * 2, (
            f"最终订单数 {final_count} 应接近目标 {target_count}"
        )


# 命令行运行入口
if __name__ == "__main__":
    """
    直接运行压力测试:
    python -m tests.orderbook.maintainer.test_stress

    或指定测试:
    python -m pytest tests/orderbook/maintainer/test_stress.py::TestMillionCycleStress::test_1_million_random_walk -v -s
    """
    import sys

    # 创建配置
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
    config = MaintainerConfig(
        spread=Decimal("0.008"),
        max_distance=Decimal("0.05"),
        total_budget=Decimal("10000"),
        near_layer=near_layer,
        far_layer=far_layer,
        price_precision=6,
        quantity_precision=4,
        min_price_change=Decimal("0.001"),
        max_operations_per_cycle=20,
    )

    # 运行测试
    simulator = StressTestSimulator(config)

    cycles = 1_000_000
    if len(sys.argv) > 1:
        cycles = int(sys.argv[1])

    print(f"\n开始 {cycles:,} 次压力测试...\n")

    stats = simulator.run_stress_test(
        total_cycles=cycles,
        batch_size=10000,
        volatility=0.01,
        trend=0.0,
        seed=42,
        sample_interval=10000,
        progress_interval=100000,
    )

    print(stats.summary())
