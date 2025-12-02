"""
对冲策略抽象基类

定义对冲策略的统一接口，支持多种对冲策略的实现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional
from datetime import datetime


@dataclass
class HedgeDecision:
    """
    对冲决策数据类

    包含对冲策略计算后的决策信息。

    Attributes:
        should_hedge: 是否需要执行对冲
        direction: 对冲方向 ('BUY' 或 'SELL')
        amount: 对冲数量（交易对的基础货币数量）
        urgency: 紧急程度 (0-1, 1表示最紧急)
        reason: 对冲原因说明
        estimated_value: 预估对冲金额 (USDT)
        timestamp: 决策时间戳
    """
    should_hedge: bool
    direction: str  # 'BUY' or 'SELL'
    amount: Decimal
    urgency: float
    reason: str
    estimated_value: Decimal
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """验证决策数据"""
        if self.direction not in ('BUY', 'SELL'):
            raise ValueError(f"direction must be 'BUY' or 'SELL', got {self.direction}")
        if self.urgency < 0 or self.urgency > 1:
            raise ValueError(f"urgency must be between 0 and 1, got {self.urgency}")
        if self.amount < 0:
            raise ValueError(f"amount must be non-negative, got {self.amount}")

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "should_hedge": self.should_hedge,
            "direction": self.direction,
            "amount": float(self.amount),
            "urgency": self.urgency,
            "reason": self.reason,
            "estimated_value": float(self.estimated_value),
            "timestamp": self.timestamp.isoformat(),
        }


class HedgeStrategy(ABC):
    """
    对冲策略抽象基类

    所有对冲策略必须实现此接口，提供统一的对冲计算逻辑。

    策略类型:
    - FixedRatioStrategy: 固定比例对冲 (ratio=1.0 表示金额对冲)
    - DynamicRatioStrategy: 动态对冲 (根据波动率调整比例)

    使用示例:
        strategy = FixedRatioStrategy(ratio=1.0)
        decision = strategy.calculate_hedge(
            xt_position_delta=Decimal("-10000"),
            current_hedge_position=Decimal("0"),
            price=Decimal("2.5"),
            leverage=3
        )
        if decision.should_hedge:
            print(f"需要 {decision.direction} {decision.amount} 进行对冲")
    """

    @abstractmethod
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
                - 正值表示做市商买入（需要卖出对冲）
                - 负值表示做市商卖出（需要买入对冲）
            current_hedge_position: 当前对冲持仓金额 (USDT)
            price: 当前价格（对冲标的）
            leverage: ETF杠杆倍数 (3 或 5)
            volatility: 可选的波动率数据（动态策略使用）

        Returns:
            HedgeDecision: 对冲决策，包含是否对冲、方向、数量等信息
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        获取策略名称

        Returns:
            策略名称字符串，用于日志和监控
        """
        pass

    def get_config(self) -> dict:
        """
        获取策略配置

        Returns:
            策略当前配置的字典表示
        """
        return {"name": self.get_name()}


class NullHedgeStrategy(HedgeStrategy):
    """
    空策略（禁用对冲）

    用于配置关闭对冲功能时的占位实现。
    """

    def calculate_hedge(
        self,
        xt_position_delta: Decimal,
        current_hedge_position: Decimal,
        price: Decimal,
        leverage: int,
        volatility: Optional[float] = None
    ) -> HedgeDecision:
        return HedgeDecision(
            should_hedge=False,
            direction="BUY",
            amount=Decimal("0"),
            urgency=0.0,
            reason="对冲功能已禁用",
            estimated_value=Decimal("0")
        )

    def get_name(self) -> str:
        return "NullStrategy"
