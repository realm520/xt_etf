"""
对冲编排器

协调各组件完成对冲工作流程：
1. 验证价格
2. 计算对冲决策
3. 执行对冲订单
4. 记录监控数据
"""

import logging
from decimal import Decimal
from typing import Optional

from .strategies.base import HedgeStrategy, HedgeDecision
from .execution.base import OrderExecutor, ExecutionResult, OrderStatus
from .validation.price import PriceValidator, PriceStatus
from .monitoring.monitor import HedgeMonitor

logger = logging.getLogger(__name__)


class HedgeOrchestrator:
    """
    对冲编排器

    协调策略、执行、验证、监控各组件，完成对冲工作流程。

    工作流程:
    1. 获取并验证价格
    2. 计算对冲需求（包含累积的剩余量）
    3. 执行对冲订单
    4. 更新状态和监控记录

    Args:
        strategy: 对冲策略实例
        executor: 订单执行器实例
        price_validator: 价格验证器实例
        monitor: 监控记录器实例
        symbol: 交易对 (例如: "TONUSDT")
        leverage: 杠杆倍数
        min_confidence: 最低价格置信度，低于此值不执行对冲

    Examples:
        orchestrator = HedgeOrchestrator(
            strategy=FixedRatioStrategy(ratio=1.0),
            executor=MarketOrderExecutor(client),
            price_validator=PriceValidator(client),
            monitor=HedgeMonitor(),
            symbol="TONUSDT",
            leverage=3
        )
        result = await orchestrator.check_and_hedge(xt_delta, xt_position)
    """

    def __init__(
        self,
        strategy: HedgeStrategy,
        executor: OrderExecutor,
        price_validator: PriceValidator,
        monitor: HedgeMonitor,
        symbol: str,
        leverage: int = 3,
        min_confidence: float = 0.5,
    ):
        self.strategy = strategy
        self.executor = executor
        self.price_validator = price_validator
        self.monitor = monitor
        self.symbol = symbol
        self.leverage = leverage
        self.min_confidence = min_confidence

        # 状态跟踪
        self.current_hedge_position = Decimal("0")  # 当前对冲持仓金额
        self.remaining_qty = Decimal("0")            # 剩余未对冲数量
        self.last_price = Decimal("0")               # 最后有效价格

        logger.info(
            f"HedgeOrchestrator 初始化: symbol={symbol}, leverage={leverage}, "
            f"strategy={strategy.get_name()}, executor={executor.get_name()}"
        )

    async def check_and_hedge(
        self,
        xt_position_delta: Decimal,
        xt_total_position: Optional[Decimal] = None,
        current_price: Optional[Decimal] = None,
    ) -> Optional[ExecutionResult]:
        """
        检查并执行对冲

        Args:
            xt_position_delta: XT端持仓变化金额 (USDT)
            xt_total_position: XT端总持仓金额 (可选，用于一致性检查)
            current_price: 当前价格（可选，如不提供则从验证器获取）

        Returns:
            ExecutionResult: 执行结果，如果不需要对冲则返回None
        """
        # 1. 验证价格
        validated = self.price_validator.validate_price(self.symbol, current_price)

        if validated.status == PriceStatus.UNAVAILABLE:
            logger.warning(f"价格不可用，跳过对冲: {validated.reason}")
            self.monitor.record_skip(self.symbol, validated.reason, validated.status.value)
            return None

        if validated.confidence < self.min_confidence:
            logger.warning(
                f"价格置信度过低 ({validated.confidence:.2f} < {self.min_confidence}), "
                f"跳过对冲: {validated.reason}"
            )
            self.monitor.record_skip(
                self.symbol,
                f"置信度过低: {validated.confidence:.2f}",
                validated.status.value
            )
            return None

        price = validated.price
        self.last_price = price

        # 2. 计算包含剩余量的总delta
        # remaining_qty * price = 上次未完成的对冲金额
        total_delta = xt_position_delta
        if self.remaining_qty != 0 and price > 0:
            remaining_value = self.remaining_qty * price
            total_delta = xt_position_delta + remaining_value
            if abs(remaining_value) > Decimal("1"):
                logger.info(
                    f"包含剩余量: delta={xt_position_delta:.2f}, "
                    f"remaining={remaining_value:.2f}, total={total_delta:.2f}"
                )

        # 3. 计算对冲决策
        decision = self.strategy.calculate_hedge(
            xt_position_delta=total_delta,
            current_hedge_position=self.current_hedge_position,
            price=price,
            leverage=self.leverage,
        )

        # 记录决策
        self.monitor.record_decision(
            symbol=self.symbol,
            strategy_name=self.strategy.get_name(),
            decision=decision,
            xt_position_delta=total_delta,
            current_hedge_position=self.current_hedge_position,
            price=price,
            price_status=validated.status.value,
            price_confidence=validated.confidence,
        )

        if not decision.should_hedge:
            logger.debug(f"无需对冲: {decision.reason}")
            return None

        # 4. 执行对冲
        result = await self.executor.execute(
            symbol=self.symbol,
            side=decision.direction,
            quantity=decision.amount,
            price=price,  # 作为参考价格用于滑点计算
        )

        # 5. 更新状态
        if result.success:
            # 更新对冲持仓
            hedge_value = result.filled_qty * result.filled_price
            if decision.direction == "BUY":
                self.current_hedge_position -= hedge_value
            else:
                self.current_hedge_position += hedge_value

            # 计算剩余量
            if result.remaining_qty > 0:
                self.remaining_qty = result.remaining_qty
                if decision.direction == "BUY":
                    self.remaining_qty = -self.remaining_qty
            else:
                self.remaining_qty = Decimal("0")

            logger.info(
                f"对冲状态更新: position={self.current_hedge_position:.2f}, "
                f"remaining={self.remaining_qty:.6f}"
            )
        else:
            # 执行失败，累积剩余量
            if decision.direction == "BUY":
                self.remaining_qty -= decision.amount
            else:
                self.remaining_qty += decision.amount
            logger.warning(f"对冲失败，累积剩余量: {self.remaining_qty:.6f}")

        # 6. 记录执行结果
        self.monitor.record_execution(
            symbol=self.symbol,
            strategy_name=self.strategy.get_name(),
            decision=decision,
            result=result,
            xt_position_delta=total_delta,
            current_hedge_position=self.current_hedge_position,
            price=price,
            price_status=validated.status.value,
            price_confidence=validated.confidence,
        )

        return result

    def update_position(self, hedge_position: Decimal) -> None:
        """
        更新当前对冲持仓

        用于与交易所同步持仓状态。

        Args:
            hedge_position: 交易所报告的对冲持仓金额
        """
        old_position = self.current_hedge_position
        self.current_hedge_position = hedge_position
        logger.info(
            f"对冲持仓更新: {old_position:.2f} → {hedge_position:.2f}"
        )

    def reset_remaining(self) -> None:
        """重置剩余量"""
        if self.remaining_qty != 0:
            logger.info(f"重置剩余量: {self.remaining_qty:.6f} → 0")
            self.remaining_qty = Decimal("0")

    def get_status(self) -> dict:
        """获取当前状态"""
        return {
            "symbol": self.symbol,
            "leverage": self.leverage,
            "strategy": self.strategy.get_name(),
            "executor": self.executor.get_name(),
            "current_hedge_position": float(self.current_hedge_position),
            "remaining_qty": float(self.remaining_qty),
            "last_price": float(self.last_price),
            "stats": self.monitor.get_stats().to_dict(),
        }

    def get_config(self) -> dict:
        """获取配置信息"""
        return {
            "symbol": self.symbol,
            "leverage": self.leverage,
            "min_confidence": self.min_confidence,
            "strategy": self.strategy.get_config(),
            "executor": self.executor.get_config(),
        }
