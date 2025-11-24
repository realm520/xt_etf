"""
洗盘订单类型

用于维护K线连续性和交易活跃度的订单类型。
"""

from dataclasses import dataclass
from datetime import datetime
from .types import BaseOrder, OrderType


@dataclass
class WashTradingOrder(BaseOrder):
    """
    洗盘订单

    用于维护K线连续性和市场活跃度的订单。通过micro_trade_index标识分笔成交索引。

    Attributes:
        micro_trade_index: 分笔成交索引（0-6，一批通常包含3-7笔微交易）
        batch_id: 批次ID（同一批次的微交易共享此ID）
    """

    order_type: OrderType = OrderType.WASH_TRADING
    micro_trade_index: int = 0  # 分笔成交索引（0-6）
    batch_id: str = ""  # 批次ID

    def __post_init__(self):
        """初始化后自动生成client_order_id和batch_id"""
        # 如果没有batch_id，生成一个
        if not self.batch_id:
            timestamp = int(datetime.now().timestamp())
            self.batch_id = f"batch_{timestamp}"

        # 如果没有client_order_id，生成一个
        if not self.client_order_id:
            side_str = self.side.value.lower()
            self.client_order_id = (
                f"wash_{self.symbol}_{side_str}_{self.batch_id}_M{self.micro_trade_index}"
            )

    def to_dict(self):
        """扩展父类的to_dict方法，添加洗盘订单特有字段"""
        data = super().to_dict()
        data["micro_trade_index"] = self.micro_trade_index
        data["batch_id"] = self.batch_id
        return data

    @classmethod
    def from_dict(cls, data):
        """从字典创建洗盘订单对象"""
        # 移除父类不需要的字段
        micro_trade_index = data.pop("micro_trade_index", 0)
        batch_id = data.pop("batch_id", "")

        # 调用父类from_dict创建基础订单
        base_order = super().from_dict(data)

        # 创建洗盘订单
        return cls(
            symbol=base_order.symbol,
            side=base_order.side,
            price=base_order.price,
            quantity=base_order.quantity,
            order_type=OrderType.WASH_TRADING,
            client_order_id=base_order.client_order_id,
            order_id=base_order.order_id,
            status=base_order.status,
            filled_quantity=base_order.filled_quantity,
            created_at=base_order.created_at,
            updated_at=base_order.updated_at,
            metadata=base_order.metadata,
            micro_trade_index=micro_trade_index,
            batch_id=batch_id,
        )
