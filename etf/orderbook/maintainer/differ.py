"""
订单簿差异计算器

设计原则：
1. 最小化操作：复用价格容差内的现有订单
2. 智能匹配：基于价格索引的 O(n) 匹配算法
3. 只添加/取消必要的订单
"""

from decimal import Decimal
from typing import List, Dict, Set, Tuple, Optional
from dataclasses import dataclass

from ..base import OrderLevel, OrderOperation
from .config import MaintainerConfig


@dataclass
class ExistingOrder:
    """现有订单（从交易所获取）"""

    order_id: str
    price: Decimal
    quantity: Decimal
    side: str  # 'bid' | 'ask'
    layer: Optional[str] = None  # 所属层级（可选）
    client_order_id: Optional[str] = None

    def __post_init__(self):
        """类型转换"""
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))
        if not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))


@dataclass
class CurrentOrderbook:
    """当前订单簿状态（从交易所获取）"""

    bids: List[ExistingOrder]
    asks: List[ExistingOrder]

    @classmethod
    def from_exchange_orders(cls, orders: List[Dict]) -> "CurrentOrderbook":
        """
        从交易所订单格式转换

        Args:
            orders: 交易所订单列表，格式：
                [
                    {
                        'orderId': '123',
                        'clientOrderId': 'mm_xxx',
                        'price': '1.0',
                        'origQty': '100',
                        'side': 'BUY',
                        ...
                    }
                ]

        Returns:
            CurrentOrderbook 实例
        """
        bids = []
        asks = []

        for o in orders:
            # 提取订单ID（兼容不同字段名）
            order_id = o.get("orderId") or o.get("order_id", "")

            # 提取价格和数量
            price = Decimal(str(o.get("price", 0)))
            quantity = Decimal(
                str(o.get("origQty") or o.get("quantity") or o.get("origQuantity", 0))
            )

            # 判断方向
            side_raw = o.get("side", "").upper()
            if side_raw == "BUY":
                side = "bid"
            elif side_raw == "SELL":
                side = "ask"
            else:
                continue  # 跳过未知方向

            existing = ExistingOrder(
                order_id=str(order_id),
                price=price,
                quantity=quantity,
                side=side,
                client_order_id=o.get("clientOrderId"),
            )

            if side == "bid":
                bids.append(existing)
            else:
                asks.append(existing)

        return cls(bids=bids, asks=asks)

    @classmethod
    def empty(cls) -> "CurrentOrderbook":
        """创建空订单簿"""
        return cls(bids=[], asks=[])

    @property
    def total_orders(self) -> int:
        """总订单数"""
        return len(self.bids) + len(self.asks)

    @property
    def is_empty(self) -> bool:
        """是否为空"""
        return self.total_orders == 0


class OrderbookDiffer:
    """差异计算器 - 最小化操作"""

    def compute_diff(
        self,
        current: CurrentOrderbook,
        target_bids: List[OrderLevel],
        target_asks: List[OrderLevel],
        nav: Decimal,
        config: MaintainerConfig,
    ) -> List[OrderOperation]:
        """
        计算订单簿差异

        Args:
            current: 当前订单簿状态
            target_bids: 目标买单列表
            target_asks: 目标卖单列表
            nav: 当前净值
            config: 维护器配置

        Returns:
            操作列表（未排序）

        算法：
        1. 构建价格索引 O(n)
        2. 价格容差内订单复用（无需操作）
        3. 只添加/取消必要订单
        """
        operations: List[OrderOperation] = []

        # 处理买单
        ops_bid = self._match_side(
            current.bids, target_bids, "bid", nav, config
        )
        operations.extend(ops_bid)

        # 处理卖单
        ops_ask = self._match_side(
            current.asks, target_asks, "ask", nav, config
        )
        operations.extend(ops_ask)

        return operations

    def _match_side(
        self,
        current: List[ExistingOrder],
        target: List[OrderLevel],
        side: str,
        nav: Decimal,
        config: MaintainerConfig,
    ) -> List[OrderOperation]:
        """
        单边匹配算法

        Args:
            current: 现有订单列表
            target: 目标订单列表
            side: 方向 'bid' | 'ask'
            nav: 当前净值
            config: 配置

        Returns:
            操作列表
        """
        operations: List[OrderOperation] = []
        matched_current_ids: Set[str] = set()
        matched_target_indices: Set[int] = set()

        # 1. 构建价格索引
        price_index: Dict[Decimal, List[ExistingOrder]] = {}
        for order in current:
            # 四舍五入到配置精度
            key = self._round_price(order.price, config.price_precision)
            price_index.setdefault(key, []).append(order)

        # 2. 匹配目标订单
        for i, target_order in enumerate(target):
            target_price = self._round_price(target_order.price, config.price_precision)
            matched = False

            # 在价格容差范围内查找
            for existing in price_index.get(target_price, []):
                if existing.order_id in matched_current_ids:
                    continue

                # 数量容差检查
                if target_order.quantity > Decimal("0"):
                    qty_diff = abs(existing.quantity - target_order.quantity)
                    qty_ratio = qty_diff / target_order.quantity

                    if qty_ratio <= config.quantity_tolerance:
                        # 找到匹配，复用现有订单
                        matched_current_ids.add(existing.order_id)
                        matched_target_indices.add(i)
                        matched = True
                        break

            if not matched:
                # 需要添加新订单
                operations.append(
                    OrderOperation(
                        action="add",
                        side=side,
                        price=target_order.price,
                        quantity=target_order.quantity,
                        reason=f"new_{side}_order",
                    )
                )

        # 3. 取消未匹配的现有订单
        for order in current:
            if order.order_id not in matched_current_ids:
                operations.append(
                    OrderOperation(
                        action="cancel",
                        side=side,
                        order_id=order.order_id,
                        reason=f"unmatched_{side}_order",
                    )
                )

        return operations

    def _round_price(self, price: Decimal, precision: int) -> Decimal:
        """四舍五入价格"""
        return round(price, precision)

    def compute_reuse_ratio(
        self,
        current: CurrentOrderbook,
        target_bids: List[OrderLevel],
        target_asks: List[OrderLevel],
        config: MaintainerConfig,
    ) -> float:
        """
        计算订单复用率

        Args:
            current: 当前订单簿
            target_bids: 目标买单
            target_asks: 目标卖单
            config: 配置

        Returns:
            复用率 (0.0 - 1.0)
        """
        # 简化实现：计算操作数量
        ops = self.compute_diff(
            current, target_bids, target_asks, Decimal("1"), config
        )

        total_current = current.total_orders
        if total_current == 0:
            return 0.0

        cancel_count = sum(1 for op in ops if op.action == "cancel")
        reused = total_current - cancel_count

        return reused / total_current if total_current > 0 else 0.0
