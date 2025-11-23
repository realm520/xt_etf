"""
订单簿算法模块

提供统一的订单簿生成接口，支持多种算法。

架构：
    算法层 (Algorithm) → 计算 → OrderbookDiff
                                      ↓
    执行层 (Executor) ← 执行 ← OrderbookDiff
"""

from .base import (
    OrderbookConfig,
    OrderLevel,
    OrderbookSnapshot,
    OrderOperation,
    OrderbookDiff,
    OrderbookAlgorithm,
    OrderbookFactory,
    register_algorithm,
)
from .executor import OrderExecutor, ExecutionResult, ExecutionSummary

# 自动导入所有算法（触发装饰器注册）
from . import natural

# ✅ 旧函数已删除，不再需要向后兼容

__all__ = [
    # 基础类型
    'OrderbookConfig',
    'OrderLevel',
    'OrderbookSnapshot',
    'OrderOperation',
    'OrderbookDiff',

    # 算法相关
    'OrderbookAlgorithm',
    'OrderbookFactory',
    'register_algorithm',

    # 执行器相关
    'OrderExecutor',
    'ExecutionResult',
    'ExecutionSummary',
]
