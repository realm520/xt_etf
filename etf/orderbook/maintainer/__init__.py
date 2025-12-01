"""
订单簿维护器模块

纯算法模块，负责：
1. 生成价值平衡的初始订单簿
2. 计算净值变化时的调整操作
3. 智能排序操作顺序

不涉及：
- 实际下单/撤单
- 网络IO
- 状态持久化
"""

from .config import MaintainerConfig, LayerSpec
from .core import OrderbookMaintainer, MaintenanceResult, MaintenanceStats
from .generator import OrderbookGenerator
from .differ import OrderbookDiffer, CurrentOrderbook, ExistingOrder
from .metrics import BalanceMetrics, MetricsCalculator
from .adapter import MaintainerAdapter

__all__ = [
    # 配置
    "MaintainerConfig",
    "LayerSpec",
    # 核心
    "OrderbookMaintainer",
    "MaintenanceResult",
    "MaintenanceStats",
    # 当前订单簿
    "CurrentOrderbook",
    "ExistingOrder",
    # 生成器
    "OrderbookGenerator",
    # 差异计算
    "OrderbookDiffer",
    # 指标
    "BalanceMetrics",
    "MetricsCalculator",
    # 适配器
    "MaintainerAdapter",
]
