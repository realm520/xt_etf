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

        # 6. 判断是否为初始化阶段（当前订单簿为空或几乎为空）
        current_order_count = len(current.bids) + len(current.asks)
        target_order_count = len(target.bids) + len(target.asks)
        # 初始化阶段：当前订单数 < 目标订单数的 20%
        is_initial = current_order_count < target_order_count * 0.2

        # 7. 限制操作数量（初始化阶段不限制）
        limited_operations, was_limited = self._limit_operations(
            sorted_operations, is_initial=is_initial
        )

        # 8. 计算指标
        metrics = MetricsCalculator.calculate(target.bids, target.asks)

        # 9. 更新状态
        self._last_nav = new_nav

        # 10. 构建结果
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
        is_initial: bool = False,
    ) -> Tuple[List[OrderOperation], bool]:
        """
        限制操作数量（智能平衡 add/cancel 和 bid/ask）

        策略：
        1. 初始化阶段：不限制操作数量，一次性挂满所有订单
        2. 维护阶段：限制每周期操作数量
           - 平衡 add 和 cancel 的比例
           - **关键**: 平衡 bid 和 ask 两侧的操作，避免单边被清空

        Args:
            operations: 操作列表
            is_initial: 是否为初始化阶段（首次建仓）

        Returns:
            (limited_operations, was_limited)
        """
        # 初始化阶段：不限制，一次性挂满所有订单
        if is_initial:
            return operations, False

        max_ops = self.config.max_operations_per_cycle

        if len(operations) <= max_ops:
            return operations, False

        # 按 action 和 side 四维分类
        add_bids = [op for op in operations if op.action == "add" and op.side == "bid"]
        add_asks = [op for op in operations if op.action == "add" and op.side == "ask"]
        cancel_bids = [op for op in operations if op.action == "cancel" and op.side == "bid"]
        cancel_asks = [op for op in operations if op.action == "cancel" and op.side == "ask"]

        total_ops = len(operations)
        if total_ops == 0:
            return [], True

        # 计算 add 和 cancel 的总数
        total_adds = len(add_bids) + len(add_asks)
        total_cancels = len(cancel_bids) + len(cancel_asks)

        # 第一步：确定 add 和 cancel 的配额
        if total_cancels >= max_ops:
            # cancel 很多，给 80% 配额
            cancel_quota = int(max_ops * 0.8)
            add_quota = max_ops - cancel_quota
        elif total_cancels > total_adds:
            # cancel > add，给 60% 配额
            cancel_quota = int(max_ops * 0.6)
            add_quota = max_ops - cancel_quota
        elif total_cancels >= max_ops * 0.5:
            # cancel 较多，50% 配额
            cancel_quota = int(max_ops * 0.5)
            add_quota = max_ops - cancel_quota
        else:
            # 正常情况，按原始比例分配，cancel 至少 30%
            if total_cancels > 0:
                cancel_ratio = max(total_cancels / total_ops, 0.3)
                if total_cancels < max_ops * 0.3:
                    cancel_quota = total_cancels
                else:
                    cancel_quota = int(max_ops * cancel_ratio)
                add_quota = max_ops - cancel_quota
            else:
                add_quota = max_ops
                cancel_quota = 0

        # 第二步：在 add/cancel 配额内，平衡 bid/ask
        # 原则：每侧至少获得 40% 的该类操作配额（避免单边被清空）
        
        def balanced_select(ops_side1: List, ops_side2: List, quota: int) -> Tuple[List, List]:
            """
            平衡选择两侧的操作
            
            确保每侧至少获得 40% 配额（如果有足够的操作）
            """
            if quota <= 0:
                return [], []
            
            total = len(ops_side1) + len(ops_side2)
            if total == 0:
                return [], []
            
            if total <= quota:
                # 不需要限制
                return ops_side1, ops_side2
            
            # 计算每侧的最小配额（40%）
            min_ratio = 0.4
            min_per_side = int(quota * min_ratio)
            
            # 如果一侧没有操作，全部给另一侧
            if len(ops_side1) == 0:
                return [], ops_side2[:quota]
            if len(ops_side2) == 0:
                return ops_side1[:quota], []
            
            # 两侧都有操作，平衡分配
            # 先给每侧最小配额
            side1_quota = min(len(ops_side1), min_per_side)
            side2_quota = min(len(ops_side2), min_per_side)
            
            # 剩余配额按原始比例分配
            remaining = quota - side1_quota - side2_quota
            if remaining > 0:
                # 按原始比例分配剩余配额
                side1_remaining = len(ops_side1) - side1_quota
                side2_remaining = len(ops_side2) - side2_quota
                total_remaining = side1_remaining + side2_remaining
                
                if total_remaining > 0:
                    side1_extra = int(remaining * side1_remaining / total_remaining)
                    side1_extra = min(side1_extra, side1_remaining)
                    side2_extra = min(remaining - side1_extra, side2_remaining)
                    
                    side1_quota += side1_extra
                    side2_quota += side2_extra
            
            return ops_side1[:side1_quota], ops_side2[:side2_quota]

        # 平衡选择 add 操作（bid vs ask）
        selected_add_bids, selected_add_asks = balanced_select(
            add_bids, add_asks, min(add_quota, total_adds)
        )
        
        # 平衡选择 cancel 操作（bid vs ask）
        selected_cancel_bids, selected_cancel_asks = balanced_select(
            cancel_bids, cancel_asks, min(cancel_quota, total_cancels)
        )

        # 合并结果（保持原始排序顺序已经在 _sort_operations 中处理）
        result = selected_add_bids + selected_add_asks + selected_cancel_bids + selected_cancel_asks

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
