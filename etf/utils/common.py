# -*- coding:utf-8 -*-

"""
ETF系统通用工具函数

Author: Claude Code
Date: 2025-01-22
"""

import time
import logging
from typing import Dict, Any, Optional, List, Union
from decimal import Decimal


def get_mid_price(depth: Dict[str, Any]) -> float:
    """
    从订单簿计算中间价格

    Args:
        depth: 订单簿深度数据，包含bids和asks

    Returns:
        float: 中间价格

    Raises:
        IndexError: 当订单簿完全为空时
        ValueError: 当价格格式无效时

    Note:
        如果只有一边有数据（流动性不足），使用该边的最佳价格作为中间价格
    """
    bids = depth.get("bids", [])
    asks = depth.get("asks", [])

    # ✅ 如果两边都为空，抛出异常
    if not bids and not asks:
        raise IndexError("Empty order book (both bids and asks are empty)")

    try:
        # ✅ 如果只有asks（买单为空），使用最佳卖价
        if not bids and asks:
            best_ask = float(asks[0][0])
            logging.warning(f"⚠️ 订单簿只有卖单，使用最佳卖价作为中间价: {best_ask}")
            return best_ask

        # ✅ 如果只有bids（卖单为空），使用最佳买价
        if bids and not asks:
            best_bid = float(bids[0][0])
            logging.warning(f"⚠️ 订单簿只有买单，使用最佳买价作为中间价: {best_bid}")
            return best_bid

        # ✅ 正常情况：两边都有数据，计算中间价
        best_bid = float(bids[0][0])
        best_ask = float(asks[0][0])
        return (best_bid + best_ask) / 2

    except (IndexError, ValueError) as e:
        logging.error(f"Failed to calculate mid price: {e}")
        raise


def calculate_price_change_percentage(old_price: float, new_price: float) -> float:
    """
    计算价格变化百分比
    
    Args:
        old_price: 旧价格
        new_price: 新价格
        
    Returns:
        float: 价格变化百分比 (小数形式，如0.05表示5%)
    """
    if old_price == 0:
        return 0.0
    return (new_price - old_price) / old_price


def format_order_data(
    symbol: str,
    side: str,
    order_type: str,
    price: Union[float, str],
    quantity: Union[float, str],
    client_order_id: Optional[str] = None,
    time_in_force: str = "GTC",
    biz_type: str = "SPOT"
) -> Dict[str, Any]:
    """
    格式化订单数据为标准格式
    
    Args:
        symbol: 交易对
        side: 买卖方向 (BUY/SELL)
        order_type: 订单类型 (LIMIT/MARKET)
        price: 价格
        quantity: 数量
        client_order_id: 客户端订单ID
        time_in_force: 订单有效期
        biz_type: 业务类型
        
    Returns:
        Dict: 格式化的订单数据
    """
    order_data = {
        "symbol": symbol,
        "side": side.upper(),
        "type": order_type.upper(),
        "price": float(price),
        "quantity": float(quantity),
        "timeInForce": time_in_force,
        "bizType": biz_type,
    }
    
    if client_order_id:
        order_data["clientOrderId"] = client_order_id
    
    return order_data


def validate_order_data(order_data: Dict[str, Any]) -> bool:
    """
    验证订单数据的有效性
    
    Args:
        order_data: 订单数据
        
    Returns:
        bool: 是否有效
    """
    required_fields = ["symbol", "side", "type", "price", "quantity"]
    
    # 检查必需字段
    for field in required_fields:
        if field not in order_data:
            logging.error(f"Missing required field: {field}")
            return False
    
    # 检查价格和数量为正数
    try:
        if float(order_data["price"]) <= 0:
            logging.error("Price must be positive")
            return False
        if float(order_data["quantity"]) <= 0:
            logging.error("Quantity must be positive")
            return False
    except (ValueError, TypeError):
        logging.error("Invalid price or quantity format")
        return False
    
    # 检查买卖方向
    if order_data["side"].upper() not in ["BUY", "SELL"]:
        logging.error("Invalid side, must be BUY or SELL")
        return False
    
    return True


def round_to_precision(value: float, precision: int) -> float:
    """
    按指定精度四舍五入
    
    Args:
        value: 要四舍五入的值
        precision: 小数位数
        
    Returns:
        float: 四舍五入后的值
    """
    return round(value, precision)


def calculate_order_value(price: float, quantity: float) -> float:
    """
    计算订单价值
    
    Args:
        price: 价格
        quantity: 数量
        
    Returns:
        float: 订单价值
    """
    return price * quantity


def batch_orders_by_size(orders: List[Dict], max_batch_size: int = 100) -> List[List[Dict]]:
    """
    按批量大小分组订单
    
    Args:
        orders: 订单列表
        max_batch_size: 最大批量大小
        
    Returns:
        List[List[Dict]]: 分组后的订单批次
    """
    if not orders:
        return []
    
    batches = []
    for i in range(0, len(orders), max_batch_size):
        batch = orders[i:i + max_batch_size]
        batches.append(batch)
    
    return batches


def generate_client_order_id(prefix: str = "etf", timestamp: Optional[float] = None) -> str:
    """
    生成客户端订单ID
    
    Args:
        prefix: ID前缀
        timestamp: 时间戳 (如果未提供则使用当前时间)
        
    Returns:
        str: 客户端订单ID
    """
    if timestamp is None:
        timestamp = time.time()
    
    # 使用时间戳和微秒确保唯一性
    timestamp_str = str(int(timestamp * 1000000))
    return f"{prefix}_{timestamp_str}"


def safe_float_conversion(value: Any, default: float = 0.0) -> float:
    """
    安全的浮点数转换
    
    Args:
        value: 要转换的值
        default: 转换失败时的默认值
        
    Returns:
        float: 转换后的浮点数
    """
    try:
        return float(value)
    except (ValueError, TypeError):
        logging.warning(f"Failed to convert {value} to float, using default {default}")
        return default


def calculate_spread(bid_price: float, ask_price: float) -> float:
    """
    计算买卖价差
    
    Args:
        bid_price: 买价
        ask_price: 卖价
        
    Returns:
        float: 价差百分比
    """
    if bid_price <= 0 or ask_price <= 0:
        return 0.0
    
    mid_price = (bid_price + ask_price) / 2
    if mid_price == 0:
        return 0.0
    
    return (ask_price - bid_price) / mid_price


def is_price_within_range(price: float, reference_price: float, tolerance_percent: float) -> bool:
    """
    检查价格是否在允许范围内
    
    Args:
        price: 待检查的价格
        reference_price: 参考价格
        tolerance_percent: 容忍度百分比 (如0.05表示5%)
        
    Returns:
        bool: 是否在范围内
    """
    if reference_price <= 0:
        return False
    
    tolerance = reference_price * tolerance_percent
    return abs(price - reference_price) <= tolerance


def format_timestamp(timestamp: Optional[float] = None, format_str: str = "%Y-%m-%d %H:%M:%S") -> str:
    """
    格式化时间戳
    
    Args:
        timestamp: 时间戳 (如果未提供则使用当前时间)
        format_str: 格式字符串
        
    Returns:
        str: 格式化后的时间字符串
    """
    if timestamp is None:
        timestamp = time.time()
    
    return time.strftime(format_str, time.localtime(timestamp))


def merge_orderbook_levels(bids: List[List[str]], asks: List[List[str]], max_levels: int = 10) -> Dict[str, List]:
    """
    合并和限制订单簿层级
    
    Args:
        bids: 买单列表
        asks: 卖单列表
        max_levels: 最大层级数
        
    Returns:
        Dict: 合并后的订单簿
    """
    return {
        "bids": bids[:max_levels],
        "asks": asks[:max_levels]
    }


def calculate_weighted_average_price(orders: List[Dict[str, Any]]) -> float:
    """
    计算订单的加权平均价格
    
    Args:
        orders: 订单列表，每个订单包含price和quantity字段
        
    Returns:
        float: 加权平均价格
    """
    if not orders:
        return 0.0
    
    total_value = 0.0
    total_quantity = 0.0
    
    for order in orders:
        try:
            price = float(order.get("price", 0))
            quantity = float(order.get("quantity", 0))
            
            total_value += price * quantity
            total_quantity += quantity
        except (ValueError, TypeError):
            continue
    
    if total_quantity == 0:
        return 0.0
    
    return total_value / total_quantity


def filter_orders_by_price_range(
    orders: List[Dict[str, Any]], 
    min_price: float, 
    max_price: float
) -> List[Dict[str, Any]]:
    """
    按价格范围过滤订单
    
    Args:
        orders: 订单列表
        min_price: 最小价格
        max_price: 最大价格
        
    Returns:
        List: 过滤后的订单列表
    """
    filtered_orders = []
    
    for order in orders:
        try:
            price = float(order.get("price", 0))
            if min_price <= price <= max_price:
                filtered_orders.append(order)
        except (ValueError, TypeError):
            continue
    
    return filtered_orders