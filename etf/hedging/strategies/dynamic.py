"""
动态对冲策略

根据市场波动率动态调整对冲比例：
- 高波动率时增加对冲比例（更保守）
- 低波动率时降低对冲比例（更激进）
"""

import logging
from decimal import Decimal
from typing import Optional

from .base import HedgeStrategy, HedgeDecision

logger = logging.getLogger(__name__)


class DynamicRatioStrategy(HedgeStrategy):
    """
    动态对冲策略

    根据波动率动态调整对冲比例：
        adjusted_ratio = base_ratio * (1 + volatility * volatility_multiplier)
        adjusted_ratio = clamp(adjusted_ratio, min_ratio, max_ratio)

    适用场景：
    - 市场波动较大时需要更完全的对冲
    - 希望在低波动时提高资金效率
    - 需要自动适应市场状态的策略

    Args:
        base_ratio: 基础对冲比例，默认1.0
        volatility_multiplier: 波动率乘数，默认2.0
        max_ratio: 最大对冲比例，默认3.0
        min_ratio: 最小对冲比例，默认0.5
        min_hedge_value: 最小对冲金额(USDT)
        min_hedge_qty: 最小对冲数量
        urgency_base: 紧急程度基准值(USDT)

    Examples:
        # 基础对冲，波动率高时增加
        strategy = DynamicRatioStrategy(base_ratio=1.0)

        # 保守策略，最低1.5倍对冲
        strategy = DynamicRatioStrategy(base_ratio=1.5, min_ratio=1.0)
    """

    def __init__(
        self,
        base_ratio: float = 1.0,
        volatility_multiplier: float = 2.0,
        max_ratio: float = 3.0,
        min_ratio: float = 0.5,
        min_hedge_value: Decimal = Decimal("10"),
        min_hedge_qty: Decimal = Decimal("0.001"),
        urgency_base: float = 10000.0,
    ):
        if base_ratio <= 0:
            raise ValueError(f"base_ratio must be positive, got {base_ratio}")
        if min_ratio <= 0:
            raise ValueError(f"min_ratio must be positive, got {min_ratio}")
        if max_ratio < min_ratio:
            raise ValueError(f"max_ratio ({max_ratio}) must be >= min_ratio ({min_ratio})")
        if volatility_multiplier < 0:
            raise ValueError(f"volatility_multiplier must be non-negative, got {volatility_multiplier}")

        self.base_ratio = base_ratio
        self.volatility_multiplier = volatility_multiplier
        self.max_ratio = max_ratio
        self.min_ratio = min_ratio
        self.min_hedge_value = min_hedge_value
        self.min_hedge_qty = min_hedge_qty
        self.urgency_base = urgency_base

        # 最后使用的比例（用于日志和监控）
        self._last_ratio = base_ratio

        logger.info(
            f"DynamicRatioStrategy 初始化: base_ratio={base_ratio}, "
            f"volatility_multiplier={volatility_multiplier}, "
            f"range=[{min_ratio}, {max_ratio}]"
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
        计算动态对冲决策

        Args:
            xt_position_delta: XT端持仓变化金额 (USDT)
            current_hedge_position: 当前对冲持仓金额 (USDT)
            price: 当前价格
            leverage: ETF杠杆倍数
            volatility: 波动率 (0-1)，如果为None则使用base_ratio

        Returns:
            HedgeDecision: 对冲决策
        """
        # 边界情况检查
        if price <= 0:
            logger.warning(f"价格无效: {price}")
            return self._no_hedge_decision("价格无效")

        if xt_position_delta == 0 and current_hedge_position == 0:
            return self._no_hedge_decision("无持仓变化")

        # 计算动态比例
        ratio = self._calculate_ratio(volatility)
        self._last_ratio = ratio

        # 计算目标对冲金额
        target_hedge_value = xt_position_delta * Decimal(str(ratio))

        # 计算需要对冲的增量
        hedge_delta = target_hedge_value - current_hedge_position

        # 如果变化很小，不需要对冲
        if abs(hedge_delta) < self.min_hedge_value:
            return self._no_hedge_decision(
                f"对冲金额 {abs(hedge_delta):.2f} < 最小值 {self.min_hedge_value}"
            )

        # 确定方向
        direction = "SELL" if hedge_delta > 0 else "BUY"

        # 计算对冲数量
        amount = abs(hedge_delta) / price

        # 检查最小数量
        if amount < self.min_hedge_qty:
            return self._no_hedge_decision(
                f"对冲数量 {amount:.6f} < 最小值 {self.min_hedge_qty}"
            )

        # 计算紧急程度
        # 动态策略：波动率高时更紧急
        base_urgency = min(1.0, float(abs(hedge_delta)) / self.urgency_base)
        if volatility is not None:
            urgency = min(1.0, base_urgency * (1 + volatility))
        else:
            urgency = base_urgency

        reason = (
            f"动态对冲: ratio={ratio:.2f} (base={self.base_ratio}, "
            f"vol={volatility:.2%} if volatility else 'N/A')), "
            f"xt_delta={xt_position_delta:.2f}, "
            f"target={target_hedge_value:.2f}"
        )

        logger.info(
            f"动态对冲决策: {direction} {amount:.6f} @ {price}, "
            f"ratio={ratio:.2f}, urgency={urgency:.2f}"
        )

        return HedgeDecision(
            should_hedge=True,
            direction=direction,
            amount=amount,
            urgency=urgency,
            reason=reason,
            estimated_value=abs(hedge_delta)
        )

    def _calculate_ratio(self, volatility: Optional[float]) -> float:
        """
        根据波动率计算对冲比例

        公式: ratio = base_ratio * (1 + volatility * volatility_multiplier)
        结果限制在 [min_ratio, max_ratio] 范围内
        """
        if volatility is None or volatility <= 0:
            return self.base_ratio

        # 计算调整后的比例
        adjustment = 1 + volatility * self.volatility_multiplier
        ratio = self.base_ratio * adjustment

        # 限制范围
        ratio = max(self.min_ratio, min(self.max_ratio, ratio))

        return ratio

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
        return f"DynamicRatio(base={self.base_ratio}, range=[{self.min_ratio},{self.max_ratio}])"

    def get_config(self) -> dict:
        return {
            "name": self.get_name(),
            "type": "dynamic",
            "base_ratio": self.base_ratio,
            "volatility_multiplier": self.volatility_multiplier,
            "max_ratio": self.max_ratio,
            "min_ratio": self.min_ratio,
            "min_hedge_value": float(self.min_hedge_value),
            "min_hedge_qty": float(self.min_hedge_qty),
            "urgency_base": self.urgency_base,
            "last_ratio": self._last_ratio,
        }

    @property
    def current_ratio(self) -> float:
        """获取最后使用的对冲比例"""
        return self._last_ratio
