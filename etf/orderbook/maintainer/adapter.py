"""
Maintainer 数据适配器

职责：
1. 将交易所订单格式转换为 CurrentOrderbook
2. 过滤仅 mm_ 前缀的做市订单
3. 提供数据格式转换工具
"""

from decimal import Decimal
from typing import List, Dict, Optional

from .differ import CurrentOrderbook, ExistingOrder
from ..base import OrderOperation


class MaintainerAdapter:
    """
    数据格式适配器

    核心功能：
    1. exchange_orders → CurrentOrderbook
    2. OrderManager.open_orders → CurrentOrderbook
    3. OrderOperation → OrderManager 参数
    """

    @staticmethod
    def from_exchange_orders(
        orders: List[Dict],
        filter_prefix: str = "mm_",
    ) -> CurrentOrderbook:
        """
        从交易所订单格式转换为 CurrentOrderbook

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
            filter_prefix: 只处理指定前缀的订单，None 表示全部

        Returns:
            CurrentOrderbook 实例
        """
        if filter_prefix:
            orders = [
                o for o in orders
                if (o.get("clientOrderId") or "").startswith(filter_prefix)
            ]

        return CurrentOrderbook.from_exchange_orders(orders)

    @staticmethod
    def from_open_orders_dict(
        open_orders: Dict[str, Dict],
        filter_prefix: str = "mm_",
    ) -> CurrentOrderbook:
        """
        从 OrderManager.open_orders 字典转换为 CurrentOrderbook

        Args:
            open_orders: OrderManager.open_orders 字典，格式：
                {
                    "order_id_123": {
                        "symbol": "BTCUSDT",
                        "side": "BUY",
                        "price": 50000.0,
                        "origQty": 0.001,
                        "orderId": "order_id_123",
                        "clientOrderId": "mm_xxx",
                        ...
                    }
                }
            filter_prefix: 只处理指定前缀的订单，None 表示全部

        Returns:
            CurrentOrderbook 实例
        """
        bids = []
        asks = []

        for order_id, order in open_orders.items():
            # 过滤前缀
            client_order_id = order.get("clientOrderId") or ""
            if filter_prefix and not client_order_id.startswith(filter_prefix):
                continue

            # 提取价格和数量
            price = Decimal(str(order.get("price", 0)))
            quantity = Decimal(
                str(order.get("origQty") or order.get("quantity", 0))
            )

            # 判断方向
            side_raw = order.get("side", "").upper()
            if side_raw == "BUY":
                side = "bid"
            elif side_raw == "SELL":
                side = "ask"
            else:
                continue

            existing = ExistingOrder(
                order_id=str(order.get("orderId") or order_id),
                price=price,
                quantity=quantity,
                side=side,
                client_order_id=client_order_id,
            )

            if side == "bid":
                bids.append(existing)
            else:
                asks.append(existing)

        return CurrentOrderbook(bids=bids, asks=asks)

    @staticmethod
    def operation_to_add_params(
        op: OrderOperation,
        symbol: str,
        price_precision: int = 6,
        quantity_precision: int = 2,
    ) -> Dict:
        """
        将 add 类型的 OrderOperation 转换为 OrderManager.add_order 参数

        Args:
            op: OrderOperation 实例（action='add'）
            symbol: 交易对
            price_precision: 价格精度
            quantity_precision: 数量精度

        Returns:
            Dict: OrderManager.add_order 参数
        """
        if op.action != "add":
            raise ValueError(f"Expected add operation, got {op.action}")

        return {
            "symbol": symbol,
            "side": "BUY" if op.side == "bid" else "SELL",
            "price": float(round(op.price, price_precision)),
            "quantity": float(round(op.quantity, quantity_precision)),
            "order_purpose": "market_making",
        }

    @staticmethod
    def operation_to_cancel_params(op: OrderOperation) -> Dict:
        """
        将 cancel 类型的 OrderOperation 转换为 OrderManager.cancel_order 参数

        Args:
            op: OrderOperation 实例（action='cancel'）

        Returns:
            Dict: OrderManager.cancel_order 参数
        """
        if op.action != "cancel":
            raise ValueError(f"Expected cancel operation, got {op.action}")

        return {"orderId": op.order_id}

    @staticmethod
    def count_mm_orders(orders: List[Dict]) -> int:
        """
        统计 mm_ 前缀订单数量

        Args:
            orders: 订单列表

        Returns:
            int: mm_ 订单数量
        """
        return sum(
            1
            for o in orders
            if (o.get("clientOrderId") or "").startswith("mm_")
        )

    @staticmethod
    def count_mm_orders_from_dict(open_orders: Dict[str, Dict]) -> int:
        """
        从 open_orders 字典统计 mm_ 前缀订单数量

        Args:
            open_orders: OrderManager.open_orders 字典

        Returns:
            int: mm_ 订单数量
        """
        return sum(
            1
            for order in open_orders.values()
            if (order.get("clientOrderId") or "").startswith("mm_")
        )
