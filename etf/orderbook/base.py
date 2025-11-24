"""
订单簿算法抽象基类

设计原则：
1. 算法只负责计算，不执行任何订单操作
2. 返回 OrderbookDiff（差异对象），描述需要做什么调整
3. 由独立的执行器模块负责实际下单/撤单
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import List, Dict, Tuple, Optional
from decimal import Decimal


@dataclass
class OrderbookConfig:
    """订单簿算法配置（通用参数）"""

    # 核心参数
    total_budget: float              # 总预算（USDT）
    layer: int                       # 档位数（1000-1000000）
    mid_price: float                 # 中间价（净值或市场价）
    bid_ask_spread: float            # 买卖价差
    symbol: str                      # 交易对

    # 精度控制
    price_precision: int = 6         # 价格精度（小数位数）
    quantity_precision: int = 2      # 数量精度（小数位数）

    # 扩展参数（算法特定）
    extra_params: Dict = field(default_factory=dict)

    def __post_init__(self):
        """参数验证"""
        if self.layer < 10 or self.layer > 1_000_000:
            raise ValueError(f"layer must be in [10, 1000000], got {self.layer}")

        if self.total_budget <= 0:
            raise ValueError(f"total_budget must be positive, got {self.total_budget}")


@dataclass
class OrderLevel:
    """单个订单档位"""

    price: Decimal                   # 价格
    quantity: Decimal                # 数量（币）
    value: Decimal                   # 金额（USDT）= price * quantity
    side: str                        # 'bid' | 'ask'

    # 可选：订单元数据
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
    """订单簿快照（算法输出）"""

    bids: List[OrderLevel]           # 买盘订单列表
    asks: List[OrderLevel]           # 卖盘订单列表

    # 元数据
    algorithm: str                   # 算法名称
    generation_time: float           # 生成耗时（秒）
    total_value: Decimal = field(init=False)  # 总金额

    def __post_init__(self):
        """计算总金额"""
        bid_total = sum(level.value for level in self.bids)
        ask_total = sum(level.value for level in self.asks)
        self.total_value = bid_total + ask_total

    def to_dict(self) -> dict:
        """转换为字典格式（兼容现有代码）"""
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


@dataclass
class OrderbookDiff:
    """订单簿差异（算法计算结果 → 执行器输入）

    核心思想：
    - 算法只负责计算"应该做什么"
    - 执行器负责"真正去做"
    """

    operations: List[OrderOperation]  # 操作列表

    # 统计信息
    num_adds: int = field(init=False)
    num_cancels: int = field(init=False)

    def __post_init__(self):
        """计算统计"""
        self.num_adds = sum(1 for op in self.operations if op.action == 'add')
        self.num_cancels = sum(1 for op in self.operations if op.action == 'cancel')

    def summary(self) -> str:
        """简要描述"""
        return f"OrderbookDiff: +{self.num_adds} adds, -{self.num_cancels} cancels"


class OrderbookAlgorithm(ABC):
    """订单簿算法抽象基类

    职责：
    1. 根据配置生成目标订单簿快照
    2. 对比当前订单簿，计算差异（Diff）
    3. 不执行任何实际订单操作
    """

    def __init__(self, config: OrderbookConfig):
        self.config = config
        self.validate_config()

    @abstractmethod
    def generate_snapshot(self) -> OrderbookSnapshot:
        """生成目标订单簿快照

        Returns:
            OrderbookSnapshot: 理想的订单簿状态
        """
        pass

    def compute_diff(
        self,
        current_orders: Dict[str, List[dict]]
    ) -> OrderbookDiff:
        """计算订单簿差异

        Args:
            current_orders: 当前订单簿
                {
                    'bids': [{'order_id': '123', 'price': 1.0, 'quantity': 10}, ...],
                    'asks': [{'order_id': '456', 'price': 1.1, 'quantity': 10}, ...]
                }

        Returns:
            OrderbookDiff: 需要执行的操作列表
        """
        # 1. 生成目标订单簿
        target = self.generate_snapshot()

        # 2. 计算差异
        operations = []

        # 处理买盘
        operations.extend(
            self._compute_side_diff(
                current_orders.get('bids', []),
                target.bids,
                side='bid'
            )
        )

        # 处理卖盘
        operations.extend(
            self._compute_side_diff(
                current_orders.get('asks', []),
                target.asks,
                side='ask'
            )
        )

        return OrderbookDiff(operations=operations)

    def _compute_side_diff(
        self,
        current: List[dict],
        target: List[OrderLevel],
        side: str
    ) -> List[OrderOperation]:
        """计算单边差异

        策略：
        1. 取消所有当前订单
        2. 添加所有目标订单

        （简单粗暴但有效，避免复杂的匹配逻辑）
        """
        operations = []

        # 1. 取消所有现有订单
        for order in current:
            operations.append(OrderOperation(
                action='cancel',
                side=side,
                order_id=order['order_id'],
                reason='refresh_orderbook'
            ))

        # 2. 添加所有目标订单
        for level in target:
            operations.append(OrderOperation(
                action='add',
                side=side,
                price=level.price,
                quantity=level.quantity,
                reason='refresh_orderbook'
            ))

        return operations

    @abstractmethod
    def validate_config(self):
        """验证配置参数"""
        pass

    @property
    @abstractmethod
    def algorithm_name(self) -> str:
        """算法名称"""
        pass

    @property
    @abstractmethod
    def supported_layer_range(self) -> Tuple[int, int]:
        """支持的档位范围 (min, max)"""
        pass


class OrderbookFactory:
    """订单簿算法工厂（简化版）"""

    _algorithms: Dict[str, type] = {}

    @classmethod
    def register(cls, name: str, algorithm_class: type):
        """注册算法"""
        cls._algorithms[name] = algorithm_class

    @classmethod
    def create(cls, name: str, config: OrderbookConfig) -> OrderbookAlgorithm:
        """创建算法实例"""
        if name not in cls._algorithms:
            available = ', '.join(cls._algorithms.keys())
            raise ValueError(
                f"Unknown algorithm: {name}. "
                f"Available: {available}"
            )

        return cls._algorithms[name](config)

    @classmethod
    def list_algorithms(cls) -> List[str]:
        """列出所有已注册算法"""
        return list(cls._algorithms.keys())


def register_algorithm(name: str):
    """装饰器：自动注册算法"""
    def decorator(cls: type) -> type:
        OrderbookFactory.register(name, cls)
        return cls
    return decorator
