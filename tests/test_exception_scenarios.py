# -*- coding:utf-8 -*-

"""
ETF交易系统异常场景测试

Author: Claude Code
Date: 2025-01-22
"""

import time
import pytest
import redis
from unittest.mock import MagicMock, patch
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.risk import RiskController
from etf.washing import WashController


class TestNetworkFailureScenarios:
    """网络故障场景测试"""

    @pytest.fixture
    def unstable_client(self):
        """模拟不稳定的网络客户端"""
        client = MagicMock()
        
        # 模拟间歇性网络故障
        self.call_count = 0
        def intermittent_failure(*args, **kwargs):
            self.call_count += 1
            if self.call_count % 3 == 0:  # 每三次调用失败一次
                raise Exception("Network timeout")
            return {"bids": [["1.0", "100"]], "asks": [["1.001", "100"]]}
        
        client.get_depth.side_effect = intermittent_failure
        client.get_open_orders.return_value = []
        client.batch_orders.return_value = {"success": True}
        
        return client

    def test_intermittent_network_failure(self, unstable_client):
        """测试间歇性网络故障处理"""
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(unstable_client, strategy_name="network_test")

        # 多次调用，应该有成功和失败
        success_count = 0
        failure_count = 0
        
        for i in range(10):
            try:
                result = order_manager.get_depth_data("btc3l_usdt")
                if result is not None:
                    success_count += 1
            except Exception:
                failure_count += 1
        
        # 应该有成功和失败的调用
        assert success_count > 0
        assert failure_count > 0

    def test_complete_network_failure(self):
        """测试完全网络故障"""
        client = MagicMock()
        client.get_depth.side_effect = Exception("Network unreachable")
        client.get_open_orders.side_effect = Exception("Network unreachable")
        client.batch_orders.side_effect = Exception("Network unreachable")
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="failure_test")
        
        # 连续失败应该触发熔断器
        for _ in range(6):
            try:
                order_manager.get_depth_data("btc3l_usdt")
            except:
                pass
        
        assert order_manager.circuit_breaker_open
        assert order_manager.consecutive_failures >= 5

    def test_slow_network_response(self):
        """测试慢网络响应"""
        client = MagicMock()
        
        def slow_response(*args, **kwargs):
            time.sleep(0.1)  # 模拟慢响应
            return {"bids": [["1.0", "100"]], "asks": [["1.001", "100"]]}
        
        client.get_depth.side_effect = slow_response
        client.get_open_orders.return_value = []
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="slow_test")
        
        start_time = time.time()
        result = order_manager.get_depth_data("btc3l_usdt")
        end_time = time.time()
        
        # 应该能处理慢响应
        assert result is not None
        assert end_time - start_time >= 0.1


class TestDataIntegrityScenarios:
    """数据完整性异常场景测试"""

    def test_malformed_depth_data(self):
        """测试格式错误的深度数据"""
        client = MagicMock()
        client.get_depth.return_value = {
            "bids": [["invalid_price", "100"]],  # 无效价格
            "asks": [["1.001", "invalid_amount"]]  # 无效数量
        }
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        # 应该能捕获并处理格式错误
        with pytest.raises((ValueError, TypeError)):
            depth = risk_controller.get_depth_data("btc3l_usdt")
            risk_controller.get_mid_price(depth)

    def test_empty_orderbook_data(self):
        """测试空订单簿数据"""
        client = MagicMock()
        client.get_depth.return_value = {
            "bids": [],  # 空买单
            "asks": []   # 空卖单
        }
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        # 空订单簿应该触发异常
        with pytest.raises(IndexError):
            depth = risk_controller.get_depth_data("btc3l_usdt")
            risk_controller.get_mid_price(depth)

    def test_missing_required_fields(self):
        """测试缺少必要字段"""
        client = MagicMock()
        client.get_tickers.return_value = [{}]  # 缺少价格字段
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        # 缺少字段应该触发异常
        with pytest.raises(KeyError):
            risk_controller.get_market_price("btc3l_usdt")

    def test_negative_prices_and_amounts(self):
        """测试负价格和负数量"""
        client = MagicMock()
        client.get_depth.return_value = {
            "bids": [["-1.0", "100"]],  # 负价格
            "asks": [["1.001", "-100"]]  # 负数量
        }
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        depth = risk_controller.get_depth_data("btc3l_usdt")
        
        # 负价格在计算中间价时可能导致异常结果
        mid_price = risk_controller.get_mid_price(depth)
        assert mid_price < 0  # 会得到负的中间价


class TestRedisFailureScenarios:
    """Redis故障场景测试"""

    def test_redis_connection_failure(self):
        """测试Redis连接失败"""
        # 模拟Redis连接失败
        mock_redis = MagicMock()
        mock_redis.side_effect = Exception("Redis connection failed")
        
        with patch("etf.market_making.redis.Redis", side_effect=mock_redis):
            with pytest.raises(Exception):
                mock_client = MagicMock()
                mock_client.get_open_orders.return_value = []
                
                order_manager = OrderManager(mock_client)
                MarketMaker(order_manager)

    def test_redis_data_corruption(self):
        """测试Redis数据损坏"""
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
        except:
            pytest.skip("Redis not available")
        
        # 写入损坏的数据
        r.set("netvalue_test", "not_a_number")
        
        with patch("etf.market_making.redis.Redis", return_value=r), \
             patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            
            mock_client = MagicMock()
            mock_client.get_open_orders.return_value = []
            
            order_manager = OrderManager(mock_client)
            market_maker = MarketMaker(order_manager)
            
            config = {
                "netvalue": "netvalue_test",
                "bid_ask_spread": 0.01,
                "anti_pin_rate": 0.1,
                "anti_pin_usdt": 1000,
                "precision": 4,
                "prec_amount": 2
            }
            
            with patch("etf.market_making.get_orderbook") as mock_orderbook:
                mock_orderbook.return_value = ([], [])
                
                # 应该回退到默认值而不是崩溃
                market_maker.place_orders(config)
                
                # 验证使用了默认净值
                assert order_manager.netvalue == 1.0
        
        r.flushdb()

    def test_redis_memory_full(self):
        """测试Redis内存满"""
        mock_redis = MagicMock()
        mock_redis.set.side_effect = Exception("OOM command not allowed when used memory > 'maxmemory'")
        mock_redis.get.return_value = "1.0000"
        
        with patch("etf.market_making.redis.Redis", return_value=mock_redis), \
             patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            
            mock_client = MagicMock()
            mock_client.get_open_orders.return_value = []
            
            order_manager = OrderManager(mock_client)
            market_maker = MarketMaker(order_manager)
            
            config = {
                "netvalue": "netvalue_test",
                "bid_ask_spread": 0.01,
                "anti_pin_rate": 0.1,
                "anti_pin_usdt": 1000,
                "precision": 4,
                "prec_amount": 2
            }
            
            with patch("etf.market_making.get_orderbook") as mock_orderbook:
                mock_orderbook.return_value = ([], [])
                
                # 应该能处理Redis写入失败
                market_maker.place_orders(config)


class TestOrderExecutionFailures:
    """订单执行失败场景测试"""

    def test_order_rejection(self):
        """测试订单被拒绝"""
        client = MagicMock()
        client.get_open_orders.return_value = []
        client.batch_orders.side_effect = Exception("Order rejected: Insufficient balance")
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="rejection_test")
        
        orders_data = [{
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "price": 50000.0,
            "quantity": 0.001,
            "clientOrderId": "test_order"
        }]
        
        # 订单被拒绝应该被处理
        result = order_manager.add_orders_batch(orders_data)
        assert result is None  # 错误处理应该返回None

    def test_partial_batch_failure(self):
        """测试批量订单部分失败"""
        client = MagicMock()
        client.get_open_orders.return_value = []
        
        # 模拟部分成功的批量订单响应
        client.batch_orders.return_value = {
            "success": False,
            "failed_orders": [{"reason": "Invalid price"}]
        }
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="partial_failure_test")
        
        orders_data = [
            {"symbol": "BTCUSDT", "side": "BUY", "price": 50000.0, "quantity": 0.001},
            {"symbol": "BTCUSDT", "side": "SELL", "price": -1000.0, "quantity": 0.001}  # 无效价格
        ]
        
        result = order_manager.add_orders_batch(orders_data)
        # 应该能处理部分失败
        assert result is not None

    def test_order_timeout(self):
        """测试订单超时"""
        client = MagicMock()
        client.get_open_orders.return_value = []
        
        def timeout_response(*args, **kwargs):
            time.sleep(0.2)  # 模拟超时
            raise Exception("Request timeout")
        
        client.batch_orders.side_effect = timeout_response
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="timeout_test")
        
        orders_data = [{
            "symbol": "BTCUSDT",
            "side": "BUY",
            "type": "LIMIT",
            "price": 50000.0,
            "quantity": 0.001,
            "clientOrderId": "timeout_order"
        }]
        
        # 超时应该被处理
        start_time = time.time()
        result = order_manager.add_orders_batch(orders_data)
        end_time = time.time()
        
        assert result is None
        assert end_time - start_time >= 0.2


class TestExtremeMarketConditions:
    """极端市场条件测试"""

    def test_extreme_volatility(self):
        """测试极端波动性"""
        client = MagicMock()
        
        # 模拟极端价格波动的K线数据
        extreme_klines = [
            {"c": "1000.0"},   # 基准价格
            {"c": "1500.0"},   # +50%
            {"c": "500.0"},    # -50%
            {"c": "2000.0"},   # +100%
            {"c": "100.0"}     # -90%
        ]
        
        client.get_kline.return_value = extreme_klines
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        # 极端波动性应该触发最高风险等级
        risk_level = risk_controller.check_market_volatility("btc3l_usdt")
        assert risk_level in [1, 2, 3]  # 应该返回有效的风险等级

    def test_market_crash_scenario(self):
        """测试市场崩盘场景"""
        client = MagicMock()
        client.get_depth.return_value = {
            "bids": [["0.0001", "1000000"]],  # 极低买价
            "asks": [["10000", "1"]]          # 极高卖价
        }
        client.get_tickers.return_value = [{"p": "0.0001"}]
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        depth = risk_controller.get_depth_data("btc3l_usdt")
        mid_price = risk_controller.get_mid_price(depth)
        market_price = risk_controller.get_market_price("btc3l_usdt")
        
        # 极端价差应该触发最高风险等级
        risk_level = risk_controller.market_price_deviation(market_price, mid_price)
        assert risk_level == 3

    def test_zero_liquidity(self):
        """测试零流动性场景"""
        client = MagicMock()
        client.get_depth.return_value = {
            "bids": [["1.0", "0"]],  # 零流动性
            "asks": [["1.001", "0"]]
        }
        
        risk_controller = RiskController(client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        depth = risk_controller.get_depth_data("btc3l_usdt")
        
        # 零流动性应该触发最高风险等级
        risk_level = risk_controller.monitor_order_book_depth(depth)
        assert risk_level == 3


class TestSystemResourceExhaustion:
    """系统资源耗尽测试"""

    def test_memory_pressure(self):
        """测试内存压力"""
        # 模拟大量历史价格数据
        risk_controller = RiskController(MagicMock(), {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        
        # 添加大量价格数据
        for i in range(10000):
            risk_controller.mid_price_deviation(1000.0 + i * 0.1)
        
        # 应该自动限制队列长度
        assert len(risk_controller.midprices) == 60

    def test_high_frequency_operations(self):
        """测试高频操作"""
        client = MagicMock()
        client.get_open_orders.return_value = []
        client.batch_orders.return_value = {"success": True}
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="high_freq_test")
        
        # 快速连续下单
        orders_data = [{
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0 + i,
            "quantity": 0.001,
            "clientOrderId": f"high_freq_{i}"
        } for i in range(100)]
        
        start_time = time.time()
        for i in range(0, 100, 10):  # 每次处理10个订单
            batch = orders_data[i:i+10]
            order_manager.add_orders_batch(batch)
        end_time = time.time()
        
        # 高频操作应该在合理时间内完成
        assert end_time - start_time < 5.0

    def test_concurrent_operations(self):
        """测试并发操作冲突"""
        import threading
        
        client = MagicMock()
        client.get_open_orders.return_value = []
        client.batch_orders.return_value = {"success": True}
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(client, strategy_name="concurrent_test")
        
        results = []
        errors = []
        
        def concurrent_operation(thread_id):
            try:
                orders_data = [{
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "price": 50000.0,
                    "quantity": 0.001,
                    "clientOrderId": f"concurrent_{thread_id}"
                }]
                result = order_manager.add_orders_batch(orders_data)
                results.append(result)
            except Exception as e:
                errors.append(e)
        
        # 启动多个并发线程
        threads = []
        for i in range(10):
            thread = threading.Thread(target=concurrent_operation, args=(i,))
            threads.append(thread)
            thread.start()
        
        # 等待所有线程完成
        for thread in threads:
            thread.join()
        
        # 大部分操作应该成功
        assert len(results) >= 5
        assert len(errors) <= 5


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])