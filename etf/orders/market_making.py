"""
做市订单类型

用于市场做市业务的订单类型，包含订单簿档位信息。
"""

from dataclasses import dataclass
from datetime import datetime
from .types import BaseOrder, OrderType


@dataclass
class MarketMakingOrder(BaseOrder):
    """
    做市订单

    用于在订单簿中提供流动性的订单。通过layer_index标识订单在订单簿中的档位。

    Attributes:
        layer_index: 订单簿档位（0=最优价格，1=第二档，以此类推）
    """

    order_type: OrderType = OrderType.MARKET_MAKING
    layer_index: int = 0  # 订单簿档位（0=最优价格）

    def __post_init__(self):
        """初始化后自动生成client_order_id"""
        if not self.client_order_id:
            timestamp = int(datetime.now().timestamp() * 1000)
            side_str = self.side.value.lower()
            self.client_order_id = (
                f"mm_{self.symbol}_{side_str}_L{self.layer_index}_{timestamp}"
            )

    def to_dict(self):
        """扩展父类的to_dict方法，添加做市订单特有字段"""
        data = super().to_dict()
        data["layer_index"] = self.layer_index
        return data

    @classmethod
    def from_dict(cls, data):
        """从字典创建做市订单对象"""
        # 移除父类不需要的字段
        layer_index = data.pop("layer_index", 0)

        # 调用父类from_dict创建基础订单
        base_order = super().from_dict(data)

        # 创建做市订单
        return cls(
            symbol=base_order.symbol,
            side=base_order.side,
            price=base_order.price,
            quantity=base_order.quantity,
            order_type=OrderType.MARKET_MAKING,
            client_order_id=base_order.client_order_id,
            order_id=base_order.order_id,
            status=base_order.status,
            filled_quantity=base_order.filled_quantity,
            created_at=base_order.created_at,
            updated_at=base_order.updated_at,
            metadata=base_order.metadata,
            layer_index=layer_index,
        )
