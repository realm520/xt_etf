# -*- coding:utf-8 -*-

"""
ETF测试配置和通用fixtures

Author: Claude Code
Date: 2025-01-22
"""

import pytest
import redis
import time
import logging
from unittest.mock import MagicMock
from typing import Generator


# 配置测试日志级别
logging.getLogger().setLevel(logging.WARNING)


@pytest.fixture(scope="session")
def redis_test_db():
    """Session级别的Redis测试数据库"""
    try:
        r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        r.ping()
        yield r
        r.flushdb()  # 清理测试数据
    except:
        pytest.skip("Redis not available for testing")


@pytest.fixture
def clean_redis(redis_test_db):
    """每个测试前清理Redis数据"""
    redis_test_db.flushdb()
    yield redis_test_db
    redis_test_db.flushdb()


@pytest.fixture
def mock_exchange_client():
    """标准的模拟交易所客户端"""
    client = MagicMock()
    
    # 默认深度数据
    client.get_depth.return_value = {
        "symbol": "btc3l_usdt",
        "timestamp": int(time.time() * 1000),
        "bids": [["1.0000", "100"], ["0.9999", "200"], ["0.9998", "300"]],
        "asks": [["1.0001", "100"], ["1.0002", "200"], ["1.0003", "300"]]
    }
    
    # 默认ticker数据
    client.get_tickers.return_value = [{"s": "btc3l_usdt", "p": "1.0000"}]
    
    # 默认K线数据
    client.get_kline.return_value = [
        {"c": "1.0000", "h": "1.0050", "l": "0.9950", "o": "1.0000"},
        {"c": "1.0010", "h": "1.0060", "l": "0.9960", "o": "1.0000"},
        {"c": "1.0005", "h": "1.0055", "l": "0.9955", "o": "1.0010"}
    ]
    
    # 默认订单操作
    client.get_open_orders.return_value = []
    client.order.return_value = {"orderId": "test_order_123", "status": "NEW"}
    client.batch_orders.return_value = {"success": True, "orderIds": ["123", "124"]}
    client.cancel_order.return_value = {"orderId": "test_order_123", "status": "CANCELED"}
    client.batch_cancel.return_value = {"success": True}
    
    return client


@pytest.fixture
def basic_risk_params():
    """基础风控参数"""
    return {
        "stop_loss": {
            "enabled": True,
            "fixed_threshold": -0.02,
            "trailing_stop": 0.01,
            "time_stop": 24,
            "cooldown": 60,
            "enable_partial_close": True
        },
        "orderbook_threshold": [0.8, 0.6, 0.4],
        "base_bid_volume": 100.0,
        "base_ask_volume": 100.0,
        "price_deviation_threshold": [0.05, 0.03, 0.01]
    }


@pytest.fixture
def basic_strategy_config():
    """基础策略配置"""
    return {
        "symbol": "btc3l_usdt",
        "netvalue": "netvalue_btc3l_usdt",
        "bid_ask_spread": 0.01,
        "anti_pin_rate": 0.1,
        "anti_pin_usdt": 1000,
        "precision": 4,
        "prec_amount": 2,
        "wash": "mid_price",
        "kline_continuity_interval": 60
    }


@pytest.fixture
def performance_timer():
    """性能计时器fixture"""
    times = {}
    
    def timer(name: str = "default"):
        def decorator(func):
            def wrapper(*args, **kwargs):
                start_time = time.time()
                result = func(*args, **kwargs)
                end_time = time.time()
                times[name] = end_time - start_time
                return result
            return wrapper
        return decorator
    
    timer.times = times
    return timer


@pytest.fixture
def benchmark_runner():
    """基准测试运行器"""
    results = {}
    
    def run_benchmark(name: str, func, *args, iterations: int = 100, **kwargs):
        """运行基准测试"""
        times = []
        
        for _ in range(iterations):
            start_time = time.perf_counter()
            result = func(*args, **kwargs)
            end_time = time.perf_counter()
            times.append(end_time - start_time)
        
        avg_time = sum(times) / len(times)
        min_time = min(times)
        max_time = max(times)
        
        results[name] = {
            "avg_time": avg_time,
            "min_time": min_time,
            "max_time": max_time,
            "iterations": iterations,
            "total_time": sum(times)
        }
        
        return result
    
    run_benchmark.results = results
    return run_benchmark


# 测试辅助函数

def assert_within_range(value, expected, tolerance_percent=5):
    """断言值在预期范围内"""
    tolerance = abs(expected * tolerance_percent / 100)
    assert abs(value - expected) <= tolerance, f"Value {value} is not within {tolerance_percent}% of {expected}"


def assert_performance_threshold(execution_time, threshold_seconds=1.0):
    """断言性能阈值"""
    assert execution_time <= threshold_seconds, f"Execution time {execution_time:.3f}s exceeds threshold {threshold_seconds}s"


def create_mock_orders(count: int, symbol: str = "BTCUSDT", base_price: float = 50000.0):
    """创建模拟订单列表"""
    orders = []
    for i in range(count):
        orders.append({
            "orderId": f"mock_order_{i}",
            "symbol": symbol,
            "price": f"{base_price + i * 0.01}",
            "origQty": f"{10 + i}",
            "side": "SELL" if i % 2 == 0 else "BUY",
            "state": "NEW",
            "clientOrderId": f"client_order_{i}"
        })
    return orders


def create_mock_depth_data(
    mid_price: float = 1.0,
    spread: float = 0.0002,
    depth: int = 10
):
    """创建模拟深度数据"""
    bid_price = mid_price - spread / 2
    ask_price = mid_price + spread / 2
    
    bids = []
    asks = []
    
    for i in range(depth):
        bid_level_price = bid_price - i * 0.0001
        ask_level_price = ask_price + i * 0.0001
        
        bids.append([f"{bid_level_price:.4f}", f"{100 + i * 10}"])
        asks.append([f"{ask_level_price:.4f}", f"{100 + i * 10}"])
    
    return {
        "symbol": "btc3l_usdt",
        "timestamp": int(time.time() * 1000),
        "bids": bids,
        "asks": asks
    }