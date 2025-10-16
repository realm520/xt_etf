# -*- coding: utf-8 -*-
"""
风险控制模块

这个包提供风险控制功能，包括止损管理和风险监控。
"""

from .stop_loss import (
    StopLossManager,
    StopLossType,
    StopLossAction,
    StopLossResult,
    PositionInfo
)

from .controller import RiskController

# 向后兼容别名
RiskManager = RiskController

__all__ = [
    "StopLossManager",
    "StopLossType",
    "StopLossAction",
    "StopLossResult",
    "PositionInfo",
    "RiskController",
    "RiskManager"
]