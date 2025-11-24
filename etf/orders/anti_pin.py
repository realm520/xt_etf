"""
反针对订单类型

用于防止价格异常波动的保护性订单。
"""

from dataclasses import dataclass
from datetime import datetime
from .types import BaseOrder, OrderType


@dataclass
class AntiPinOrder(BaseOrder):
    """
    反针对订单

    在远离市场价格的位置放置订单，防止价格异常波动和针对性交易。

    Attributes:
        deviation_rate: 偏离率（例如0.05表示偏离5%）
        anti_pin_generation: 生成批次号（用于管理订单生命周期）
    """

    order_type: OrderType = OrderType.ANTI_PIN
    deviation_rate: float = 0.05  # 偏离率（5%）
    anti_pin_generation: int = 0  # 生成批次号

    def __post_init__(self):
        """初始化后自动生成client_order_id"""
        if not self.client_order_id:
            timestamp = int(datetime.now().timestamp() * 1000)
            side_str = self.side.value.lower()
            self.client_order_id = (
                f"antipin_{self.symbol}_{side_str}_G{self.anti_pin_generation}_{timestamp}"
            )

    def to_dict(self):
        """扩展父类的to_dict方法，添加反针对订单特有字段"""
        data = super().to_dict()
        data["deviation_rate"] = self.deviation_rate
        data["anti_pin_generation"] = self.anti_pin_generation
        return data

    @classmethod
    def from_dict(cls, data):
        """从字典创建反针对订单对象"""
        # 移除父类不需要的字段
        deviation_rate = data.pop("deviation_rate", 0.05)
        anti_pin_generation = data.pop("anti_pin_generation", 0)

        # 调用父类from_dict创建基础订单
        base_order = super().from_dict(data)

        # 创建反针对订单
        return cls(
            symbol=base_order.symbol,
            side=base_order.side,
            price=base_order.price,
            quantity=base_order.quantity,
            order_type=OrderType.ANTI_PIN,
            client_order_id=base_order.client_order_id,
            order_id=base_order.order_id,
            status=base_order.status,
            filled_quantity=base_order.filled_quantity,
            created_at=base_order.created_at,
            updated_at=base_order.updated_at,
            metadata=base_order.metadata,
            deviation_rate=deviation_rate,
            anti_pin_generation=anti_pin_generation,
        )

    def is_outdated(self, current_generation: int) -> bool:
        """
        判断订单是否已过时

        Args:
            current_generation: 当前生成批次号

        Returns:
            True if订单批次号小于当前批次号
        """
        return self.anti_pin_generation < current_generation
