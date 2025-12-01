"""
订单簿维护器核心模块

设计原则：
1. 纯算法：无 IO 依赖，确定性输入输出
2. 智能排序：价格上涨/下跌时不同操作顺序
3. 操作限制：每周期最多 N 个操作
"""

from decimal import Decimal
from typing import List, Optional, Tuple
from dataclasses import dataclass, field

from ..base import OrderLevel, OrderbookSnapshot, OrderOperation
from .config import MaintainerConfig
from .generator import OrderbookGenerator
from .differ import OrderbookDiffer, CurrentOrderbook, ExistingOrder
from .metrics import BalanceMetrics, MetricsCalculator


@dataclass
class MaintenanceStats:
    """维护统计信息"""

    nav_change: Decimal  # NAV 变化量
    nav_change_pct: Decimal  # NAV 变化百分比
    price_direction: str  # 价格方向: 'up' | 'down' | 'stable'
    reuse_ratio: float  # 订单复用率
    operations_count: int  # 操作数量
    operations_limited: bool  # 是否被限制


@dataclass
class MaintenanceResult:
    """维护结果"""

    # 目标订单簿
    target_snapshot: OrderbookSnapshot

    # 需要执行的操作（已排序）
    operations: List[OrderOperation]

    # 平衡指标
    metrics: BalanceMetrics

    # 统计信息
    stats: MaintenanceStats

    # 是否需要更新
    needs_update: bool = True


class OrderbookMaintainer:
    """
    订单簿维护器

    核心功能：
    1. 生成价值平衡的初始订单簿
    2. 计算 NAV 变化时的调整操作
    3. 智能排序操作顺序
    """

    def __init__(self, config: MaintainerConfig):
        """
        初始化维护器

        Args:
            config: 维护器配置
        """
        self.config = config
        self.generator = OrderbookGenerator()
        self.differ = OrderbookDiffer()
        self._last_nav: Optional[Decimal] = None

    def generate_initial(self, nav: Decimal) -> OrderbookSnapshot:
        """
        生成初始订单簿

        Args:
            nav: 当前净值

        Returns:
            OrderbookSnapshot: 初始订单簿快照
        """
        if not isinstance(nav, Decimal):
            nav = Decimal(str(nav))

        snapshot = self.generator.generate(nav, self.config)
        self._last_nav = nav
        return snapshot

    def maintain(
        self,
        current: CurrentOrderbook,
        new_nav: Decimal,
    ) -> MaintenanceResult:
        """
        维护订单簿

        Args:
            current: 当前订单簿状态（从交易所获取）
            new_nav: 最新净值

        Returns:
            MaintenanceResult: 维护结果

        流程：
        1. 检查是否需要更新
        2. 生成目标订单簿
        3. 计算差异
        4. 智能排序操作
        5. 限制操作数量
        """
        if not isinstance(new_nav, Decimal):
            new_nav = Decimal(str(new_nav))

        # 1. 检查是否需要更新
        needs_update, nav_change, nav_change_pct = self._check_update_needed(new_nav)

        # 2. 生成目标订单簿
        target = self.generator.generate(new_nav, self.config)

        # 3. 计算差异
        raw_operations = self.differ.compute_diff(
            current,
            target.bids,
            target.asks,
            new_nav,
            self.config,
        )

        # 4. 计算复用率
        reuse_ratio = self.differ.compute_reuse_ratio(
            current, target.bids, target.asks, self.config
        )

        # 5. 智能排序
        price_direction = self._get_price_direction(nav_change_pct)
        sorted_operations = self._sort_operations(raw_operations, price_direction)

        # 6. 限制操作数量
        limited_operations, was_limited = self._limit_operations(sorted_operations)

        # 7. 计算指标
        metrics = MetricsCalculator.calculate(target.bids, target.asks)

        # 8. 更新状态
        self._last_nav = new_nav

        # 9. 构建结果
        stats = MaintenanceStats(
            nav_change=nav_change,
            nav_change_pct=nav_change_pct,
            price_direction=price_direction,
            reuse_ratio=reuse_ratio,
            operations_count=len(limited_operations),
            operations_limited=was_limited,
        )

        # needs_update 应该为 True 当：
        # 1. NAV 变化超过阈值 (needs_update=True) 或
        # 2. 有操作需要执行 (说明当前订单簿不完整)
        actual_needs_update = needs_update or len(limited_operations) > 0

        return MaintenanceResult(
            target_snapshot=target,
            operations=limited_operations,
            metrics=metrics,
            stats=stats,
            needs_update=actual_needs_update,
        )

    def _check_update_needed(
        self, new_nav: Decimal
    ) -> Tuple[bool, Decimal, Decimal]:
        """
        检查是否需要更新

        Args:
            new_nav: 新净值

        Returns:
            (needs_update, nav_change, nav_change_pct)
        """
        if self._last_nav is None:
            return True, Decimal("0"), Decimal("0")

        nav_change = new_nav - self._last_nav
        nav_change_pct = (
            nav_change / self._last_nav
            if self._last_nav > Decimal("0")
            else Decimal("0")
        )

        needs_update = abs(nav_change_pct) >= self.config.min_price_change

        return needs_update, nav_change, nav_change_pct

    def _get_price_direction(self, nav_change_pct: Decimal) -> str:
        """
        获取价格方向

        Args:
            nav_change_pct: NAV 变化百分比

        Returns:
            'up' | 'down' | 'stable'
        """
        if nav_change_pct > self.config.min_price_change:
            return "up"
        elif nav_change_pct < -self.config.min_price_change:
            return "down"
        else:
            return "stable"

    def _sort_operations(
        self,
        operations: List[OrderOperation],
        price_direction: str,
    ) -> List[OrderOperation]:
        """
        智能排序操作

        排序规则（避免自成交）：
        - 价格上涨：补近盘口买单 → 撤近盘口卖单 → 补远盘口卖单 → 撤远盘口买单
        - 价格下跌：补近盘口卖单 → 撤近盘口买单 → 补远盘口买单 → 撤远盘口卖单
        - 稳定：先添加后取消

        Args:
            operations: 未排序的操作列表
            price_direction: 价格方向

        Returns:
            排序后的操作列表
        """
        if not operations:
            return []

        # 分类操作
        add_bids = [op for op in operations if op.action == "add" and op.side == "bid"]
        add_asks = [op for op in operations if op.action == "add" and op.side == "ask"]
        cancel_bids = [
            op for op in operations if op.action == "cancel" and op.side == "bid"
        ]
        cancel_asks = [
            op for op in operations if op.action == "cancel" and op.side == "ask"
        ]

        # 按价格排序
        # 买单：按价格降序（高价在前）
        add_bids.sort(key=lambda x: x.price if x.price else Decimal("0"), reverse=True)
        # 卖单：按价格升序（低价在前）
        add_asks.sort(key=lambda x: x.price if x.price else Decimal("0"))

        # 取消操作按订单 ID 排序（保持稳定性）
        cancel_bids.sort(key=lambda x: x.order_id or "")
        cancel_asks.sort(key=lambda x: x.order_id or "")

        # 根据价格方向排序
        if price_direction == "up":
            # 价格上涨：补近盘口买单 → 撤近盘口卖单 → 补远盘口卖单 → 撤远盘口买单
            # 简化：添加买单 → 取消卖单 → 添加卖单 → 取消买单
            return add_bids + cancel_asks + add_asks + cancel_bids
        elif price_direction == "down":
            # 价格下跌：补近盘口卖单 → 撤近盘口买单 → 补远盘口买单 → 撤远盘口卖单
            # 简化：添加卖单 → 取消买单 → 添加买单 → 取消卖单
            return add_asks + cancel_bids + add_bids + cancel_asks
        else:
            # 稳定：先添加后取消（安全优先）
            return add_bids + add_asks + cancel_bids + cancel_asks

    def _limit_operations(
        self,
        operations: List[OrderOperation],
    ) -> Tuple[List[OrderOperation], bool]:
        """
        限制操作数量

        Args:
            operations: 操作列表

        Returns:
            (limited_operations, was_limited)
        """
        max_ops = self.config.max_operations_per_cycle

        if len(operations) <= max_ops:
            return operations, False

        # 优先保留添加操作（保持流动性）
        add_ops = [op for op in operations if op.action == "add"]
        cancel_ops = [op for op in operations if op.action == "cancel"]

        result = []
        remaining = max_ops

        # 先添加 add 操作
        for op in add_ops:
            if remaining <= 0:
                break
            result.append(op)
            remaining -= 1

        # 再添加 cancel 操作
        for op in cancel_ops:
            if remaining <= 0:
                break
            result.append(op)
            remaining -= 1

        return result, True

    def reset(self) -> None:
        """重置维护器状态"""
        self._last_nav = None


# 重新导出以保持向后兼容
__all__ = [
    "OrderbookMaintainer",
    "MaintenanceResult",
    "MaintenanceStats",
    "CurrentOrderbook",
    "ExistingOrder",
]
