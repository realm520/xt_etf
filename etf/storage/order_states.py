"""
订单状态管理模块
定义完整的订单生命周期状态和状态转换规则
"""

from enum import Enum
from typing import Optional, Set


class OrderStatus(str, Enum):
    """订单状态枚举"""

    # 初始状态（数据库专有）
    PENDING = "PENDING"  # 订单已创建，等待交易所确认

    # 交易所状态
    NEW = "NEW"  # 交易所已确认，订单激活
    PARTIALLY_FILLED = "PARTIALLY_FILLED"  # 部分成交
    FILLED = "FILLED"  # 完全成交
    CANCELED = "CANCELED"  # 已取消
    REJECTED = "REJECTED"  # 订单被拒绝
    EXPIRED = "EXPIRED"  # 订单过期

    # 撤单中间状态（数据库专有）
    PENDING_CANCEL = "PENDING_CANCEL"  # 撤单请求已发送，等待交易所确认
    CANCEL_REJECTED = "CANCEL_REJECTED"  # 撤单被拒绝（可能已成交）


class OrderStatusManager:
    """订单状态管理器 - 管理状态转换规则"""

    # 终态状态（不可再变更）
    FINAL_STATES: Set[OrderStatus] = {
        OrderStatus.FILLED,
        OrderStatus.CANCELED,
        OrderStatus.REJECTED,
        OrderStatus.EXPIRED,
    }

    # 活跃状态（可以继续操作）
    ACTIVE_STATES: Set[OrderStatus] = {
        OrderStatus.NEW,
        OrderStatus.PARTIALLY_FILLED,
    }

    # 中间状态（等待确认）
    PENDING_STATES: Set[OrderStatus] = {
        OrderStatus.PENDING,
        OrderStatus.PENDING_CANCEL,
    }

    # 可撤销状态
    CANCELABLE_STATES: Set[OrderStatus] = {
        OrderStatus.NEW,
        OrderStatus.PARTIALLY_FILLED,
    }

    # 状态转换规则（from_status -> allowed_to_statuses）
    STATE_TRANSITIONS = {
        # 从PENDING可以转换到
        OrderStatus.PENDING: {
            OrderStatus.NEW,  # 交易所确认成功
            OrderStatus.REJECTED,  # 交易所拒绝
        },

        # 从NEW可以转换到
        OrderStatus.NEW: {
            OrderStatus.PARTIALLY_FILLED,  # 部分成交
            OrderStatus.FILLED,  # 完全成交
            OrderStatus.PENDING_CANCEL,  # 发起撤单
            OrderStatus.CANCELED,  # WebSocket直接推送已取消（跳过PENDING_CANCEL）
        },

        # 从PARTIALLY_FILLED可以转换到
        OrderStatus.PARTIALLY_FILLED: {
            OrderStatus.FILLED,  # 完全成交
            OrderStatus.PENDING_CANCEL,  # 发起撤单
            OrderStatus.CANCELED,  # WebSocket直接推送已取消
        },

        # 从PENDING_CANCEL可以转换到
        OrderStatus.PENDING_CANCEL: {
            OrderStatus.CANCELED,  # 撤单成功
            OrderStatus.CANCEL_REJECTED,  # 撤单失败
            OrderStatus.FILLED,  # 撤单期间完全成交
        },

        # 终态不可转换
        OrderStatus.FILLED: set(),
        OrderStatus.CANCELED: set(),
        OrderStatus.REJECTED: set(),
        OrderStatus.EXPIRED: set(),
        OrderStatus.CANCEL_REJECTED: set(),
    }

    @classmethod
    def can_transition(cls, from_status: str, to_status: str) -> bool:
        """
        检查状态转换是否合法

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            bool: 是否允许转换
        """
        try:
            from_state = OrderStatus(from_status)
            to_state = OrderStatus(to_status)

            # 检查是否在允许的转换列表中
            allowed_states = cls.STATE_TRANSITIONS.get(from_state, set())
            return to_state in allowed_states

        except ValueError:
            # 无效的状态值
            return False

    @classmethod
    def is_final(cls, status: str) -> bool:
        """检查是否为终态"""
        try:
            return OrderStatus(status) in cls.FINAL_STATES
        except ValueError:
            return False

    @classmethod
    def is_active(cls, status: str) -> bool:
        """检查是否为活跃状态"""
        try:
            return OrderStatus(status) in cls.ACTIVE_STATES
        except ValueError:
            return False

    @classmethod
    def is_pending(cls, status: str) -> bool:
        """检查是否为等待中状态"""
        try:
            return OrderStatus(status) in cls.PENDING_STATES
        except ValueError:
            return False

    @classmethod
    def can_cancel(cls, status: str) -> bool:
        """检查是否可以撤单"""
        try:
            return OrderStatus(status) in cls.CANCELABLE_STATES
        except ValueError:
            return False

    @classmethod
    def validate_transition(cls, from_status: str, to_status: str) -> tuple[bool, Optional[str]]:
        """
        验证状态转换并返回详细信息

        Args:
            from_status: 当前状态
            to_status: 目标状态

        Returns:
            (is_valid, error_message): (是否有效, 错误信息)
        """
        try:
            from_state = OrderStatus(from_status)
            to_state = OrderStatus(to_status)

            # 检查是否为终态
            if from_state in cls.FINAL_STATES:
                return False, f"订单已处于终态 {from_status}，无法再变更"

            # 检查转换是否合法
            allowed_states = cls.STATE_TRANSITIONS.get(from_state, set())
            if to_state not in allowed_states:
                return False, f"不允许从 {from_status} 转换到 {to_status}"

            return True, None

        except ValueError as e:
            return False, f"无效的状态值: {e}"


# 状态说明文档
ORDER_STATUS_DESCRIPTIONS = {
    "PENDING": "订单已创建，等待交易所确认（数据库专有状态）",
    "NEW": "订单已被交易所接受，等待成交",
    "PARTIALLY_FILLED": "订单部分成交，剩余部分仍在等待",
    "FILLED": "订单完全成交（终态）",
    "CANCELED": "订单已取消（终态）",
    "REJECTED": "订单被交易所拒绝（终态）",
    "EXPIRED": "订单已过期（终态）",
    "PENDING_CANCEL": "撤单请求已发送，等待交易所确认（数据库专有状态）",
    "CANCEL_REJECTED": "撤单请求被拒绝，订单可能已成交（终态）",
}


def get_status_description(status: str) -> str:
    """获取状态描述"""
    return ORDER_STATUS_DESCRIPTIONS.get(status, "未知状态")


# 导出
__all__ = [
    "OrderStatus",
    "OrderStatusManager",
    "ORDER_STATUS_DESCRIPTIONS",
    "get_status_description",
]
