"""
订单执行模块

提供可插拔的订单执行实现：
- MarketOrderExecutor: 市价单执行器（含重试机制）
"""

from .base import OrderExecutor, ExecutionResult, OrderStatus
from .market import MarketOrderExecutor

__all__ = [
    "OrderExecutor",
    "ExecutionResult",
    "OrderStatus",
    "MarketOrderExecutor",
]
