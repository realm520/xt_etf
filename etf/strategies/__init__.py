"""
ETF交易策略模块
包含动态价差管理、趋势跟随等策略
"""

from .dynamic_spread import DynamicSpreadManager
from .trend_following import TrendFollower

__all__ = ["DynamicSpreadManager", "TrendFollower"]
