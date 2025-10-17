# -*- coding: utf-8 -*-
"""
告警系统模块

简化版告警系统 - 仅提供日志记录功能
Lark 告警已移除，改用统一的可观测平台
"""

from enum import Enum

class AlertLevel(Enum):
    """告警级别枚举（保留以兼容现有代码）"""
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"

# 空的告警管理器类，提供最小接口以兼容现有代码
class AlertManager:
    async def close(self):
        """关闭告警管理器（空实现）"""
        pass

# 单例实例
_alert_manager = AlertManager()

def get_alert_manager():
    """获取告警管理器实例"""
    return _alert_manager

async def send_alert(*args, **kwargs):
    """空实现，不再发送告警"""
    pass

async def send_direct_alert(*args, **kwargs):
    """空实现，不再发送告警"""
    pass

__all__ = [
    "AlertLevel",
    "AlertManager",
    "get_alert_manager",
    "send_alert",
    "send_direct_alert"
]
