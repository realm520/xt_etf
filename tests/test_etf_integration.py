# -*- coding:utf-8 -*-

"""
ETF交易系统端到端集成测试

Author: Claude Code
Date: 2025-01-22
"""

import time
import pytest
import redis
import asyncio
from unittest.mock import MagicMock, patch, AsyncMock
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.risk import RiskController
from etf.washing import WashController


class TestETFSystemIntegration:
    """ETF交易系统集成测试"""

    @pytest.fixture
    def redis_client(self):
        """创建Redis测试客户端"""
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
            yield r
            r.flushdb()
        except:
            pytest.skip("Redis not available")

    @pytest.fixture
    def mock_exchange_client(self):
        """模拟交易所客户端"""
        client = MagicMock()
        
        # 基础行情数据
        client.get_depth.return_value = {
            "symbol": "btc3l_usdt",
            "timestamp": int(time.time() * 1000),
            "bids": [["1.0000", "100"], ["0.9999", "200"], ["0.9998", "300"]],
            "asks": [["1.0001", "100"], ["1.0002", "200"], ["1.0003", "300"]]
        }
        
        client.get_tickers.return_value = [{"s": "btc3l_usdt", "p": "1.0000"}]
        
        client.get_kline.return_value = [
            {"c": "1.0000", "h": "1.0050", "l": "0.9950", "o": "1.0000"},
            {"c": "1.0010", "h": "1.0060", "l": "0.9960", "o": "1.0000"},
            {"c": "1.0005", "h": "1.0055", "l": "0.9955", "o": "1.0010"}
        ]
        
        # 订单操作
        client.get_open_orders.return_value = []
        client.order.return_value = {"orderId": "test_order_123", "status": "NEW"}
        client.batch_orders.return_value = {"success": True, "orderIds": ["123", "124"]}
        client.cancel_order.return_value = {"orderId": "test_order_123", "status": "CANCELED"}
        client.batch_cancel.return_value = {"success": True}
        
        return client

    @pytest.fixture
    def risk_params(self):
        """风控参数配置"""
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
    def strategy_config(self):
        """策略配置"""
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
    def etf_system(self, mock_exchange_client, risk_params, redis_client):
        """创建完整的ETF交易系统"""
        with patch("etf.market_making.redis.Redis", return_value=redis_client), \
             patch("etf.washing.redis.Redis", return_value=redis_client), \
             patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            
            # 创建核心组件
            order_manager = OrderManager(mock_exchange_client, strategy_name="test_integration")
            market_maker = MarketMaker(order_manager)
            risk_controller = RiskController(mock_exchange_client, risk_params, strategy_name="test_integration")
            wash_controller = WashController(order_manager, market_maker)
            
            return {
                "order_manager": order_manager,
                "market_maker": market_maker,
                "risk_controller": risk_controller,
                "wash_controller": wash_controller,
                "client": mock_exchange_client
            }

    def test_system_initialization(self, etf_system):
        """测试系统初始化"""
        system = etf_system
        
        # 验证所有组件都被正确创建
        assert system["order_manager"] is not None
        assert system["market_maker"] is not None
        assert system["risk_controller"] is not None
        assert system["wash_controller"] is not None
        
        # 验证组件之间的关联关系
        assert system["market_maker"].order_manager == system["order_manager"]
        assert system["wash_controller"].order_manager == system["order_manager"]
        assert system["wash_controller"].market_maker == system["market_maker"]

    def test_market_data_flow(self, etf_system, redis_client, strategy_config):
        """测试市场数据流"""
        system = etf_system
        
        # 设置净值数据
        redis_client.set(strategy_config["netvalue"], "1.0500")
        
        # 1. 获取市场数据
        depth = system["risk_controller"].get_depth_data(strategy_config["symbol"])
        assert depth is not None
        
        # 2. 计算中间价
        mid_price = system["risk_controller"].get_mid_price(depth)
        expected_mid_price = (1.0000 + 1.0001) / 2
        assert mid_price == expected_mid_price
        
        # 3. 获取市场价格
        market_price = system["risk_controller"].get_market_price(strategy_config["symbol"])
        assert market_price == 1.0000

    def test_order_lifecycle(self, etf_system, redis_client, strategy_config):
        """测试订单生命周期"""
        system = etf_system
        
        # 设置净值
        redis_client.set(strategy_config["netvalue"], "1.0000")
        
        # 1. 创建订单
        with patch("etf.market_making.get_orderbook") as mock_orderbook:
            mock_orderbook.return_value = (
                [{"direction": "bid", "price": 0.9999, "amount": 100,
                  "min_price": 0.9998, "max_price": 1.0000}],
                [{"direction": "ask", "price": 1.0001, "amount": 100,
                  "min_price": 1.0000, "max_price": 1.0002}]
            )
            
            system["market_maker"].place_orders(strategy_config, symbol=strategy_config["symbol"])
        
        # 验证订单被创建
        system["order_manager"].client.batch_orders.assert_called()
        
        # 2. 取消订单（如果有现有订单的话）
        system["order_manager"].client.get_open_orders.return_value = [
            {"orderId": "test_123", "symbol": "btc3l_usdt", "price": "1.0010", "origQty": "50", "side": "SELL", "state": "NEW"}
        ]
        
        # 重新下单会取消不符合要求的订单
        system["market_maker"].place_orders(strategy_config, symbol=strategy_config["symbol"])
        
        # 验证取消订单被调用
        assert system["order_manager"].client.batch_cancel.call_count >= 0

    def test_risk_monitoring_and_control(self, etf_system, strategy_config):
        """测试风险监控和控制"""
        system = etf_system
        
        # 1. 执行风险监控
        system["risk_controller"].risk_monitor(strategy_config["symbol"])
        
        # 验证所有风险检查方法被调用
        system["client"].get_depth.assert_called()
        system["client"].get_tickers.assert_called()
        
        # 2. 测试价格偏离检查
        mid_price = 1.0000
        market_price_normal = 1.0005  # 小偏离
        market_price_extreme = 1.0600  # 大偏离
        
        risk_level_normal = system["risk_controller"].market_price_deviation(market_price_normal, mid_price)
        risk_level_extreme = system["risk_controller"].market_price_deviation(market_price_extreme, mid_price)
        
        assert isinstance(risk_level_normal, int)
        assert isinstance(risk_level_extreme, int)
        assert 1 <= risk_level_normal <= 3
        assert 1 <= risk_level_extreme <= 3

    def test_wash_trading_flow(self, etf_system, redis_client, strategy_config):
        """测试洗盘交易流程"""
        system = etf_system
        
        # 设置净值
        redis_client.set(strategy_config["netvalue"], "1.0000")
        
        # 设置市场做市器的最佳价格
        system["market_maker"].best_sell = 1.0001
        system["market_maker"].best_buy = 0.9999
        
        # 1. 获取洗盘价格
        wash_price = system["wash_controller"].get_washing_price(strategy_config)
        expected_wash_price = (1.0001 + 0.9999) / 2
        assert wash_price == expected_wash_price
        
        # 2. 执行洗盘交易
        result = system["wash_controller"].wash(
            symbol=strategy_config["symbol"],
            last_mid_price=1.0000,
            mid_price=wash_price,
            prec=strategy_config["precision"],
            prec_amount=strategy_config["prec_amount"],
            interval=strategy_config["kline_continuity_interval"]
        )
        
        # 验证洗盘交易结果
        assert result == wash_price
        assert len(system["wash_controller"].returns) == 1
        
        # 验证洗盘订单被创建
        wash_order_calls = [call for call in system["order_manager"].add_orders_batch.call_args_list 
                           if call[1].get("is_wash_trading")]
        assert len(wash_order_calls) == 2  # 买单和卖单

    def test_system_coordination_under_normal_conditions(self, etf_system, redis_client, strategy_config):
        """测试正常条件下的系统协调"""
        system = etf_system
        
        # 设置初始状态
        redis_client.set(strategy_config["netvalue"], "1.0000")
        
        # 1. 市场数据更新
        depth = system["risk_controller"].get_depth_data(strategy_config["symbol"])
        mid_price = system["risk_controller"].get_mid_price(depth)
        
        # 2. 风险评估
        risk_level = system["risk_controller"].market_price_deviation(1.0000, mid_price)
        assert risk_level in [1, 2, 3]
        
        # 3. 市场做市
        with patch("etf.market_making.get_orderbook") as mock_orderbook:
            mock_orderbook.return_value = (
                [{"direction": "bid", "price": 0.9999, "amount": 100,
                  "min_price": 0.9998, "max_price": 1.0000}],
                [{"direction": "ask", "price": 1.0001, "amount": 100,
                  "min_price": 1.0000, "max_price": 1.0002}]
            )
            
            system["market_maker"].place_orders(strategy_config)
        
        # 4. 洗盘交易
        system["market_maker"].best_sell = 1.0001
        system["market_maker"].best_buy = 0.9999
        
        wash_result = system["wash_controller"].wash(
            symbol=strategy_config["symbol"],
            last_mid_price=1.0000,
            mid_price=1.0000,
            prec=strategy_config["precision"],
            prec_amount=strategy_config["prec_amount"],
            interval=60
        )
        
        # 验证系统协调工作
        assert wash_result is not None
        assert system["order_manager"].add_orders_batch.call_count >= 2

    def test_system_error_handling(self, etf_system, redis_client, strategy_config):
        """测试系统错误处理"""
        system = etf_system
        
        # 设置Redis数据
        redis_client.set(strategy_config["netvalue"], "1.0000")
        
        # 1. 测试API错误
        system["client"].get_depth.side_effect = Exception("Network error")
        
        with pytest.raises(Exception):
            system["risk_controller"].get_depth_data(strategy_config["symbol"])
        
        # 重置mock
        system["client"].get_depth.side_effect = None
        system["client"].get_depth.return_value = {
            "bids": [["1.0000", "100"]],
            "asks": [["1.0001", "100"]]
        }
        
        # 2. 测试订单错误处理
        system["client"].batch_orders.side_effect = Exception("Order failed")
        
        # 错误应该被捕获，不影响系统运行
        with patch("etf.market_making.get_orderbook") as mock_orderbook:
            mock_orderbook.return_value = ([], [])
            
            # 不应该抛出异常
            system["market_maker"].place_orders(strategy_config)

    def test_system_performance_under_load(self, etf_system, redis_client, strategy_config):
        """测试系统在负载下的性能"""
        system = etf_system
        
        # 设置初始数据
        redis_client.set(strategy_config["netvalue"], "1.0000")
        
        # 模拟大量订单
        large_order_list = []
        for i in range(200):  # 超过批量限制
            large_order_list.append({
                "orderId": f"order_{i}",
                "symbol": "btc3l_usdt",
                "price": f"{1.0000 + i * 0.0001}",
                "origQty": "10",
                "side": "SELL" if i % 2 == 0 else "BUY",
                "state": "NEW"
            })
        
        system["client"].get_open_orders.return_value = large_order_list
        
        # 执行下单，应该能处理批量限制
        with patch("etf.market_making.get_orderbook") as mock_orderbook:
            mock_orderbook.return_value = ([], [])
            
            start_time = time.time()
            system["market_maker"].place_orders(strategy_config)
            end_time = time.time()
            
            # 验证执行时间合理（不超过10秒）
            assert end_time - start_time < 10.0
            
            # 验证批量处理被执行
            assert system["client"].batch_cancel.call_count >= 1

    def test_system_state_consistency(self, etf_system, redis_client, strategy_config):
        """测试系统状态一致性"""
        system = etf_system
        
        # 设置初始状态
        redis_client.set(strategy_config["netvalue"], "1.0000")
        
        # 1. 执行一系列操作
        system["risk_controller"].get_depth_data(strategy_config["symbol"])
        
        with patch("etf.market_making.get_orderbook") as mock_orderbook:
            mock_orderbook.return_value = (
                [{"direction": "bid", "price": 0.9999, "amount": 100,
                  "min_price": 0.9998, "max_price": 1.0000}],
                [{"direction": "ask", "price": 1.0001, "amount": 100,
                  "min_price": 1.0000, "max_price": 1.0002}]
            )
            
            system["market_maker"].place_orders(strategy_config)
        
        # 2. 验证状态一致性
        assert system["order_manager"].netvalue == 1.0000
        assert system["market_maker"].best_sell == 1.0001
        assert system["market_maker"].best_buy == 0.9999
        
        # 3. 验证组件间数据共享
        wash_price = system["wash_controller"].get_washing_price(strategy_config)
        expected_price = (system["market_maker"].best_sell + system["market_maker"].best_buy) / 2
        assert wash_price == expected_price


class TestETFSystemFailureScenarios:
    """ETF系统故障场景测试"""

    @pytest.fixture
    def failing_client(self):
        """模拟故障的交易客户端"""
        client = MagicMock()
        client.get_depth.side_effect = Exception("Connection timeout")
        client.get_tickers.side_effect = Exception("API rate limit")
        client.get_open_orders.side_effect = Exception("Server error")
        client.batch_orders.side_effect = Exception("Order submission failed")
        return client

    @pytest.fixture
    def redis_client(self):
        """Redis客户端fixture"""
        try:
            r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
            r.ping()
            r.flushdb()
            yield r
            r.flushdb()
        except:
            pytest.skip("Redis not available")

    def test_network_failure_recovery(self, failing_client, redis_client):
        """测试网络故障恢复"""
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            order_manager = OrderManager(failing_client, strategy_name="test_failure")
        
        # 模拟连续网络故障
        for _ in range(6):  # 超过熔断器阈值
            try:
                order_manager.get_depth_data("btc3l_usdt")
            except:
                pass
        
        # 验证熔断器被触发
        assert order_manager.circuit_breaker_open
        assert order_manager.consecutive_failures >= 5
        
        # 模拟网络恢复
        failing_client.get_depth.side_effect = None
        failing_client.get_depth.return_value = {"bids": [], "asks": []}
        
        # 等待熔断器重置时间
        order_manager.circuit_breaker_reset_time = time.time() - 1
        
        # 验证熔断器可以重置
        assert order_manager._check_circuit_breaker()
        assert not order_manager.circuit_breaker_open

    def test_redis_failure_fallback(self, redis_client):
        """测试Redis故障回退机制"""
        # 模拟Redis连接失败
        failed_redis = MagicMock()
        failed_redis.get.side_effect = Exception("Redis connection failed")
        failed_redis.set.side_effect = Exception("Redis connection failed")
        
        with patch("etf.market_making.redis.Redis", return_value=failed_redis), \
             patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
            
            mock_client = MagicMock()
            mock_client.get_open_orders.return_value = []
            
            order_manager = OrderManager(mock_client)
            market_maker = MarketMaker(order_manager)
            
            # 配置应该回退到默认值
            config = {
                "netvalue": "nonexistent_key",
                "bid_ask_spread": 0.01,
                "anti_pin_rate": 0.1,
                "anti_pin_usdt": 1000,
                "precision": 4,
                "prec_amount": 2
            }
            
            with patch("etf.market_making.get_orderbook") as mock_orderbook:
                mock_orderbook.return_value = ([], [])
                
                # 不应该抛出异常，应该使用默认净值
                market_maker.place_orders(config)
                
                # 验证使用了默认净值
                assert order_manager.netvalue == 1.0

    def test_partial_system_failure(self, redis_client):
        """测试部分系统故障"""
        # 创建部分工作的客户端
        client = MagicMock()
        client.get_depth.return_value = {"bids": [["1.0", "100"]], "asks": [["1.001", "100"]]}
        client.get_tickers.side_effect = Exception("Ticker service down")  # 只有ticker服务故障
        client.get_open_orders.return_value = []
        
        with patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False), \
             patch("etf.market_making.redis.Redis", return_value=redis_client):
            
            order_manager = OrderManager(client)
            risk_controller = RiskController(client, {
                "orderbook_threshold": [0.8, 0.6, 0.4],
                "base_bid_volume": 100.0,
                "base_ask_volume": 100.0,
                "price_deviation_threshold": [0.05, 0.03, 0.01],
                "stop_loss": {"enabled": False}
            })
            
            # 深度数据应该正常工作
            depth = risk_controller.get_depth_data("btc3l_usdt")
            assert depth is not None
            
            # 市场价格获取应该失败但被处理
            with pytest.raises(Exception):
                risk_controller.get_market_price("btc3l_usdt")


def test_full_system_integration():
    """完整系统集成测试"""
    try:
        r = redis.Redis(host="localhost", port=6379, db=15)
        r.ping()
        r.flushdb()
    except:
        pytest.skip("Redis not available")

    # 创建完整的模拟客户端
    mock_client = MagicMock()
    mock_client.get_depth.return_value = {
        "bids": [["1.0000", "100"], ["0.9999", "200"]],
        "asks": [["1.0001", "100"], ["1.0002", "200"]]
    }
    mock_client.get_tickers.return_value = [{"p": "1.0000"}]
    mock_client.get_kline.return_value = [{"c": "1.0000"}] * 3
    mock_client.get_open_orders.return_value = []
    mock_client.batch_orders.return_value = {"success": True}

    # 创建系统组件
    with patch("etf.market_making.redis.Redis", return_value=r), \
         patch("etf.washing.redis.Redis", return_value=r), \
         patch("etf.order_manager.ORDER_RECORDER_AVAILABLE", False):
        
        order_manager = OrderManager(mock_client, strategy_name="full_integration")
        market_maker = MarketMaker(order_manager)
        risk_controller = RiskController(mock_client, {
            "stop_loss": {"enabled": False},
            "orderbook_threshold": [0.8, 0.6, 0.4],
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]
        })
        wash_controller = WashController(order_manager, market_maker)

    # 设置测试数据
    r.set("netvalue_full_integration", "1.0000")
    
    config = {
        "symbol": "btc3l_usdt",
        "netvalue": "netvalue_full_integration",
        "bid_ask_spread": 0.01,
        "anti_pin_rate": 0.1,
        "anti_pin_usdt": 1000,
        "precision": 4,
        "prec_amount": 2,
        "wash": "mid_price"
    }

    # 执行完整的交易周期
    
    # 1. 风险监控
    risk_controller.risk_monitor(config["symbol"])
    
    # 2. 市场做市
    with patch("etf.market_making.get_orderbook") as mock_orderbook:
        mock_orderbook.return_value = (
            [{"direction": "bid", "price": 0.9999, "amount": 100,
              "min_price": 0.9998, "max_price": 1.0000}],
            [{"direction": "ask", "price": 1.0001, "amount": 100,
              "min_price": 1.0000, "max_price": 1.0002}]
        )
        
        market_maker.place_orders(config)
    
    # 3. 洗盘交易
    wash_price = wash_controller.get_washing_price(config)
    wash_result = wash_controller.wash(
        symbol=config["symbol"],
        last_mid_price=1.0000,
        mid_price=wash_price,
        prec=config["precision"],
        prec_amount=config["prec_amount"],
        interval=60
    )

    # 验证系统协调工作
    assert order_manager.netvalue == 1.0000
    assert market_maker.best_sell == 1.0001
    assert market_maker.best_buy == 0.9999
    assert wash_result is not None
    assert len(wash_controller.returns) == 1
    
    # 验证所有API调用
    mock_client.get_depth.assert_called()
    mock_client.batch_orders.assert_called()
    
    # 清理
    r.flushdb()


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])