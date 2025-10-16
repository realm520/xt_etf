# -*- coding: utf-8 -*-
"""
业务指标收集器

使用 OpenTelemetry Metrics API 收集和导出业务指标

Author: ETF Trading Team
Date: 2025-01-16
"""

import logging
from typing import Optional, Dict, Any
from opentelemetry import metrics

logger = logging.getLogger(__name__)


class MetricsCollector:
    """
    统一的指标收集器

    使用 OpenTelemetry Metrics API 收集业务和系统指标
    """

    def __init__(self, meter: metrics.Meter):
        """
        初始化指标收集器

        Args:
            meter: OpenTelemetry Meter 实例
        """
        self.meter = meter

        # ===== 业务指标 =====

        # 风险等级 (1-3)
        self.risk_level_gauge = meter.create_gauge(
            name="etf.risk.level",
            description="Current risk level (1=high risk, 2=medium, 3=normal)",
            unit="1"
        )

        # 风险子指标
        self.risk_vol_level_gauge = meter.create_gauge(
            name="etf.risk.volatility_level",
            description="Volatility risk level (1-3)",
            unit="1"
        )

        self.risk_mid_price_level_gauge = meter.create_gauge(
            name="etf.risk.mid_price_level",
            description="Mid price deviation level (1-3)",
            unit="1"
        )

        self.risk_market_price_level_gauge = meter.create_gauge(
            name="etf.risk.market_price_level",
            description="Market price deviation level (1-3)",
            unit="1"
        )

        self.risk_orderbook_level_gauge = meter.create_gauge(
            name="etf.risk.orderbook_level",
            description="Orderbook depth level (1-3)",
            unit="1"
        )

        # 净值
        self.net_value_gauge = meter.create_gauge(
            name="etf.net_value",
            description="Net asset value of the ETF",
            unit="1"
        )

        # 净值变化率
        self.net_value_change_rate_gauge = meter.create_gauge(
            name="etf.net_value.change_rate",
            description="Net value change rate",
            unit="1"
        )

        # 止损触发次数
        self.stop_loss_counter = meter.create_counter(
            name="etf.stop_loss.triggered",
            description="Total number of stop loss triggers",
            unit="1"
        )

        # 持仓盈亏
        self.position_pnl_gauge = meter.create_gauge(
            name="etf.position.pnl",
            description="Current position profit and loss",
            unit="USDT"
        )

        # 持仓数量
        self.position_amount_gauge = meter.create_gauge(
            name="etf.position.amount",
            description="Current position amount",
            unit="1"
        )

        # 账户余额
        self.account_balance_gauge = meter.create_gauge(
            name="etf.account.balance",
            description="Account balance",
            unit="USDT"
        )

        # ===== 系统指标 =====

        # API 调用耗时直方图
        self.api_duration_histogram = meter.create_histogram(
            name="etf.api.duration",
            description="API call duration in milliseconds",
            unit="ms"
        )

        # API 错误计数
        self.api_errors_counter = meter.create_counter(
            name="etf.api.errors",
            description="Total number of API errors",
            unit="1"
        )

        # API 成功率
        self.api_success_rate_gauge = meter.create_gauge(
            name="etf.api.success_rate",
            description="API call success rate (0-1)",
            unit="1"
        )

        # Redis 操作计数
        self.redis_ops_counter = meter.create_counter(
            name="etf.redis.operations",
            description="Total number of Redis operations",
            unit="1"
        )

        # 订单数量统计
        self.orders_total_counter = meter.create_counter(
            name="etf.orders.total",
            description="Total number of orders placed",
            unit="1"
        )

        self.orders_success_counter = meter.create_counter(
            name="etf.orders.success",
            description="Total number of successful orders",
            unit="1"
        )

        self.orders_failed_counter = meter.create_counter(
            name="etf.orders.failed",
            description="Total number of failed orders",
            unit="1"
        )

        logger.info("✅ MetricsCollector 初始化完成")

    # ===== 风险相关指标 =====

    def record_risk_level(self, level: int, strategy: str, **kwargs):
        """
        记录风险等级

        Args:
            level: 风险等级 (1=high, 2=medium, 3=normal)
            strategy: 策略名称
            **kwargs: 额外的标签
        """
        labels = {"strategy": strategy, **kwargs}
        self.risk_level_gauge.set(level, labels)

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
        labels = {"strategy": strategy}
        self.risk_vol_level_gauge.set(vol_level, labels)
        self.risk_mid_price_level_gauge.set(mid_price_level, labels)
        self.risk_market_price_level_gauge.set(market_price_level, labels)
        self.risk_orderbook_level_gauge.set(orderbook_level, labels)

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
        labels = {
            "strategy": strategy,
            "leverage": str(leverage),
            "direction": direction
        }
        self.net_value_gauge.set(value, labels)

        if change_rate is not None:
            self.net_value_change_rate_gauge.set(change_rate, labels)

    # ===== 止损相关指标 =====

    def record_stop_loss(self, strategy: str, reason: str, loss_rate: float):
        """
        记录止损触发

        Args:
            strategy: 策略名称
            reason: 触发原因 (fixed_threshold/trailing_stop/time_stop)
            loss_rate: 亏损率
        """
        labels = {
            "strategy": strategy,
            "reason": reason
        }
        self.stop_loss_counter.add(1, labels)

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
        labels = {"strategy": strategy}
        if symbol:
            labels["symbol"] = symbol

        self.position_amount_gauge.set(amount, labels)

        if pnl is not None:
            self.position_pnl_gauge.set(pnl, labels)

    def record_account_balance(self, strategy: str, balance: float, asset: str = "USDT"):
        """
        记录账户余额

        Args:
            strategy: 策略名称
            balance: 余额
            asset: 资产类型
        """
        labels = {"strategy": strategy, "asset": asset}
        self.account_balance_gauge.set(balance, labels)

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
        labels = {
            "endpoint": endpoint,
            "status": "success" if success else "error"
        }
        if strategy:
            labels["strategy"] = strategy

        # 记录耗时
        self.api_duration_histogram.record(duration_ms, labels)

        # 记录错误
        if not success:
            self.api_errors_counter.add(1, labels)

    def record_api_success_rate(self, strategy: str, rate: float):
        """
        记录 API 成功率

        Args:
            strategy: 策略名称
            rate: 成功率 (0-1)
        """
        labels = {"strategy": strategy}
        self.api_success_rate_gauge.set(rate, labels)

    # ===== Redis 相关指标 =====

    def record_redis_operation(self, operation: str, strategy: Optional[str] = None):
        """
        记录 Redis 操作

        Args:
            operation: 操作类型 (get/set/hset/lpush/etc)
            strategy: 策略名称（可选）
        """
        labels = {"operation": operation}
        if strategy:
            labels["strategy"] = strategy

        self.redis_ops_counter.add(1, labels)

    # ===== 订单相关指标 =====

    def record_order(self, strategy: str, success: bool, order_type: Optional[str] = None):
        """
        记录订单

        Args:
            strategy: 策略名称
            success: 是否成功
            order_type: 订单类型（可选：limit/market）
        """
        labels = {"strategy": strategy}
        if order_type:
            labels["type"] = order_type

        self.orders_total_counter.add(1, labels)

        if success:
            self.orders_success_counter.add(1, labels)
        else:
            self.orders_failed_counter.add(1, labels)
