"""
ETF 对冲系统模块

提供模块化的对冲功能，包括：
- 对冲策略（固定比例、动态对冲）
- 订单执行（市价单、限价单）
- 价格验证（异常检测）
- 监控记录（CSV、日志）

使用示例:
    from etf.hedging import create_hedge_orchestrator

    orchestrator = create_hedge_orchestrator(config, binance_client)
    await orchestrator.check_and_hedge(xt_delta, xt_position)
"""

from .strategies.base import HedgeStrategy, HedgeDecision, NullHedgeStrategy
from .strategies.fixed_ratio import FixedRatioStrategy
from .strategies.dynamic import DynamicRatioStrategy
from .execution.base import OrderExecutor, ExecutionResult, OrderStatus
from .execution.market import MarketOrderExecutor
from .validation.price import PriceValidator, ValidatedPrice, PriceStatus
from .monitoring.monitor import HedgeMonitor
from .orchestrator import HedgeOrchestrator
from .factory import create_hedge_orchestrator, create_strategy, create_executor

__all__ = [
    # 策略
    "HedgeStrategy",
    "HedgeDecision",
    "NullHedgeStrategy",
    "FixedRatioStrategy",
    "DynamicRatioStrategy",
    # 执行
    "OrderExecutor",
    "ExecutionResult",
    "OrderStatus",
    "MarketOrderExecutor",
    # 验证
    "PriceValidator",
    "ValidatedPrice",
    "PriceStatus",
    # 监控
    "HedgeMonitor",
    # 编排
    "HedgeOrchestrator",
    # 工厂
    "create_hedge_orchestrator",
    "create_strategy",
    "create_executor",
]
