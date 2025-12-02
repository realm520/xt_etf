"""
对冲策略模块

提供可插拔的对冲策略实现：
- FixedRatioStrategy: 固定比例对冲
- DynamicRatioStrategy: 动态对冲（根据波动率调整）
"""

from .base import HedgeStrategy, HedgeDecision
from .fixed_ratio import FixedRatioStrategy
from .dynamic import DynamicRatioStrategy

__all__ = [
    "HedgeStrategy",
    "HedgeDecision",
    "FixedRatioStrategy",
    "DynamicRatioStrategy",
]
