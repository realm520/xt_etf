"""
订单簿平衡指标计算器

设计原则：
1. 价值平衡：V_bid ≈ V_ask
2. 数量平衡：Q_bid ≈ Q_ask
3. 不平衡指数：衡量偏离程度
"""

from decimal import Decimal
from typing import List
from dataclasses import dataclass

from ..base import OrderLevel


@dataclass
class BalanceMetrics:
    """订单簿平衡指标"""

    # 不平衡指数
    vii: Decimal  # 价值不平衡指数 (Value Imbalance Index)
    qii: Decimal  # 数量不平衡指数 (Quantity Imbalance Index)

    # 原始数值
    v_bid: Decimal  # 买单总价值
    v_ask: Decimal  # 卖单总价值
    q_bid: Decimal  # 买单总数量
    q_ask: Decimal  # 卖单总数量

    # 订单统计
    n_bid: int  # 买单数量
    n_ask: int  # 卖单数量

    @property
    def is_value_balanced(self) -> bool:
        """价值是否平衡（10%容差）"""
        return abs(self.vii) <= Decimal("0.1")

    @property
    def is_quantity_balanced(self) -> bool:
        """数量是否平衡（10%容差）"""
        return abs(self.qii) <= Decimal("0.1")

    @property
    def is_balanced(self) -> bool:
        """整体是否平衡"""
        return self.is_value_balanced and self.is_quantity_balanced

    @property
    def value_diff(self) -> Decimal:
        """价值差异（绝对值）"""
        return abs(self.v_bid - self.v_ask)

    @property
    def quantity_diff(self) -> Decimal:
        """数量差异（绝对值）"""
        return abs(self.q_bid - self.q_ask)

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "vii": float(self.vii),
            "qii": float(self.qii),
            "v_bid": float(self.v_bid),
            "v_ask": float(self.v_ask),
            "q_bid": float(self.q_bid),
            "q_ask": float(self.q_ask),
            "n_bid": self.n_bid,
            "n_ask": self.n_ask,
            "is_balanced": self.is_balanced,
        }


class MetricsCalculator:
    """指标计算器"""

    @staticmethod
    def calculate(
        bids: List[OrderLevel], asks: List[OrderLevel]
    ) -> BalanceMetrics:
        """
        计算订单簿平衡指标

        Args:
            bids: 买单列表
            asks: 卖单列表

        Returns:
            BalanceMetrics: 平衡指标

        公式：
        - VII = (V_bid - V_ask) / (V_bid + V_ask)
        - QII = (Q_bid - Q_ask) / (Q_bid + Q_ask)
        - 范围: [-1, 1]，0 表示完美平衡
        """
        # 计算买单总价值和数量
        v_bid = Decimal("0")
        q_bid = Decimal("0")
        for order in bids:
            price = (
                order.price
                if isinstance(order.price, Decimal)
                else Decimal(str(order.price))
            )
            quantity = (
                order.quantity
                if isinstance(order.quantity, Decimal)
                else Decimal(str(order.quantity))
            )
            v_bid += price * quantity
            q_bid += quantity

        # 计算卖单总价值和数量
        v_ask = Decimal("0")
        q_ask = Decimal("0")
        for order in asks:
            price = (
                order.price
                if isinstance(order.price, Decimal)
                else Decimal(str(order.price))
            )
            quantity = (
                order.quantity
                if isinstance(order.quantity, Decimal)
                else Decimal(str(order.quantity))
            )
            v_ask += price * quantity
            q_ask += quantity

        # 计算不平衡指数
        v_total = v_bid + v_ask
        q_total = q_bid + q_ask

        vii = (
            (v_bid - v_ask) / v_total
            if v_total > Decimal("0")
            else Decimal("0")
        )
        qii = (
            (q_bid - q_ask) / q_total
            if q_total > Decimal("0")
            else Decimal("0")
        )

        return BalanceMetrics(
            vii=vii,
            qii=qii,
            v_bid=v_bid,
            v_ask=v_ask,
            q_bid=q_bid,
            q_ask=q_ask,
            n_bid=len(bids),
            n_ask=len(asks),
        )

    @staticmethod
    def calculate_spread(
        bids: List[OrderLevel],
        asks: List[OrderLevel],
        nav: Decimal,
    ) -> dict:
        """
        计算买卖价差指标

        Args:
            bids: 买单列表（假设已按价格降序排列）
            asks: 卖单列表（假设已按价格升序排列）
            nav: 当前净值

        Returns:
            dict: 价差指标
                - best_bid: 最佳买价
                - best_ask: 最佳卖价
                - spread: 买卖价差（绝对值）
                - spread_pct: 买卖价差百分比
                - mid_price: 中间价
                - mid_nav_diff: 中间价与NAV的差异
        """
        if not bids or not asks:
            return {
                "best_bid": None,
                "best_ask": None,
                "spread": None,
                "spread_pct": None,
                "mid_price": None,
                "mid_nav_diff": None,
            }

        # 获取最佳买卖价
        best_bid = max(
            (
                order.price
                if isinstance(order.price, Decimal)
                else Decimal(str(order.price))
            )
            for order in bids
        )
        best_ask = min(
            (
                order.price
                if isinstance(order.price, Decimal)
                else Decimal(str(order.price))
            )
            for order in asks
        )

        # 计算价差
        spread = best_ask - best_bid
        mid_price = (best_bid + best_ask) / 2

        spread_pct = spread / mid_price if mid_price > Decimal("0") else Decimal("0")

        mid_nav_diff = (
            (mid_price - nav) / nav if nav > Decimal("0") else Decimal("0")
        )

        return {
            "best_bid": float(best_bid),
            "best_ask": float(best_ask),
            "spread": float(spread),
            "spread_pct": float(spread_pct),
            "mid_price": float(mid_price),
            "mid_nav_diff": float(mid_nav_diff),
        }

    @staticmethod
    def calculate_layer_metrics(
        orders: List[OrderLevel], nav: Decimal
    ) -> dict:
        """
        按层计算订单指标

        Args:
            orders: 订单列表
            nav: 当前净值

        Returns:
            dict: 分层指标
        """
        layers = {"near": [], "far": [], "unknown": []}

        for order in orders:
            layer = order.metadata.get("layer", "unknown") if order.metadata else "unknown"
            if layer in layers:
                layers[layer].append(order)
            else:
                layers["unknown"].append(order)

        result = {}
        for layer_name, layer_orders in layers.items():
            if not layer_orders:
                continue

            # 计算该层指标
            v_total = Decimal("0")
            q_total = Decimal("0")
            prices = []

            for order in layer_orders:
                price = (
                    order.price
                    if isinstance(order.price, Decimal)
                    else Decimal(str(order.price))
                )
                quantity = (
                    order.quantity
                    if isinstance(order.quantity, Decimal)
                    else Decimal(str(order.quantity))
                )
                v_total += price * quantity
                q_total += quantity
                prices.append(price)

            # 计算距离范围
            if prices:
                min_dist = abs(min(prices) - nav) / nav if nav > Decimal("0") else Decimal("0")
                max_dist = abs(max(prices) - nav) / nav if nav > Decimal("0") else Decimal("0")
            else:
                min_dist = max_dist = Decimal("0")

            result[layer_name] = {
                "order_count": len(layer_orders),
                "total_value": float(v_total),
                "total_quantity": float(q_total),
                "min_distance": float(min_dist),
                "max_distance": float(max_dist),
            }

        return result
