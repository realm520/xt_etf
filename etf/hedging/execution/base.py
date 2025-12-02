"""
订单执行器抽象基类

定义订单执行的统一接口，支持多种执行策略的实现。
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional
from datetime import datetime


class OrderStatus(Enum):
    """订单状态枚举"""
    PENDING = "PENDING"
    FILLED = "FILLED"
    PARTIALLY_FILLED = "PARTIALLY_FILLED"
    CANCELLED = "CANCELLED"
    REJECTED = "REJECTED"
    EXPIRED = "EXPIRED"
    FAILED = "FAILED"


@dataclass
class ExecutionResult:
    """
    订单执行结果数据类

    包含订单执行后的完整信息。

    Attributes:
        success: 是否执行成功
        order_id: 订单ID（成功时返回）
        status: 订单状态
        filled_qty: 成交数量
        filled_price: 成交均价
        remaining_qty: 剩余未成交数量
        commission: 手续费
        error_message: 错误信息（失败时返回）
        error_code: 错误码（失败时返回）
        attempts: 执行尝试次数
        execution_time: 执行耗时（秒）
        timestamp: 执行时间戳
    """
    success: bool
    order_id: Optional[str] = None
    status: OrderStatus = OrderStatus.PENDING
    filled_qty: Decimal = Decimal("0")
    filled_price: Decimal = Decimal("0")
    remaining_qty: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    error_message: Optional[str] = None
    error_code: Optional[str] = None
    attempts: int = 1
    execution_time: float = 0.0
    timestamp: datetime = field(default_factory=datetime.now)

    def __post_init__(self):
        """验证结果数据"""
        if self.filled_qty < 0:
            raise ValueError(f"filled_qty must be non-negative, got {self.filled_qty}")
        if self.filled_price < 0:
            raise ValueError(f"filled_price must be non-negative, got {self.filled_price}")
        if self.remaining_qty < 0:
            raise ValueError(f"remaining_qty must be non-negative, got {self.remaining_qty}")

    @property
    def filled_value(self) -> Decimal:
        """计算成交金额"""
        return self.filled_qty * self.filled_price

    def to_dict(self) -> dict:
        """转换为字典格式"""
        return {
            "success": self.success,
            "order_id": self.order_id,
            "status": self.status.value,
            "filled_qty": float(self.filled_qty),
            "filled_price": float(self.filled_price),
            "filled_value": float(self.filled_value),
            "remaining_qty": float(self.remaining_qty),
            "commission": float(self.commission),
            "error_message": self.error_message,
            "error_code": self.error_code,
            "attempts": self.attempts,
            "execution_time": self.execution_time,
            "timestamp": self.timestamp.isoformat(),
        }


class OrderExecutor(ABC):
    """
    订单执行器抽象基类

    所有订单执行器必须实现此接口，提供统一的订单执行逻辑。

    执行器类型:
    - MarketOrderExecutor: 市价单执行（保证成交）
    - LimitOrderExecutor: 限价单执行（可选，未来扩展）

    使用示例:
        executor = MarketOrderExecutor(client, max_retries=3)
        result = await executor.execute(
            symbol="TONUSDT",
            side="BUY",
            quantity=Decimal("100")
        )
        if result.success:
            print(f"成交 {result.filled_qty} @ {result.filled_price}")
    """

    @abstractmethod
    async def execute(
        self,
        symbol: str,
        side: str,
        quantity: Decimal,
        price: Optional[Decimal] = None
    ) -> ExecutionResult:
        """
        执行订单

        Args:
            symbol: 交易对 (例如: "TONUSDT")
            side: 交易方向 ('BUY' 或 'SELL')
            quantity: 交易数量
            price: 价格（市价单可选，限价单必需）

        Returns:
            ExecutionResult: 执行结果，包含成交信息或错误信息
        """
        pass

    @abstractmethod
    async def cancel(self, symbol: str, order_id: str) -> bool:
        """
        取消订单

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            bool: 是否取消成功
        """
        pass

    @abstractmethod
    async def get_order_status(self, symbol: str, order_id: str) -> ExecutionResult:
        """
        查询订单状态

        Args:
            symbol: 交易对
            order_id: 订单ID

        Returns:
            ExecutionResult: 订单当前状态
        """
        pass

    @abstractmethod
    def get_name(self) -> str:
        """
        获取执行器名称

        Returns:
            执行器名称字符串，用于日志和监控
        """
        pass

    def get_config(self) -> dict:
        """
        获取执行器配置

        Returns:
            执行器当前配置的字典表示
        """
        return {"name": self.get_name()}
