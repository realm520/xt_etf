# -*- coding:utf-8 -*-

"""
ETF系统性能优化工具

Author: Claude Code
Date: 2025-01-22
"""

import asyncio
import time
from typing import List, Dict, Any, Optional, Tuple, Set
from collections import defaultdict
from dataclasses import dataclass
import logging


@dataclass
class OrderPriceIndex:
    """订单价格索引"""
    orders_by_price: Dict[float, List[Dict[str, Any]]]
    price_levels: List[float]
    
    def __post_init__(self):
        self.price_levels.sort()


def build_order_price_index(orders: List[Dict[str, Any]]) -> OrderPriceIndex:
    """
    构建订单价格索引，优化价格范围查询
    
    Args:
        orders: 订单列表
        
    Returns:
        OrderPriceIndex: 价格索引
    """
    orders_by_price = defaultdict(list)
    
    for order in orders:
        try:
            price = float(order.get("price", 0))
            orders_by_price[price].append(order)
        except (ValueError, TypeError):
            logging.warning(f"Invalid price in order: {order}")
            continue
    
    price_levels = list(orders_by_price.keys())
    
    return OrderPriceIndex(
        orders_by_price=dict(orders_by_price),
        price_levels=price_levels
    )


def find_orders_in_price_range(
    price_index: OrderPriceIndex,
    min_price: float,
    max_price: float
) -> List[Dict[str, Any]]:
    """
    在价格索引中查找指定价格范围内的订单 (O(log n + k) 复杂度)
    
    Args:
        price_index: 价格索引
        min_price: 最小价格
        max_price: 最大价格
        
    Returns:
        List: 价格范围内的订单列表
    """
    # 使用二分查找找到价格范围
    left = binary_search_left(price_index.price_levels, min_price)
    right = binary_search_right(price_index.price_levels, max_price)
    
    result_orders = []
    
    for i in range(left, right + 1):
        if i < len(price_index.price_levels):
            price = price_index.price_levels[i]
            if min_price <= price <= max_price:
                result_orders.extend(price_index.orders_by_price[price])
    
    return result_orders


def binary_search_left(arr: List[float], target: float) -> int:
    """二分查找左边界"""
    left, right = 0, len(arr)
    
    while left < right:
        mid = (left + right) // 2
        if arr[mid] < target:
            left = mid + 1
        else:
            right = mid
    
    return left


def binary_search_right(arr: List[float], target: float) -> int:
    """二分查找右边界"""
    left, right = 0, len(arr) - 1
    
    while left <= right:
        mid = (left + right) // 2
        if arr[mid] <= target:
            left = mid + 1
        else:
            right = mid - 1
    
    return right


def optimize_order_matching(
    current_orders: List[Dict[str, Any]],
    goal_orders: List[Dict[str, Any]],
    max_layer: Optional[int] = None,  # 新增：最大档位数限制
    cleanup_threshold: float = 1.5,   # 新增：清理阈值（150%）
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """
    优化的订单匹配算法，将O(n²)复杂度降低到O(n log n)
    
    改进：
    1. 保留原有价格范围匹配逻辑
    2. 添加超范围订单自动清理
    3. 添加订单数量上限保护
    
    Args:
        current_orders: 当前订单列表
        goal_orders: 目标订单列表
        max_layer: 最大档位数（可选，用于订单数量保护）
        cleanup_threshold: 清理阈值（默认150%，当订单数超过max_layer*1.5时强制清理）
        
    Returns:
        Tuple: (需要添加的订单, 需要取消的订单)
    """
    # 构建价格索引，O(n log n)
    price_index = build_order_price_index(current_orders)
    
    add_orders = []
    cancel_orders = []
    
    # 计算目标价格范围（用于识别超范围订单）
    if goal_orders:
        all_min_prices = [goal["min_price"] for goal in goal_orders]
        all_max_prices = [goal["max_price"] for goal in goal_orders]
        global_min_price = min(all_min_prices)
        global_max_price = max(all_max_prices)
    else:
        global_min_price = 0
        global_max_price = float('inf')
    
    # 遍历目标订单，O(m * log n)，其中m是goal_orders数量
    for goal in goal_orders:
        goal_min_price = goal["min_price"]
        goal_max_price = goal["max_price"]
        goal_amount = goal["amount"]
        goal_side = "SELL" if goal["direction"] == "ask" else "BUY"
        
        # O(log n + k)查找价格范围内的订单
        valid_market_orders = find_orders_in_price_range(
            price_index, goal_min_price, goal_max_price
        )
        
        # ✅ 关键修复：按方向过滤订单（防止买卖混淆导致的不平衡）
        valid_market_orders = [
            order for order in valid_market_orders
            if order.get("side") == goal_side
        ]
        
        # 过滤掉部分成交的订单
        valid_market_orders = [
            order for order in valid_market_orders
            if order.get("state") != "PARTIALLY_FILLED"
        ]
        
        total_market_amount = sum(
            round(float(order.get("origQty", 0))) for order in valid_market_orders
        )
        
        if total_market_amount < goal_amount:
            # 需要添加订单
            order_data = {
                "symbol": goal.get("symbol"),
                "side": "SELL" if goal["direction"] == "ask" else "BUY",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "bizType": "SPOT",
                "price": goal["price"],
                "quantity": goal_amount - total_market_amount,
                "quoteQty": None,
            }
            add_orders.append(order_data)
            
        elif total_market_amount > goal_amount:
            # 需要取消订单
            excess_amount = total_market_amount - goal_amount
            
            for order in valid_market_orders:
                if excess_amount <= 0:
                    break
                
                cancel_amount = min(
                    round(float(order.get("origQty", 0))), excess_amount
                )
                
                if order.get("state") != "PARTIALLY_FILLED":
                    cancel_orders.append(order)
                
                excess_amount -= cancel_amount
    
    # ========== 新增：超范围订单清理逻辑 ==========
    
    # 1. 识别并清理超出目标价格范围的订单（增加缓冲区）
    # 计算价格缓冲区：目标范围的5%，避免过度清理
    price_range = global_max_price - global_min_price
    buffer = price_range * 0.05  # 5%缓冲区
    
    buffered_min_price = global_min_price - buffer
    buffered_max_price = global_max_price + buffer
    
    out_of_range_orders = []
    for order in current_orders:
        try:
            price = float(order.get("price", 0))
            # 订单价格明显超出缓冲范围 → 标记为待取消
            if price < buffered_min_price or price > buffered_max_price:
                if order not in cancel_orders:  # 避免重复
                    out_of_range_orders.append(order)
        except (ValueError, TypeError):
            logging.warning(f"Invalid order price, skipping: {order}")
            continue
    
    if out_of_range_orders:
        logging.info(
            f"🧹 发现 {len(out_of_range_orders)} 个超范围订单 "
            f"(目标范围: {global_min_price:.6f} ~ {global_max_price:.6f}, "
            f"缓冲范围: {buffered_min_price:.6f} ~ {buffered_max_price:.6f})"
        )
        cancel_orders.extend(out_of_range_orders)
    
    # 2. 订单数量上限保护（可选）
    if max_layer is not None:
        order_limit = int(max_layer * cleanup_threshold)
        
        if len(current_orders) > order_limit:
            logging.warning(
                f"⚠️ 订单数量超标: {len(current_orders)} > {order_limit} "
                f"(配置: {max_layer}, 阈值: {cleanup_threshold:.0%})"
            )
            
            # 统计需要清理的数量
            need_cleanup = len(current_orders) - max_layer
            
            # 按价格偏离度排序，优先清理偏离最远的订单
            mid_price = (global_min_price + global_max_price) / 2
            
            sorted_orders = sorted(
                current_orders,
                key=lambda o: abs(float(o.get("price", 0)) - mid_price),
                reverse=True  # 偏离最远的排在前面
            )
            
            # 清理偏离最远的订单
            for i, order in enumerate(sorted_orders):
                if i >= need_cleanup:
                    break
                if order not in cancel_orders:  # 避免重复
                    cancel_orders.append(order)
            
            logging.info(
                f"🧹 强制清理 {min(need_cleanup, len(sorted_orders))} 个偏离订单 "
                f"(目标: {max_layer}档)"
            )
    
    # ========== 结束：清理逻辑 ==========
    
    return add_orders, cancel_orders


class BatchProcessor:
    """批量处理器，优化批量操作性能"""
    
    def __init__(self, max_batch_size: int = 100, max_concurrent: int = 5):
        self.max_batch_size = max_batch_size
        self.max_concurrent = max_concurrent
    
    async def process_batches_async(
        self,
        items: List[Any],
        processor_func: callable,
        *args,
        **kwargs
    ) -> List[Any]:
        """
        异步批量处理
        
        Args:
            items: 待处理的项目列表
            processor_func: 处理函数
            *args: 处理函数的参数
            **kwargs: 处理函数的关键字参数
            
        Returns:
            List: 处理结果列表
        """
        # 分批处理
        batches = [
            items[i:i + self.max_batch_size]
            for i in range(0, len(items), self.max_batch_size)
        ]
        
        results = []
        semaphore = asyncio.Semaphore(self.max_concurrent)
        
        async def process_batch(batch):
            async with semaphore:
                return await processor_func(batch, *args, **kwargs)
        
        # 并发处理批次
        tasks = [process_batch(batch) for batch in batches]
        batch_results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并结果
        for result in batch_results:
            if isinstance(result, Exception):
                logging.error(f"Batch processing error: {result}")
            elif result:
                results.extend(result if isinstance(result, list) else [result])
        
        return results
    
    def process_batches_sync(
        self,
        items: List[Any],
        processor_func: callable,
        *args,
        **kwargs
    ) -> List[Any]:
        """
        同步批量处理
        """
        batches = [
            items[i:i + self.max_batch_size]
            for i in range(0, len(items), self.max_batch_size)
        ]
        
        results = []
        
        for batch in batches:
            try:
                result = processor_func(batch, *args, **kwargs)
                if result:
                    results.extend(result if isinstance(result, list) else [result])
            except Exception as e:
                logging.error(f"Batch processing error: {e}")
        
        return results


class MemoryOptimizer:
    """内存优化器"""
    
    @staticmethod
    def optimize_order_storage(orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """
        优化订单存储，减少内存使用
        
        Args:
            orders: 订单列表
            
        Returns:
            List: 优化后的订单列表
        """
        # 只保留必要的字段
        essential_fields = {
            "orderId", "symbol", "side", "price", "origQty", 
            "executedQty", "status", "type", "timeInForce"
        }
        
        optimized_orders = []
        for order in orders:
            optimized_order = {
                field: order[field] 
                for field in essential_fields 
                if field in order
            }
            optimized_orders.append(optimized_order)
        
        return optimized_orders
    
    @staticmethod
    def cleanup_old_data(
        data_dict: Dict[str, Any],
        max_age_seconds: float = 3600,
        timestamp_field: str = "timestamp"
    ) -> Dict[str, Any]:
        """
        清理过期数据
        
        Args:
            data_dict: 数据字典
            max_age_seconds: 最大保留时间(秒)
            timestamp_field: 时间戳字段名
            
        Returns:
            Dict: 清理后的数据字典
        """
        current_time = time.time()
        cleaned_dict = {}
        
        for key, value in data_dict.items():
            if isinstance(value, dict) and timestamp_field in value:
                try:
                    timestamp = float(value[timestamp_field])
                    if current_time - timestamp <= max_age_seconds:
                        cleaned_dict[key] = value
                except (ValueError, TypeError):
                    # 如果时间戳无效，保留数据
                    cleaned_dict[key] = value
            else:
                # 没有时间戳的数据直接保留
                cleaned_dict[key] = value
        
        return cleaned_dict


class CacheManager:
    """缓存管理器"""
    
    def __init__(self, max_size: int = 1000, ttl_seconds: float = 300):
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds
        self.cache: Dict[str, Tuple[Any, float]] = {}
    
    def get(self, key: str) -> Optional[Any]:
        """获取缓存值"""
        if key in self.cache:
            value, timestamp = self.cache[key]
            if time.time() - timestamp <= self.ttl_seconds:
                return value
            else:
                # 过期，删除
                del self.cache[key]
        return None
    
    def set(self, key: str, value: Any) -> None:
        """设置缓存值"""
        # 检查缓存大小限制
        if len(self.cache) >= self.max_size:
            self._evict_oldest()
        
        self.cache[key] = (value, time.time())
    
    def _evict_oldest(self) -> None:
        """驱逐最旧的缓存项"""
        if not self.cache:
            return
        
        oldest_key = min(
            self.cache.keys(),
            key=lambda k: self.cache[k][1]
        )
        del self.cache[oldest_key]
    
    def clear_expired(self) -> None:
        """清理过期缓存"""
        current_time = time.time()
        expired_keys = [
            key for key, (value, timestamp) in self.cache.items()
            if current_time - timestamp > self.ttl_seconds
        ]
        
        for key in expired_keys:
            del self.cache[key]


def optimize_redis_operations(operations: List[Tuple[str, str, Any]]) -> List[Any]:
    """
    优化Redis操作，使用pipeline减少网络往返
    
    Args:
        operations: Redis操作列表 [(operation, key, value), ...]
        
    Returns:
        List: 操作结果列表
    """
    try:
        import redis
        
        # 这里假设Redis连接已经建立
        # 实际使用时需要传入Redis连接对象
        r = redis.Redis(host="localhost", port=6379, db=0)
        
        pipeline = r.pipeline()
        
        for operation, key, value in operations:
            if operation == "set":
                pipeline.set(key, value)
            elif operation == "get":
                pipeline.get(key)
            elif operation == "delete":
                pipeline.delete(key)
            elif operation == "exists":
                pipeline.exists(key)
        
        return pipeline.execute()
        
    except ImportError:
        logging.warning("Redis not available, skipping pipeline optimization")
        return []


class PerformanceMonitor:
    """性能监控器"""
    
    def __init__(self):
        self.metrics: Dict[str, List[float]] = defaultdict(list)
    
    def time_function(self, func_name: str):
        """函数执行时间装饰器"""
        def decorator(func):
            def wrapper(*args, **kwargs):
                start_time = time.perf_counter()
                try:
                    result = func(*args, **kwargs)
                    return result
                finally:
                    end_time = time.perf_counter()
                    execution_time = end_time - start_time
                    self.metrics[func_name].append(execution_time)
            return wrapper
        return decorator
    
    def get_statistics(self, func_name: str) -> Dict[str, float]:
        """获取函数执行统计信息"""
        times = self.metrics.get(func_name, [])
        if not times:
            return {}
        
        return {
            "count": len(times),
            "total_time": sum(times),
            "avg_time": sum(times) / len(times),
            "min_time": min(times),
            "max_time": max(times),
        }
    
    def reset_metrics(self, func_name: Optional[str] = None) -> None:
        """重置性能指标"""
        if func_name:
            self.metrics[func_name].clear()
        else:
            self.metrics.clear()


# 全局性能监控器实例
performance_monitor = PerformanceMonitor()


class AsyncOrderProcessor:
    """异步订单处理器，优化批量订单操作"""
    
    def __init__(self, max_concurrent: int = 5, batch_size: int = 100):
        self.max_concurrent = max_concurrent
        self.batch_size = batch_size
        self.semaphore = asyncio.Semaphore(max_concurrent)
        
    async def process_orders_async(
        self,
        orders: List[Dict[str, Any]],
        processor_func: callable,
        *args,
        **kwargs
    ) -> List[Any]:
        """
        异步批量处理订单
        
        Args:
            orders: 订单列表
            processor_func: 处理函数（必须是async函数）
            *args: 处理函数的参数
            **kwargs: 处理函数的关键字参数
            
        Returns:
            List: 处理结果列表
        """
        # 分批处理
        batches = [
            orders[i:i + self.batch_size]
            for i in range(0, len(orders), self.batch_size)
        ]
        
        async def process_batch(batch):
            async with self.semaphore:
                try:
                    return await processor_func(batch, *args, **kwargs)
                except Exception as e:
                    logging.error(f"Batch processing error: {e}")
                    return None
        
        # 并发处理所有批次
        tasks = [process_batch(batch) for batch in batches]
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        # 合并结果，过滤异常
        final_results = []
        for result in results:
            if isinstance(result, Exception):
                logging.error(f"Async processing exception: {result}")
            elif result is not None:
                if isinstance(result, list):
                    final_results.extend(result)
                else:
                    final_results.append(result)
        
        return final_results
    
    async def process_order_batches_parallel(
        self,
        add_orders: List[Dict[str, Any]],
        cancel_orders: List[Dict[str, Any]],
        add_processor: callable,
        cancel_processor: callable
    ) -> Dict[str, List]:
        """
        并行处理添加和取消订单
        
        Args:
            add_orders: 要添加的订单
            cancel_orders: 要取消的订单
            add_processor: 添加订单处理函数
            cancel_processor: 取消订单处理函数
            
        Returns:
            Dict: 包含add_results和cancel_results的字典
        """
        tasks = []
        
        if add_orders:
            tasks.append(self.process_orders_async(add_orders, add_processor))
        
        if cancel_orders:
            tasks.append(self.process_orders_async(cancel_orders, cancel_processor))
        
        if not tasks:
            return {"add_results": [], "cancel_results": []}
        
        results = await asyncio.gather(*tasks, return_exceptions=True)
        
        return {
            "add_results": results[0] if len(results) > 0 and not isinstance(results[0], Exception) else [],
            "cancel_results": results[1] if len(results) > 1 and not isinstance(results[1], Exception) else []
        }


def optimize_batch_operations(
    orders: List[Dict[str, Any]], 
    max_batch_size: int = 100,
    operation_type: str = "mixed"
) -> List[List[Dict[str, Any]]]:
    """
    优化批量操作的分组策略
    
    Args:
        orders: 订单列表
        max_batch_size: 最大批量大小
        operation_type: 操作类型 (add, cancel, mixed)
        
    Returns:
        List: 优化后的批次分组
    """
    if not orders:
        return []
    
    # 按操作类型分组优化
    if operation_type == "mixed":
        # 混合操作时，按side分组以提高处理效率
        buy_orders = [order for order in orders if order.get("side") == "BUY"]
        sell_orders = [order for order in orders if order.get("side") == "SELL"]
        
        batches = []
        
        # 为买单和卖单分别创建批次
        for order_group in [buy_orders, sell_orders]:
            for i in range(0, len(order_group), max_batch_size):
                batch = order_group[i:i + max_batch_size]
                if batch:
                    batches.append(batch)
        
        return batches
    else:
        # 单一操作类型，直接按大小分批
        return [
            orders[i:i + max_batch_size]
            for i in range(0, len(orders), max_batch_size)
        ]


class ConnectionPool:
    """连接池管理器，优化API调用"""
    
    def __init__(self, max_connections: int = 10):
        self.max_connections = max_connections
        self.semaphore = asyncio.Semaphore(max_connections)
        self.active_connections = 0
        
    async def acquire_connection(self):
        """获取连接"""
        await self.semaphore.acquire()
        self.active_connections += 1
        
    def release_connection(self):
        """释放连接"""
        self.semaphore.release()
        self.active_connections = max(0, self.active_connections - 1)
        
    async def execute_with_connection(self, func: callable, *args, **kwargs):
        """使用连接池执行函数"""
        await self.acquire_connection()
        try:
            if asyncio.iscoroutinefunction(func):
                return await func(*args, **kwargs)
            else:
                return func(*args, **kwargs)
        finally:
            self.release_connection()
    
    def get_stats(self) -> Dict[str, int]:
        """获取连接池统计信息"""
        return {
            "max_connections": self.max_connections,
            "active_connections": self.active_connections,
            "available_connections": self.max_connections - self.active_connections
        }


# 全局异步处理器实例
async_order_processor = AsyncOrderProcessor()
connection_pool = ConnectionPool()