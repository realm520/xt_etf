"""
订单簿基础类型定义

提供 Maintainer 和 ExecutorV2 使用的核心数据类型。
"""

from dataclasses import dataclass, field
from typing import List, Dict, Optional
from decimal import Decimal


@dataclass
class OrderLevel:
    """单个订单档位"""

    price: Decimal                   # 价格
    quantity: Decimal                # 数量（币）
    value: Decimal                   # 金额（USDT）= price * quantity
    side: str                        # 'bid' | 'ask'

    # 可选：订单元数据（如 order_id）
    metadata: Dict = field(default_factory=dict)

    def __post_init__(self):
        """确保使用Decimal避免浮点误差"""
        if not isinstance(self.price, Decimal):
            self.price = Decimal(str(self.price))
        if not isinstance(self.quantity, Decimal):
            self.quantity = Decimal(str(self.quantity))
        if not isinstance(self.value, Decimal):
            self.value = Decimal(str(self.value))


@dataclass
class OrderbookSnapshot:
    """订单簿快照"""

    bids: List[OrderLevel]           # 买盘订单列表
    asks: List[OrderLevel]           # 卖盘订单列表

    # 元数据
    algorithm: str = "maintainer"    # 算法名称
    generation_time: float = 0.0     # 生成耗时（秒）
    total_value: Decimal = field(init=False)  # 总金额

    def __post_init__(self):
        """计算总金额"""
        bid_total = sum(level.value for level in self.bids)
        ask_total = sum(level.value for level in self.asks)
        self.total_value = bid_total + ask_total

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            'bids': [[float(level.price), float(level.quantity)] for level in self.bids],
            'asks': [[float(level.price), float(level.quantity)] for level in self.asks],
            'algorithm': self.algorithm,
            'metadata': {
                'total_value': float(self.total_value),
                'generation_time': self.generation_time,
                'bid_count': len(self.bids),
                'ask_count': len(self.asks),
            }
        }


@dataclass
class OrderOperation:
    """单个订单操作（新增或取消）"""

    action: str                      # 'add' | 'cancel'
    side: str                        # 'bid' | 'ask'

    # add操作必需
    price: Optional[Decimal] = None
    quantity: Optional[Decimal] = None

    # cancel操作必需
    order_id: Optional[str] = None

    # 可选：操作原因（用于日志/监控）
    reason: Optional[str] = None

    def __post_init__(self):
        """验证参数"""
        if self.action == 'add':
            if self.price is None or self.quantity is None:
                raise ValueError("add operation requires price and quantity")
        elif self.action == 'cancel':
            if self.order_id is None:
                raise ValueError("cancel operation requires order_id")
        else:
            raise ValueError(f"Unknown action: {self.action}")
