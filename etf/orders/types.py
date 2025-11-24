"""
订单类型系统核心定义

包含订单枚举、状态枚举和基础订单类。
"""

from enum import Enum
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Optional, Tuple, Dict, Any
from datetime import datetime


class OrderType(Enum):
    """订单类型枚举"""

    MARKET_MAKING = "market_making"
    WASH_TRADING = "wash_trading"
    ANTI_PIN = "anti_pin"
    HEDGING = "hedging"  # 预留，暂不实现

    def __str__(self):
        return self.value


class OrderSide(Enum):
    """订单方向"""

    BUY = "BUY"
    SELL = "SELL"

    def __str__(self):
        return self.value


class OrderStatus(Enum):
    """订单状态"""

    PENDING = "PENDING"  # 待发送
    NEW = "NEW"  # 已接受
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交
    FILLED = "FILLED"  # 完全成交
    CANCELED = "CANCELED"  # 已取消
    REJECTED = "REJECTED"  # 已拒绝
    EXPIRED = "EXPIRED"  # 已过期

    def __str__(self):
        return self.value


@dataclass
class BaseOrder:
    """
    订单基类

    所有具体订单类型的父类，包含订单的通用属性和方法。
    """

    # ========== 基础字段 ==========
    symbol: str
    side: OrderSide
    price: Decimal
    quantity: Decimal
    order_type: OrderType

    # ========== 唯一标识 ==========
    client_order_id: str = ""
    order_id: str = ""  # 交易所返回的订单ID

    # ========== 状态 ==========
    status: OrderStatus = OrderStatus.PENDING
    filled_quantity: Decimal = Decimal("0")

    # ========== 时间戳 ==========
    created_at: datetime = field(default_factory=datetime.now)
    updated_at: datetime = field(default_factory=datetime.now)

    # ========== 额外元数据 ==========
    metadata: Dict[str, Any] = field(default_factory=dict)

    def validate(self) -> Tuple[bool, str]:
        """
        验证订单参数

        Returns:
            (is_valid, error_message)
        """
        if not self.symbol:
            return False, "交易对symbol不能为空"

        if self.price <= 0:
            return False, f"价格必须大于0，当前: {self.price}"

        if self.quantity <= 0:
            return False, f"数量必须大于0，当前: {self.quantity}"

        return True, ""

    def is_terminal(self) -> bool:
        """
        判断是否为终态订单

        终态订单不会再发生状态变化，可以被清理。
        """
        return self.status in [
            OrderStatus.FILLED,
            OrderStatus.CANCELED,
            OrderStatus.REJECTED,
            OrderStatus.EXPIRED,
        ]

    def is_active(self) -> bool:
        """判断是否为活跃订单"""
        return not self.is_terminal()

    def get_remaining_quantity(self) -> Decimal:
        """获取剩余未成交数量"""
        return self.quantity - self.filled_quantity

    def get_fill_percentage(self) -> float:
        """获取成交百分比"""
        if self.quantity == 0:
            return 0.0
        return float(self.filled_quantity / self.quantity * 100)

    def to_dict(self) -> Dict[str, Any]:
        """
        转换为字典

        用于序列化、日志记录、数据库存储等场景。
        """
        return {
            # 基础字段
            "symbol": self.symbol,
            "side": self.side.value,
            "price": str(self.price),
            "quantity": str(self.quantity),
            "order_type": self.order_type.value,
            # 唯一标识
            "client_order_id": self.client_order_id,
            "order_id": self.order_id,
            # 状态
            "status": self.status.value,
            "filled_quantity": str(self.filled_quantity),
            # 时间戳
            "created_at": self.created_at.isoformat(),
            "updated_at": self.updated_at.isoformat(),
            # 元数据
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "BaseOrder":
        """
        从字典创建订单对象

        Args:
            data: 订单数据字典

        Returns:
            订单对象
        """
        return cls(
            symbol=data["symbol"],
            side=OrderSide[data["side"]],
            price=Decimal(data["price"]),
            quantity=Decimal(data["quantity"]),
            order_type=OrderType(data["order_type"]),
            client_order_id=data.get("client_order_id", ""),
            order_id=data.get("order_id", ""),
            status=OrderStatus[data.get("status", "PENDING")],
            filled_quantity=Decimal(data.get("filled_quantity", "0")),
            created_at=datetime.fromisoformat(data["created_at"])
            if "created_at" in data
            else datetime.now(),
            updated_at=datetime.fromisoformat(data["updated_at"])
            if "updated_at" in data
            else datetime.now(),
            metadata=data.get("metadata", {}),
        )

    def __repr__(self) -> str:
        """字符串表示"""
        return (
            f"{self.__class__.__name__}("
            f"symbol={self.symbol}, "
            f"side={self.side.value}, "
            f"price={self.price}, "
            f"quantity={self.quantity}, "
            f"status={self.status.value}, "
            f"client_order_id={self.client_order_id}"
            f")"
        )
