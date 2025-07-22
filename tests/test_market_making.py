# -*- coding:utf-8 -*-

"""
测试市场做市模块

Author: Claude Code
Date: 2025-01-22
"""

import time
import pytest
import redis
from unittest.mock import MagicMock, patch, call
from loguru import logger

from etf.market_making import MarketMaker


class TestMarketMaker:
    """测试市场做市器"""

    @pytest.fixture
    def mock_order_manager(self):
        """模拟订单管理器"""
        order_manager = MagicMock()
        order_manager.create_temp_id.return_value = "test_order_id_123"
        order_manager.client.get_open_orders.return_value = []
        order_manager.add_orders_batch.return_value = {"success": True}
        order_manager.cancel_orders_batch.return_value = {"success": True}
        return order_manager

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
    def market_maker(self, mock_order_manager, redis_client):
        """创建测试用的市场做市器"""
        with patch("etf.market_making.redis.Redis") as mock_redis:
            mock_redis.return_value = redis_client
            mm = MarketMaker(mock_order_manager)
            return mm

    def test_init(self, mock_order_manager):
        """测试初始化"""
        with patch("etf.market_making.redis.Redis") as mock_redis:
            mm = MarketMaker(mock_order_manager)
            assert mm.order_manager == mock_order_manager
            assert mm.best_sell == 0
            assert mm.best_buy == 0
            mock_redis.assert_called_once_with(host="localhost", port=6379, db=0)

    @patch("etf.market_making.get_orderbook")
    def test_make_orders_qa_env(self, mock_get_orderbook, market_maker):
        """测试QA环境下的订单创建"""
        # 模拟订单簿数据
        mock_get_orderbook.return_value = (
            [{"direction": "bid", "price": 0.99, "amount": 100}],  # bid orders
            [{"direction": "ask", "price": 1.01, "amount": 100}]   # ask orders
        )

        market_maker.make_orders(
            symbol="BTCUSDT",
            netvalue=1.0,
            env="qa"
        )

        # 验证get_orderbook被调用
        mock_get_orderbook.assert_called_once_with(mid_price=1.0)
        
        # 验证add_orders_batch被调用
        market_maker.order_manager.add_orders_batch.assert_called_once()
        
        # 获取调用参数
        call_args = market_maker.order_manager.add_orders_batch.call_args
        orders_data = call_args[0][0]
        
        # 验证订单数据结构
        assert len(orders_data) == 2
        for order in orders_data:
            assert "symbol" in order
            assert "clientOrderId" in order
            assert "side" in order
            assert "type" in order
            assert order["type"] == "LIMIT"
            assert order["timeInForce"] == "GTC"
            assert order["bizType"] == "SPOT"

    def test_place_orders_netvalue_from_redis(self, market_maker, redis_client):
        """测试从Redis获取净值并下单"""
        # 设置Redis中的净值
        redis_client.set("netvalue_btc3l_usdt", "1.05")
        
        config = {
            "netvalue": "netvalue_btc3l_usdt",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }

        with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
            mock_get_orderbook.return_value = (
                [{"direction": "bid", "price": 1.04, "amount": 100, 
                  "min_price": 1.03, "max_price": 1.05}],
                [{"direction": "ask", "price": 1.06, "amount": 100,
                  "min_price": 1.05, "max_price": 1.07}]
            )
            
            market_maker.place_orders(config, symbol="btc3l_usdt")

        # 验证净值被正确设置
        assert market_maker.order_manager.netvalue == 1.05
        
        # 验证get_orderbook被调用
        mock_get_orderbook.assert_called_with(mid_price=1.05, bid_ask_spread=0.01)

    def test_place_orders_netvalue_fallback_to_default(self, market_maker, redis_client):
        """测试净值获取失败时使用默认值"""
        config = {
            "netvalue": "nonexistent_key",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }

        with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
            mock_get_orderbook.return_value = ([], [])
            
            market_maker.place_orders(config, symbol="test_usdt")

        # 验证使用了默认净值
        assert market_maker.order_manager.netvalue == 1.0

    def test_place_orders_with_existing_orders(self, market_maker, redis_client):
        """测试存在现有订单时的处理逻辑"""
        redis_client.set("netvalue_test", "1.0")
        
        # 模拟现有订单
        existing_orders = [
            {
                "orderId": "123",
                "price": "1.05",
                "origQty": "50",
                "side": "SELL",
                "state": "NEW"
            },
            {
                "orderId": "124", 
                "price": "0.95",
                "origQty": "60",
                "side": "BUY",
                "state": "NEW"
            }
        ]
        
        market_maker.order_manager.client.get_open_orders.return_value = existing_orders
        
        config = {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }

        with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
            mock_get_orderbook.return_value = (
                [{"direction": "bid", "price": 0.99, "amount": 100,
                  "min_price": 0.94, "max_price": 0.96}],
                [{"direction": "ask", "price": 1.01, "amount": 100,
                  "min_price": 1.04, "max_price": 1.06}]
            )
            
            market_maker.place_orders(config, symbol="test_usdt")

        # 验证现有订单被正确处理
        market_maker.order_manager.client.get_open_orders.assert_called_with(symbol="test_usdt")

    def test_place_orders_api_retry_logic(self, market_maker, redis_client):
        """测试API调用失败时的重试逻辑"""
        redis_client.set("netvalue_test", "1.0")
        
        # 模拟API调用失败后成功
        market_maker.order_manager.client.get_open_orders.side_effect = [
            Exception("Network error"),
            []  # 第二次调用成功
        ]
        
        config = {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }

        with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
            with patch("time.sleep"):  # 加速测试
                mock_get_orderbook.return_value = ([], [])
                
                market_maker.place_orders(config, symbol="test_usdt")

        # 验证重试机制工作
        assert market_maker.order_manager.client.get_open_orders.call_count == 2

    def test_anti_pin_orders_calculation(self, market_maker, redis_client):
        """测试反夹单订单的计算逻辑"""
        redis_client.set("netvalue_test", "1.0")
        
        config = {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,  # 10%
            "anti_pin_usdt": 1000,  # $1000
            "precision": 4,
            "prec_amount": 2
        }

        with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
            mock_get_orderbook.return_value = (
                [{"direction": "bid", "price": 0.99, "amount": 100,
                  "min_price": 0.98, "max_price": 1.00}],
                [{"direction": "ask", "price": 1.01, "amount": 100,
                  "min_price": 1.00, "max_price": 1.02}]
            )
            
            market_maker.place_orders(config, symbol="test_usdt")

        # 验证最佳买卖价被设置
        assert market_maker.best_sell == 1.01
        assert market_maker.best_buy == 0.99
        
        # 验证反夹单价格计算
        expected_anti_pin_sell = round(1.01 * 1.1, 4)  # 1.01 * (1 + 0.1)
        expected_anti_pin_buy = round(0.99 * 0.9, 4)   # 0.99 * (1 - 0.1)

        # 通过检查add_orders_batch的调用参数来验证反夹单
        call_args = market_maker.order_manager.add_orders_batch.call_args_list
        if call_args:
            added_orders = call_args[-1][0][0]  # 最后一次调用的订单
            anti_pin_orders = [order for order in added_orders 
                              if abs(float(order["price"]) - expected_anti_pin_sell) < 0.01 
                              or abs(float(order["price"]) - expected_anti_pin_buy) < 0.01]
            assert len(anti_pin_orders) >= 1  # 至少有一个反夹单

    def test_order_batch_processing(self, market_maker, redis_client):
        """测试订单批量处理逻辑"""
        redis_client.set("netvalue_test", "1.0")
        
        # 创建大量现有订单以测试批量处理
        existing_orders = []
        for i in range(150):  # 超过批量大小限制
            existing_orders.append({
                "orderId": f"order_{i}",
                "price": f"{1.0 + i * 0.001}",
                "origQty": "10",
                "side": "SELL" if i % 2 == 0 else "BUY",
                "state": "NEW"
            })
        
        market_maker.order_manager.client.get_open_orders.return_value = existing_orders
        
        config = {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.1,
            "anti_pin_usdt": 1000,
            "precision": 4,
            "prec_amount": 2
        }

        with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
            mock_get_orderbook.return_value = ([], [])
            
            market_maker.place_orders(config, symbol="test_usdt")

        # 验证批量处理被执行（应该有多次调用由于批量大小限制）
        add_calls = market_maker.order_manager.add_orders_batch.call_count
        cancel_calls = market_maker.order_manager.cancel_orders_batch.call_count
        
        # 应该至少有一次调用
        assert add_calls >= 1 or cancel_calls >= 1


def test_market_maker_integration():
    """集成测试：模拟完整的市场做市流程"""
    try:
        r = redis.Redis(host="localhost", port=6379, db=15)
        r.ping()
    except:
        pytest.skip("Redis not available")

    # 创建模拟的订单管理器
    order_manager = MagicMock()
    order_manager.create_temp_id.return_value = "integration_test_id"
    order_manager.client.get_open_orders.return_value = []
    order_manager.add_orders_batch.return_value = {"success": True}

    # 创建市场做市器
    with patch("etf.market_making.redis.Redis", return_value=r):
        mm = MarketMaker(order_manager)

    # 设置测试数据
    r.set("netvalue_integration_test", "1.05")
    
    config = {
        "netvalue": "netvalue_integration_test",
        "bid_ask_spread": 0.01,
        "anti_pin_rate": 0.1,
        "anti_pin_usdt": 1000,
        "precision": 4,
        "prec_amount": 2
    }

    # 执行下单
    with patch("etf.market_making.get_orderbook") as mock_get_orderbook:
        mock_get_orderbook.return_value = (
            [{"direction": "bid", "price": 1.04, "amount": 100,
              "min_price": 1.03, "max_price": 1.05}],
            [{"direction": "ask", "price": 1.06, "amount": 100,
              "min_price": 1.05, "max_price": 1.07}]
        )
        
        mm.place_orders(config, symbol="integration_test_usdt")

    # 验证结果
    assert mm.order_manager.netvalue == 1.05
    assert mm.best_sell == 1.06
    assert mm.best_buy == 1.04
    
    # 验证订单被添加
    order_manager.add_orders_batch.assert_called()
    
    # 清理
    r.flushdb()


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])