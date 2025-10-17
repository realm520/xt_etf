# -*- coding: utf-8 -*-
"""
订单错误分类模块
用于区分永久性错误（不应重试）和临时性错误（可以重试）

Author: ETF Trading System
Date: 2025-10-16
"""

from typing import Dict, Optional

# 永久性错误码 - 这些错误不应该重试
PERMANENT_ERROR_CODES = {
    # 认证/权限类错误
    "AUTH_101": "ApiKey不存在",
    "AUTH_102": "ApiKey未激活",
    "AUTH_104": "IP未绑定",
    "AUTH_106": "超出apikey权限",

    # 交易对限制类错误
    "SYMBOL_001": "交易对不存在",
    "SYMBOL_002": "交易对下线",
    "SYMBOL_003": "交易对暂停交易",  # 用户特别提到的核心问题
    "SYMBOL_004": "国家限制交易",
    "SYMBOL_005": "不支持API交易",
    "SYMBOL_007": "不支持修改订单",
    "SYMBOL_010": "该市场不支持交易",
    "SYMBOL_011": "高风险限制",

    # 订单限制类错误
    "ORDER_003": "交易对暂停",
    "ORDER_004": "禁止交易",
    "ORDER_007": "子账户无交易权限",
    "ORDER_008": "价格或数量精度异常",

    # 价格/数量过滤器错误
    "ORDER_F0101": "价格过滤器-最小值",
    "ORDER_F0102": "价格过滤器-最大值",
    "ORDER_F0103": "价格过滤器-步进值",
    "ORDER_F0201": "数量过滤器-最小值",
    "ORDER_F0202": "数量过滤器-最大值",
    "ORDER_F0203": "数量过滤器-步进值",
    "ORDER_F0301": "QUOTE_QTY过滤器-最小值",
    "ORDER_F0401": "保护在线过滤器或保护限制过滤器",
    "ORDER_F0501": "保护限制过滤器-买入最大偏差",
    "ORDER_F0502": "保护限制过滤器-卖出最大偏差",
    "ORDER_F0503": "保护限制过滤器-买入限制系数",
    "ORDER_F0504": "保护限制过滤器-卖出限制系数",
    "ORDER_F0601": "保护市场过滤器",
    "ORDER_F0704": "杠杆限价单清算价格限制",
}

# 临时性错误码 - 这些错误可以重试
RETRYABLE_ERROR_CODES = {
    # 资源类错误（可能在稍后恢复）
    "ORDER_002": "资金不足",
    "ORDER_006": "挂单过多",

    # 系统类错误（临时性问题）
    "COMMON_002": "系统繁忙",
    "COMMON_003": "操作失败",

    # 风控类错误（可能临时触发）
    "GATEWAY_0001": "触发风控",
    "GATEWAY_0002": "触发风控",
    "GATEWAY_0003": "触发风控",
    "GATEWAY_0004": "触发风控",
}

# 特殊处理错误码（既不是永久也不是临时，需要特殊逻辑）
SPECIAL_ERROR_CODES = {
    "ORDER_005": "订单不存在",  # 取消订单时可能遇到，不算错误
    "ORDER_001": "平台拒单",    # 需要根据具体情况判断
}


def is_permanent_error(error_code: str) -> bool:
    """
    判断是否为永久性错误

    Args:
        error_code: 错误码，如 "SYMBOL_003"

    Returns:
        True 如果是永久性错误，不应重试
    """
    if not error_code:
        return False
    return error_code in PERMANENT_ERROR_CODES


def is_retryable_error(error_code: str) -> bool:
    """
    判断是否为可重试错误

    Args:
        error_code: 错误码

    Returns:
        True 如果是临时性错误，可以重试
    """
    if not error_code:
        return False
    return error_code in RETRYABLE_ERROR_CODES


def classify_error(error_code: str) -> str:
    """
    分类错误类型

    Args:
        error_code: 错误码

    Returns:
        "permanent" / "retryable" / "special" / "unknown"
    """
    if not error_code:
        return "unknown"

    if error_code in PERMANENT_ERROR_CODES:
        return "permanent"
    elif error_code in RETRYABLE_ERROR_CODES:
        return "retryable"
    elif error_code in SPECIAL_ERROR_CODES:
        return "special"
    else:
        return "unknown"


def get_error_description(error_code: str, default_errors: Optional[Dict] = None) -> str:
    """
    获取错误描述（优先从本地定义，其次从传入的字典）

    Args:
        error_code: 错误码
        default_errors: 默认错误字典（如 XT_MES_ERRORS）

    Returns:
        错误描述文本
    """
    # 优先从本地定义查找
    if error_code in PERMANENT_ERROR_CODES:
        return PERMANENT_ERROR_CODES[error_code]
    elif error_code in RETRYABLE_ERROR_CODES:
        return RETRYABLE_ERROR_CODES[error_code]
    elif error_code in SPECIAL_ERROR_CODES:
        return SPECIAL_ERROR_CODES[error_code]

    # 其次从传入的字典查找
    if default_errors and error_code in default_errors:
        return default_errors[error_code]

    # 未知错误
    return f"未知错误码: {error_code}"


def get_blacklist_ttl(error_code: str) -> int:
    """
    获取黑名单过期时间（秒）

    Args:
        error_code: 错误码

    Returns:
        黑名单TTL（秒），不同错误类型可能有不同的过期时间
    """
    # 交易对暂停/下线类错误 - 较长的黑名单时间
    if error_code in ["SYMBOL_002", "SYMBOL_003", "ORDER_003", "ORDER_004"]:
        return 3600  # 1小时

    # 权限类错误 - 非常长的黑名单时间
    elif error_code.startswith("AUTH_"):
        return 7200  # 2小时

    # 精度/过滤器错误 - 较短的黑名单时间（代码可能修复）
    elif error_code.startswith("ORDER_F"):
        return 1800  # 30分钟

    # 其他永久性错误 - 默认1小时
    else:
        return 3600
