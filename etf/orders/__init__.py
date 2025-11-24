"""
订单类型系统

提供强类型的订单类层次结构，支持不同业务场景的订单类型。
"""

from .types import (
    OrderType,
    OrderSide,
    OrderStatus,
    BaseOrder,
)
from .market_making import MarketMakingOrder
from .wash_trading import WashTradingOrder
from .anti_pin import AntiPinOrder

__all__ = [
    # 枚举
    "OrderType",
    "OrderSide",
    "OrderStatus",
    # 基类
    "BaseOrder",
    # 具体订单类
    "MarketMakingOrder",
    "WashTradingOrder",
    "AntiPinOrder",
]
