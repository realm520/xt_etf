"""
对冲组件工厂

根据配置创建对冲系统的各个组件实例。
"""

import logging
from decimal import Decimal
from typing import Optional, Dict, Any

from .strategies.base import HedgeStrategy, NullHedgeStrategy
from .strategies.fixed_ratio import FixedRatioStrategy
from .execution.base import OrderExecutor
from .execution.market import MarketOrderExecutor
from .validation.price import PriceValidator
from .monitoring.monitor import HedgeMonitor
from .orchestrator import HedgeOrchestrator

logger = logging.getLogger(__name__)


def create_strategy(config: Dict[str, Any]) -> HedgeStrategy:
    """
    根据配置创建对冲策略

    Args:
        config: 策略配置字典
            - type: 策略类型 ("fixed" | "dynamic" | "null")
            - fixed: 固定比例策略配置
                - ratio: 对冲比例
                - min_hedge_value: 最小对冲金额
                - min_hedge_qty: 最小对冲数量
            - dynamic: 动态策略配置（未来扩展）

    Returns:
        HedgeStrategy: 策略实例

    Examples:
        strategy = create_strategy({
            "type": "fixed",
            "fixed": {"ratio": 1.0, "min_hedge_value": 10}
        })
    """
    strategy_type = config.get("type", "fixed")

    if strategy_type == "null" or not config.get("enabled", True):
        logger.info("创建空策略（对冲禁用）")
        return NullHedgeStrategy()

    if strategy_type == "fixed":
        fixed_config = config.get("fixed", {})
        strategy = FixedRatioStrategy(
            ratio=fixed_config.get("ratio", 1.0),
            min_hedge_value=Decimal(str(fixed_config.get("min_hedge_value", 10))),
            min_hedge_qty=Decimal(str(fixed_config.get("min_hedge_qty", 0.001))),
            urgency_base=fixed_config.get("urgency_base", 10000.0),
        )
        logger.info(f"创建固定比例策略: {strategy.get_config()}")
        return strategy

    if strategy_type == "dynamic":
        # 动态策略，后续实现
        try:
            from .strategies.dynamic import DynamicRatioStrategy
            dynamic_config = config.get("dynamic", {})
            strategy = DynamicRatioStrategy(
                base_ratio=dynamic_config.get("base_ratio", 1.0),
                volatility_multiplier=dynamic_config.get("volatility_multiplier", 2.0),
                max_ratio=dynamic_config.get("max_ratio", 3.0),
                min_ratio=dynamic_config.get("min_ratio", 0.5),
                min_hedge_value=Decimal(str(dynamic_config.get("min_hedge_value", 10))),
                min_hedge_qty=Decimal(str(dynamic_config.get("min_hedge_qty", 0.001))),
            )
            logger.info(f"创建动态对冲策略: {strategy.get_config()}")
            return strategy
        except ImportError:
            logger.warning("动态策略模块未实现，回退到固定比例策略")
            return create_strategy({"type": "fixed", **config})

    raise ValueError(f"未知的策略类型: {strategy_type}")


def create_executor(client, config: Dict[str, Any]) -> OrderExecutor:
    """
    根据配置创建订单执行器

    Args:
        client: Binance客户端实例
        config: 执行器配置字典
            - type: 执行器类型 ("market" | "limit")
            - max_retries: 最大重试次数
            - retry_delay: 重试间隔
            - slippage_tolerance: 滑点容忍度

    Returns:
        OrderExecutor: 执行器实例

    Examples:
        executor = create_executor(client, {
            "type": "market",
            "max_retries": 3
        })
    """
    executor_type = config.get("type", "market")

    if executor_type == "market":
        executor = MarketOrderExecutor(
            client=client,
            max_retries=config.get("max_retries", 3),
            retry_delay=config.get("retry_delay", 1.0),
            slippage_tolerance=config.get("slippage_tolerance", 0.01),
            timeout=config.get("timeout", 30.0),
        )
        logger.info(f"创建市价单执行器: {executor.get_config()}")
        return executor

    raise ValueError(f"未知的执行器类型: {executor_type}")


def create_price_validator(client, config: Dict[str, Any]) -> PriceValidator:
    """
    根据配置创建价格验证器

    Args:
        client: Binance客户端实例（可选）
        config: 验证器配置字典
            - enabled: 是否启用验证
            - max_price_change: 最大单次价格变化
            - max_deviation: 最大偏离均值

    Returns:
        PriceValidator: 验证器实例
    """
    if not config.get("enabled", True):
        # 返回一个宽松的验证器
        validator = PriceValidator(
            client=client,
            max_price_change=1.0,  # 100%，相当于禁用
            max_deviation=1.0,
        )
        logger.info("创建宽松价格验证器（验证禁用）")
        return validator

    validator = PriceValidator(
        client=client,
        max_price_change=config.get("max_price_change", 0.05),
        max_deviation=config.get("max_deviation", 0.03),
        history_size=config.get("history_size", 20),
        stale_threshold=config.get("stale_threshold", 60.0),
    )
    logger.info(
        f"创建价格验证器: max_change={config.get('max_price_change', 0.05):.1%}, "
        f"max_deviation={config.get('max_deviation', 0.03):.1%}"
    )
    return validator


def create_monitor(config: Dict[str, Any]) -> HedgeMonitor:
    """
    根据配置创建监控记录器

    Args:
        config: 监控配置字典
            - csv_enabled: 是否启用CSV记录
            - log_dir: 日志目录

    Returns:
        HedgeMonitor: 监控器实例
    """
    monitor = HedgeMonitor(
        log_dir=config.get("log_dir", "logs/hedging"),
        csv_enabled=config.get("csv_enabled", True),
        max_memory_records=config.get("max_memory_records", 1000),
    )
    logger.info(f"创建监控记录器: log_dir={config.get('log_dir', 'logs/hedging')}")
    return monitor


def create_hedge_orchestrator(
    client,
    config: Dict[str, Any],
    symbol: str,
    leverage: int = 3,
) -> HedgeOrchestrator:
    """
    根据配置创建完整的对冲编排器

    Args:
        client: Binance客户端实例
        config: 完整的对冲配置字典
            - enabled: 是否启用对冲
            - strategy: 策略配置
            - execution: 执行器配置
            - price_validation: 价格验证配置
            - monitoring: 监控配置
        symbol: 交易对
        leverage: 杠杆倍数

    Returns:
        HedgeOrchestrator: 编排器实例

    Examples:
        orchestrator = create_hedge_orchestrator(
            client=binance_client,
            config=hedging_config,
            symbol="TONUSDT",
            leverage=3
        )
    """
    if not config.get("enabled", False):
        logger.info(f"对冲禁用，创建空编排器: {symbol}")
        # 返回一个使用空策略的编排器
        config = {
            "strategy": {"type": "null"},
            "execution": {},
            "price_validation": {"enabled": False},
            "monitoring": {},
        }

    # 创建各组件
    strategy = create_strategy(config.get("strategy", {}))
    executor = create_executor(client, config.get("execution", {}))
    price_validator = create_price_validator(client, config.get("price_validation", {}))
    monitor = create_monitor(config.get("monitoring", {}))

    # 创建编排器
    orchestrator = HedgeOrchestrator(
        strategy=strategy,
        executor=executor,
        price_validator=price_validator,
        monitor=monitor,
        symbol=symbol,
        leverage=leverage,
        min_confidence=config.get("min_confidence", 0.5),
    )

    logger.info(
        f"对冲编排器创建完成: symbol={symbol}, leverage={leverage}, "
        f"strategy={strategy.get_name()}"
    )

    return orchestrator
