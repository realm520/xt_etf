# -*- coding: utf-8 -*-
"""
业务指标收集器（Prometheus 版本）

使用 prometheus_client 收集和导出业务指标（Pull 模式）

Author: ETF Trading Team
Date: 2025-01-22 (Updated)
"""

import logging
from typing import Optional
from prometheus_client import Gauge, Counter, Histogram, CollectorRegistry, REGISTRY

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    统一的指标收集器（Prometheus 版本）

    使用 prometheus_client 收集业务和系统指标
    """

    def __init__(self, registry: Optional[CollectorRegistry] = None):
        """
        初始化指标收集器

        Args:
            registry: Prometheus Registry 实例（默认使用全局 REGISTRY）
        """
        self.registry = registry or REGISTRY

        # ===== 业务指标 =====

        # 风险等级 (1-3)
        self.risk_level_gauge = Gauge(
            name="etf_risk_level",
            documentation="Current risk level (1=high risk, 2=medium, 3=normal)",
            labelnames=["strategy"],
            registry=self.registry
        )

        # 风险子指标
        self.risk_vol_level_gauge = Gauge(
            name="etf_risk_volatility_level",
            documentation="Volatility risk level (1-3)",
            labelnames=["strategy"],
            registry=self.registry
        )

        self.risk_mid_price_level_gauge = Gauge(
            name="etf_risk_mid_price_level",
            documentation="Mid price deviation level (1-3)",
            labelnames=["strategy"],
            registry=self.registry
        )

        self.risk_market_price_level_gauge = Gauge(
            name="etf_risk_market_price_level",
            documentation="Market price deviation level (1-3)",
            labelnames=["strategy"],
            registry=self.registry
        )

        self.risk_orderbook_level_gauge = Gauge(
            name="etf_risk_orderbook_level",
            documentation="Orderbook depth level (1-3)",
            labelnames=["strategy"],
            registry=self.registry
        )

        # 净值
        self.net_value_gauge = Gauge(
            name="etf_net_value",
            documentation="Net asset value of the ETF",
            labelnames=["strategy", "leverage", "direction"],
            registry=self.registry
        )

        # 净值变化率
        self.net_value_change_rate_gauge = Gauge(
            name="etf_net_value_change_rate",
            documentation="Net value change rate",
            labelnames=["strategy", "leverage", "direction"],
            registry=self.registry
        )

        # 止损触发次数
        self.stop_loss_counter = Counter(
            name="etf_stop_loss_triggered_total",
            documentation="Total number of stop loss triggers",
            labelnames=["strategy", "reason"],
            registry=self.registry
        )

        # 持仓盈亏
        self.position_pnl_gauge = Gauge(
            name="etf_position_pnl_usdt",
            documentation="Current position profit and loss in USDT",
            labelnames=["strategy", "symbol"],
            registry=self.registry
        )

        # 持仓数量
        self.position_amount_gauge = Gauge(
            name="etf_position_amount",
            documentation="Current position amount",
            labelnames=["strategy", "symbol"],
            registry=self.registry
        )

        # 账户余额
        self.account_balance_gauge = Gauge(
            name="etf_account_balance_usdt",
            documentation="Account balance in USDT",
            labelnames=["strategy", "asset"],
            registry=self.registry
        )

        # ===== 系统指标 =====

        # API 调用耗时
        self.api_duration_histogram = Histogram(
            name="etf_api_duration_seconds",
            documentation="API call duration in seconds",
            labelnames=["strategy", "endpoint", "status"],
            registry=self.registry,
            buckets=(0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0)
        )

        # API 错误计数
        self.api_errors_counter = Counter(
            name="etf_api_errors_total",
            documentation="Total number of API errors",
            labelnames=["strategy", "endpoint"],
            registry=self.registry
        )

        # API 成功率
        self.api_success_rate_gauge = Gauge(
            name="etf_api_success_rate",
            documentation="API call success rate (0-1)",
            labelnames=["strategy"],
            registry=self.registry
        )

        # Redis 操作计数
        self.redis_ops_counter = Counter(
            name="etf_redis_operations_total",
            documentation="Total number of Redis operations",
            labelnames=["strategy", "operation"],
            registry=self.registry
        )

        # 订单数量统计
        self.orders_total_counter = Counter(
            name="etf_orders_total",
            documentation="Total number of orders placed",
            labelnames=["strategy", "type"],
            registry=self.registry
        )

        self.orders_success_counter = Counter(
            name="etf_orders_success_total",
            documentation="Total number of successful orders",
            labelnames=["strategy", "type"],
            registry=self.registry
        )

        self.orders_failed_counter = Counter(
            name="etf_orders_failed_total",
            documentation="Total number of failed orders",
            labelnames=["strategy", "type"],
            registry=self.registry
        )

        logger.info("✅ MetricsCollector 初始化完成（Prometheus 模式）")

    # ===== 风险相关指标 =====

    def record_risk_level(self, level: int, strategy: str, **kwargs):
        """
        记录风险等级

        Args:
            level: 风险等级 (1=high, 2=medium, 3=normal)
            strategy: 策略名称
            **kwargs: 额外的标签（忽略，保持兼容性）
        """
        self.risk_level_gauge.labels(strategy=strategy).set(level)

    def record_risk_sub_levels(
        self,
        strategy: str,
        vol_level: int,
        mid_price_level: int,
        market_price_level: int,
        orderbook_level: int
    ):
        """
        记录风险子指标

        Args:
            strategy: 策略名称
            vol_level: 波动率等级
            mid_price_level: 中间价偏离等级
            market_price_level: 市场价偏离等级
            orderbook_level: 订单簿深度等级
        """
        self.risk_vol_level_gauge.labels(strategy=strategy).set(vol_level)
        self.risk_mid_price_level_gauge.labels(strategy=strategy).set(mid_price_level)
        self.risk_market_price_level_gauge.labels(strategy=strategy).set(market_price_level)
        self.risk_orderbook_level_gauge.labels(strategy=strategy).set(orderbook_level)

    # ===== 净值相关指标 =====

    def record_net_value(
        self,
        value: float,
        strategy: str,
        leverage: int,
        direction: str,
        change_rate: Optional[float] = None
    ):
        """
        记录净值

        Args:
            value: 净值
            strategy: 策略名称
            leverage: 杠杆倍数
            direction: 方向 (long/short)
            change_rate: 变化率（可选）
        """
        self.net_value_gauge.labels(
            strategy=strategy,
            leverage=str(leverage),
            direction=direction
        ).set(value)

        if change_rate is not None:
            self.net_value_change_rate_gauge.labels(
                strategy=strategy,
                leverage=str(leverage),
                direction=direction
            ).set(change_rate)

    # ===== 止损相关指标 =====

    def record_stop_loss(self, strategy: str, reason: str, loss_rate: float):
        """
        记录止损触发

        Args:
            strategy: 策略名称
            reason: 触发原因 (fixed_threshold/trailing_stop/time_stop)
            loss_rate: 亏损率
        """
        self.stop_loss_counter.labels(
            strategy=strategy,
            reason=reason
        ).inc()

        logger.info(f"📊 Metrics: 止损触发 - {strategy}, 原因={reason}, 亏损率={loss_rate:.2%}")

    # ===== 持仓相关指标 =====

    def record_position(
        self,
        strategy: str,
        amount: float,
        pnl: Optional[float] = None,
        symbol: Optional[str] = None
    ):
        """
        记录持仓信息

        Args:
            strategy: 策略名称
            amount: 持仓数量
            pnl: 盈亏（可选）
            symbol: 交易对（可选）
        """
        symbol = symbol or "unknown"

        self.position_amount_gauge.labels(
            strategy=strategy,
            symbol=symbol
        ).set(amount)

        if pnl is not None:
            self.position_pnl_gauge.labels(
                strategy=strategy,
                symbol=symbol
            ).set(pnl)

    def record_account_balance(self, strategy: str, balance: float, asset: str = "USDT"):
        """
        记录账户余额

        Args:
            strategy: 策略名称
            balance: 余额
            asset: 资产类型
        """
        self.account_balance_gauge.labels(
            strategy=strategy,
            asset=asset
        ).set(balance)

    # ===== API 相关指标 =====

    def record_api_call(
        self,
        duration_ms: float,
        endpoint: str,
        success: bool,
        strategy: Optional[str] = None
    ):
        """
        记录 API 调用

        Args:
            duration_ms: 耗时（毫秒）
            endpoint: API 端点
            success: 是否成功
            strategy: 策略名称（可选）
        """
        strategy = strategy or "unknown"
        status = "success" if success else "error"

        # 转换为秒
        duration_sec = duration_ms / 1000.0

        # 记录耗时
        self.api_duration_histogram.labels(
            strategy=strategy,
            endpoint=endpoint,
            status=status
        ).observe(duration_sec)

        # 记录错误
        if not success:
            self.api_errors_counter.labels(
                strategy=strategy,
                endpoint=endpoint
            ).inc()

    def record_api_success_rate(self, strategy: str, rate: float):
        """
        记录 API 成功率

        Args:
            strategy: 策略名称
            rate: 成功率 (0-1)
        """
        self.api_success_rate_gauge.labels(strategy=strategy).set(rate)

    # ===== Redis 相关指标 =====

    def record_redis_operation(self, operation: str, strategy: Optional[str] = None):
        """
        记录 Redis 操作

        Args:
            operation: 操作类型 (get/set/hset/lpush/etc)
            strategy: 策略名称（可选）
        """
        strategy = strategy or "unknown"

        self.redis_ops_counter.labels(
            strategy=strategy,
            operation=operation
        ).inc()

    # ===== 订单相关指标 =====

    def record_order(self, strategy: str, success: bool, order_type: Optional[str] = None):
        """
        记录订单

        Args:
            strategy: 策略名称
            success: 是否成功
            order_type: 订单类型（可选：limit/market）
        """
        order_type = order_type or "unknown"

        self.orders_total_counter.labels(
            strategy=strategy,
            type=order_type
        ).inc()

        if success:
            self.orders_success_counter.labels(
                strategy=strategy,
                type=order_type
            ).inc()
        else:
            self.orders_failed_counter.labels(
                strategy=strategy,
                type=order_type
            ).inc()
