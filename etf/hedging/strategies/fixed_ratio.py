"""
固定比例对冲策略

支持两种模式:
1. 金额对冲 (ratio=1.0): 对冲金额 = XT敞口金额
2. Delta对冲 (ratio=leverage): 对冲金额 = XT敞口金额 * 杠杆
"""

import logging
from decimal import Decimal
from typing import Optional

from .base import HedgeStrategy, HedgeDecision

logger = logging.getLogger(__name__)


class FixedRatioStrategy(HedgeStrategy):
    """
    固定比例对冲策略

    根据固定比例计算对冲金额，适用于:
    - 金额对冲 (ratio=1.0): 1:1 对冲，资金效率高但有杠杆敞口
    - Delta对冲 (ratio=3.0/5.0): 完全对冲杠杆风险，资金占用高

    计算逻辑:
        target_hedge = xt_position_delta * ratio
        hedge_delta = target_hedge - current_hedge_position
        amount = hedge_delta / price

    对冲方向:
        - XT买入（delta > 0）→ 做市商需要卖出对冲 → SELL
        - XT卖出（delta < 0）→ 做市商需要买入对冲 → BUY

    Args:
        ratio: 对冲比例，默认1.0（金额对冲）
        min_hedge_value: 最小对冲金额(USDT)，低于此值不执行
        min_hedge_qty: 最小对冲数量，低于此值不执行
        urgency_base: 紧急程度基准值(USDT)，用于计算urgency

    Examples:
        # 金额对冲
        strategy = FixedRatioStrategy(ratio=1.0)

        # 3倍杠杆完全对冲
        strategy = FixedRatioStrategy(ratio=3.0)
    """

    def __init__(
        self,
        ratio: float = 1.0,
        min_hedge_value: Decimal = Decimal("10"),
        min_hedge_qty: Decimal = Decimal("0.001"),
        urgency_base: float = 10000.0,
    ):
        if ratio <= 0:
            raise ValueError(f"ratio must be positive, got {ratio}")
        if min_hedge_value < 0:
            raise ValueError(f"min_hedge_value must be non-negative, got {min_hedge_value}")
        if min_hedge_qty < 0:
            raise ValueError(f"min_hedge_qty must be non-negative, got {min_hedge_qty}")

        self.ratio = ratio
        self.min_hedge_value = min_hedge_value
        self.min_hedge_qty = min_hedge_qty
        self.urgency_base = urgency_base

        logger.info(
            f"FixedRatioStrategy 初始化: ratio={ratio}, "
            f"min_hedge_value={min_hedge_value}, min_hedge_qty={min_hedge_qty}"
        )

    def calculate_hedge(
        self,
        xt_position_delta: Decimal,
        current_hedge_position: Decimal,
        price: Decimal,
        leverage: int,
        volatility: Optional[float] = None
    ) -> HedgeDecision:
        """
        计算对冲决策

        Args:
            xt_position_delta: XT端持仓变化金额 (USDT)
            current_hedge_position: 当前对冲持仓金额 (USDT)
            price: 当前价格
            leverage: ETF杠杆倍数（本策略不使用）
            volatility: 波动率（本策略不使用）

        Returns:
            HedgeDecision: 对冲决策
        """
        # 边界情况检查
        if price <= 0:
            logger.warning(f"价格无效: {price}")
            return self._no_hedge_decision("价格无效")

        if xt_position_delta == 0 and current_hedge_position == 0:
            return self._no_hedge_decision("无持仓变化")

        # 计算目标对冲金额
        target_hedge_value = xt_position_delta * Decimal(str(self.ratio))

        # 计算需要对冲的增量
        # hedge_delta > 0: 需要增加对冲（卖出）
        # hedge_delta < 0: 需要减少对冲（买入）
        hedge_delta = target_hedge_value - current_hedge_position

        # 如果变化很小，不需要对冲
        if abs(hedge_delta) < self.min_hedge_value:
            return self._no_hedge_decision(
                f"对冲金额 {abs(hedge_delta):.2f} < 最小值 {self.min_hedge_value}"
            )

        # 确定方向: XT敞口为正（买入）需要卖出对冲，反之亦然
        direction = "SELL" if hedge_delta > 0 else "BUY"

        # 计算对冲数量
        amount = abs(hedge_delta) / price

        # 检查最小数量
        if amount < self.min_hedge_qty:
            return self._no_hedge_decision(
                f"对冲数量 {amount:.6f} < 最小值 {self.min_hedge_qty}"
            )

        # 计算紧急程度: 敞口越大越紧急
        urgency = min(1.0, float(abs(hedge_delta)) / self.urgency_base)

        reason = (
            f"固定比例对冲: ratio={self.ratio}, "
            f"xt_delta={xt_position_delta:.2f}, "
            f"current_hedge={current_hedge_position:.2f}, "
            f"target={target_hedge_value:.2f}"
        )

        logger.info(
            f"对冲决策: {direction} {amount:.6f} @ {price}, "
            f"预估金额={abs(hedge_delta):.2f} USDT, urgency={urgency:.2f}"
        )

        return HedgeDecision(
            should_hedge=True,
            direction=direction,
            amount=amount,
            urgency=urgency,
            reason=reason,
            estimated_value=abs(hedge_delta)
        )

    def _no_hedge_decision(self, reason: str) -> HedgeDecision:
        """生成不执行对冲的决策"""
        return HedgeDecision(
            should_hedge=False,
            direction="BUY",
            amount=Decimal("0"),
            urgency=0.0,
            reason=reason,
            estimated_value=Decimal("0")
        )

    def get_name(self) -> str:
        return f"FixedRatio({self.ratio})"

    def get_config(self) -> dict:
        return {
            "name": self.get_name(),
            "type": "fixed",
            "ratio": self.ratio,
            "min_hedge_value": float(self.min_hedge_value),
            "min_hedge_qty": float(self.min_hedge_qty),
            "urgency_base": self.urgency_base,
        }
