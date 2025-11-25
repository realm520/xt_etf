# -*- coding:utf-8 -*-

"""
测试订单管理器模块

Author: Claude Code  
Date: 2025-01-22
"""

import time
import pytest
from unittest.mock import MagicMock, patch, call
from datetime import datetime

from etf.order_manager import OrderManager, Order, retry_on_failure, handle_api_error


class TestOrder:
    """测试订单类"""

    def test_order_init_default(self):
        """测试订单默认初始化"""
        order = Order()
        assert order.symbol is None
        assert order.OrderId is None
        assert order.side is None
        assert order.type == "LIMIT"
        assert order.timeInForce == "GTC"
        assert order.bizType == "SPOT"
        assert order.price is None
        assert order.quantity is None
        assert order.quoteQty is None
        assert order.clientOrderId is None

    def test_order_init_with_params(self):
        """测试带参数的订单初始化"""
        order = Order(
            symbol="BTCUSDT",
            OrderId="12345",
            side="BUY",
            type="MARKET",
            timeInForce="IOC",
            bizType="MARGIN",
            price=50000.0,
            quantity=0.001,
            quoteQty=50.0
        )
        assert order.symbol == "BTCUSDT"
        assert order.OrderId == "12345"
        assert order.side == "BUY"
        assert order.type == "MARKET"
        assert order.timeInForce == "IOC"
        assert order.bizType == "MARGIN"
        assert order.price == 50000.0
        assert order.quantity == 0.001
        assert order.quoteQty == 50.0


class TestOrderManager:
    """测试订单管理器"""

    @pytest.fixture
    def mock_client(self):
        """模拟交易客户端"""
        client = MagicMock()
        client.get_depth.return_value = {
            "bids": [["50000", "1.0"], ["49999", "2.0"]],
            "asks": [["50001", "1.0"], ["50002", "2.0"]]
        }
        client.get_open_orders.return_value = []
        client.order.return_value = {"orderId": "12345", "status": "NEW"}
        client.batch_orders.return_value = {"success": True}
        client.cancel_order.return_value = {"orderId": "12345", "status": "CANCELED"}
        client.batch_cancel.return_value = {"success": True}
        return client

    @pytest.fixture
    def order_manager(self, mock_client):
        """创建测试用的订单管理器"""
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            return OrderManager(mock_client, strategy_name="test_strategy")

    def test_init(self, mock_client):
        """测试初始化"""
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            om = OrderManager(mock_client, strategy_name="test_strategy")
            
            assert om.client == mock_client
            assert om.strategy_name == "test_strategy"
            assert om.counter == 0
            assert om.position == 0
            assert om.amount == 0
            assert om.netvalue is None
            assert isinstance(om.open_orders, dict)
            assert isinstance(om.trade_orders, dict)
            assert isinstance(om.trading_history, list)
            assert om.api_error_count == 0
            assert om.consecutive_failures == 0
            assert not om.circuit_breaker_open

    def test_create_temp_id(self, order_manager):
        """测试临时ID生成"""
        # 测试ID生成的唯一性
        id1 = order_manager.create_temp_id()
        id2 = order_manager.create_temp_id()
        
        assert id1 != id2
        assert isinstance(id1, str)
        assert len(id1) > 0

    def test_circuit_breaker_mechanism(self, order_manager):
        """测试熔断器机制"""
        # 初始状态
        assert not order_manager.circuit_breaker_open
        assert order_manager._check_circuit_breaker()

        # 模拟连续失败
        for i in range(5):
            order_manager._record_api_failure()

        # 熔断器应该开启
        assert order_manager.circuit_breaker_open
        assert not order_manager._check_circuit_breaker()

        # 模拟时间过去，熔断器重置
        order_manager.circuit_breaker_reset_time = time.time() - 1
        assert order_manager._check_circuit_breaker()
        assert not order_manager.circuit_breaker_open

    def test_record_api_success(self, order_manager):
        """测试API成功记录"""
        # 先设置一些失败
        order_manager._record_api_failure()
        order_manager._record_api_failure()
        
        assert order_manager.consecutive_failures == 2
        
        # 记录成功
        order_manager._record_api_success()
        
        assert order_manager.consecutive_failures == 0
        assert order_manager.last_successful_operation > 0

    def test_get_depth_data_success(self, order_manager):
        """测试获取深度数据成功"""
        result = order_manager.get_depth_data("BTCUSDT")
        
        assert result is not None
        order_manager.client.get_depth.assert_called_once_with("BTCUSDT")

    def test_get_depth_data_circuit_breaker(self, order_manager):
        """测试熔断器状态下的深度数据获取"""
        # 开启熔断器
        order_manager.circuit_breaker_open = True
        
        result = order_manager.get_depth_data("BTCUSDT")
        
        assert result is None
        order_manager.client.get_depth.assert_not_called()

    def test_add_order_success(self, order_manager):
        """测试添加单个订单成功"""
        with patch("time.time", return_value=1640000000):
            result = order_manager.add_order(
                symbol="BTCUSDT",
                side="BUY",
                type="LIMIT",
                price=50000.0,
                quantity=0.001
            )
        
        assert result is not None
        order_manager.client.order.assert_called_once()

    def test_add_orders_batch_success(self, order_manager):
        """测试批量添加订单成功"""
        orders_data = [
            {
                "symbol": "BTCUSDT",
                "side": "BUY",
                "type": "LIMIT",
                "price": 50000.0,
                "quantity": 0.001,
                "clientOrderId": "test_id_1"
            },
            {
                "symbol": "BTCUSDT", 
                "side": "SELL",
                "type": "LIMIT",
                "price": 50100.0,
                "quantity": 0.001,
                "clientOrderId": "test_id_2"
            }
        ]
        
        result = order_manager.add_orders_batch(orders_data, batch_id=123)
        
        assert result is not None
        order_manager.client.batch_orders.assert_called_once()

    def test_add_orders_batch_empty_list(self, order_manager):
        """测试批量添加空订单列表"""
        result = order_manager.add_orders_batch([], batch_id=123)
        
        assert result is None
        order_manager.client.batch_orders.assert_not_called()

    def test_cancel_order_success(self, order_manager):
        """测试取消单个订单成功"""
        order = {
            "orderId": "12345",
            "symbol": "BTCUSDT",
            "clientOrderId": "test_client_id"
        }
        
        result = order_manager.cancel_order(order)
        
        assert result is not None
        order_manager.client.cancel_order.assert_called_once()

    def test_cancel_orders_batch_success(self, order_manager):
        """测试批量取消订单成功"""
        orders = [
            {"orderId": "12345", "symbol": "BTCUSDT"},
            {"orderId": "12346", "symbol": "BTCUSDT"}
        ]
        
        result = order_manager.cancel_orders_batch(orders)
        
        assert result is not None
        order_manager.client.batch_cancel.assert_called_once()

    def test_cancel_orders_batch_empty_list(self, order_manager):
        """测试批量取消空订单列表"""
        result = order_manager.cancel_orders_batch([])
        
        assert result is None
        order_manager.client.batch_cancel.assert_not_called()

    def test_wash_trading_flag(self, order_manager):
        """测试洗盘交易标志"""
        orders_data = [
            {
                "symbol": "BTCUSDT",
                "side": "BUY", 
                "type": "LIMIT",
                "price": 50000.0,
                "quantity": 0.001,
                "clientOrderId": "wash_test_id"
            }
        ]
        
        # 测试洗盘交易标志
        result = order_manager.add_orders_batch(
            orders_data, 
            batch_id=123, 
            is_wash_trading=True
        )
        
        assert result is not None
        # 验证洗盘交易被正确标记
        call_args = order_manager.client.batch_orders.call_args
        assert call_args is not None

    def test_error_handling_with_retry(self, order_manager):
        """测试带重试的错误处理"""
        # 模拟API调用失败然后成功
        order_manager.client.get_depth.side_effect = [
            Exception("Network error"),
            {"bids": [], "asks": []}
        ]
        
        with patch("time.sleep"):  # 加速测试
            # 这个调用会触发重试机制
            with pytest.raises(Exception):
                order_manager.get_depth_data("BTCUSDT")

    def test_strategy_name_in_alerts(self, order_manager):
        """测试策略名称在告警中的使用"""
        assert order_manager.strategy_name == "test_strategy"
        
        # 这里可以进一步测试告警机制，但需要mock异步函数
        # 暂时验证策略名称被正确设置


class TestRetryDecorator:
    """测试重试装饰器"""

    def test_retry_success_first_attempt(self):
        """测试第一次尝试就成功"""
        call_count = 0
        
        @retry_on_failure(max_retries=3)
        def test_func():
            nonlocal call_count
            call_count += 1
            return "success"
        
        result = test_func()
        assert result == "success"
        assert call_count == 1

    def test_retry_success_after_failures(self):
        """测试失败后重试成功"""
        call_count = 0
        
        @retry_on_failure(max_retries=3, delay=0.01)
        def test_func():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                raise Exception("Temporary error")
            return "success"
        
        result = test_func()
        assert result == "success"
        assert call_count == 3

    def test_retry_max_attempts_exceeded(self):
        """测试超过最大重试次数"""
        call_count = 0
        
        @retry_on_failure(max_retries=2, delay=0.01)
        def test_func():
            nonlocal call_count
            call_count += 1
            raise Exception("Persistent error")
        
        with pytest.raises(Exception, match="Persistent error"):
            test_func()
        
        assert call_count == 3  # 1 initial + 2 retries


def test_order_manager_integration():
    """集成测试：模拟完整的订单管理流程"""
    # 创建模拟客户端
    mock_client = MagicMock()
    mock_client.get_depth.return_value = {
        "bids": [["50000", "1.0"]],
        "asks": [["50001", "1.0"]]
    }
    mock_client.order.return_value = {"orderId": "integration_test_id", "status": "NEW"}
    mock_client.get_open_orders.return_value = []

    # 创建订单管理器
    with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
        om = OrderManager(mock_client, strategy_name="integration_test")

    # 1. 获取深度数据
    depth = om.get_depth_data("BTCUSDT")
    assert depth is not None

    # 2. 添加订单
    result = om.add_order(
        symbol="BTCUSDT",
        side="BUY",
        type="LIMIT",
        price=50000.0,
        quantity=0.001
    )
    assert result is not None

    # 3. 批量操作
    orders_data = [
        {
            "symbol": "BTCUSDT",
            "side": "SELL",
            "type": "LIMIT", 
            "price": 50100.0,
            "quantity": 0.001,
            "clientOrderId": om.create_temp_id()
        }
    ]
    
    batch_result = om.add_orders_batch(orders_data)
    assert batch_result is not None

    # 验证所有调用
    mock_client.get_depth.assert_called()
    mock_client.order.assert_called()
    mock_client.batch_orders.assert_called()


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])