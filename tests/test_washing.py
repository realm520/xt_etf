# -*- coding:utf-8 -*-

"""
测试洗盘交易模块

Author: Claude Code
Date: 2025-01-22
"""

import time
import random
import pytest
import redis
from unittest.mock import MagicMock, patch, call
from etf.washing import WashController


class TestWashController:
    """测试洗盘控制器"""

    @pytest.fixture
    def mock_order_manager(self):
        """模拟订单管理器"""
        order_manager = MagicMock()
        order_manager.add_orders_batch.return_value = {"success": True}
        return order_manager

    @pytest.fixture
    def mock_market_maker(self):
        """模拟市场做市器"""
        market_maker = MagicMock()
        market_maker.best_sell = 1.01
        market_maker.best_buy = 0.99
        return market_maker

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
    def wash_controller(self, mock_order_manager, mock_market_maker, redis_client):
        """创建洗盘控制器"""
        with patch("etf.washing.redis.Redis") as mock_redis:
            mock_redis.return_value = redis_client
            wc = WashController(mock_order_manager, mock_market_maker)
            return wc

    def test_init(self, mock_order_manager, mock_market_maker):
        """测试初始化"""
        with patch("etf.washing.redis.Redis") as mock_redis:
            wc = WashController(mock_order_manager, mock_market_maker)
            
            assert wc.order_manager == mock_order_manager
            assert wc.market_maker == mock_market_maker
            assert wc.returns == []
            assert wc.max_trade_amount == 50
            assert wc.total_spent == 0
            mock_redis.assert_called_once_with(host="localhost", port=6379, db=0)

    def test_wash_normal_operation(self, wash_controller):
        """测试正常洗盘操作"""
        symbol = "BTCUSDT"
        last_mid_price = 50000.0
        mid_price = 50010.0  # 小幅上涨
        
        result = wash_controller.wash(
            symbol=symbol,
            last_mid_price=last_mid_price,
            mid_price=mid_price,
            prec=4,
            prec_amount=2,
            interval=60
        )
        
        # 验证返回值
        assert result == mid_price
        
        # 验证收益率被记录
        assert len(wash_controller.returns) == 1
        expected_return = (mid_price - last_mid_price) / last_mid_price
        assert abs(wash_controller.returns[0] - expected_return) < 1e-10
        
        # 验证订单被创建
        assert wash_controller.order_manager.add_orders_batch.call_count == 2

    def test_wash_high_volatility_skip(self, wash_controller):
        """测试高波动率时跳过交易"""
        # 先添加一个高波动率收益
        wash_controller.returns = [0.02]  # 2% > 1% 阈值
        
        symbol = "BTCUSDT"
        last_mid_price = 50000.0
        mid_price = 50010.0
        
        with patch("builtins.print") as mock_print:
            result = wash_controller.wash(
                symbol=symbol,
                last_mid_price=last_mid_price,
                mid_price=mid_price,
                prec=4,
                prec_amount=2,
                interval=60
            )
        
        # 验证交易被跳过
        assert result == mid_price
        wash_controller.order_manager.add_orders_batch.assert_not_called()

    def test_wash_minimum_amount_adjustment(self, wash_controller):
        """测试最小交易金额调整"""
        symbol = "BTCUSDT"
        last_mid_price = 0.01  # 非常低的价格
        mid_price = 0.01
        
        result = wash_controller.wash(
            symbol=symbol,
            last_mid_price=last_mid_price,
            mid_price=mid_price,
            prec=8,
            prec_amount=2,
            interval=60
        )
        
        # 验证订单被创建
        assert wash_controller.order_manager.add_orders_batch.call_count == 2
        
        # 获取调用参数并验证最小金额
        call_args = wash_controller.order_manager.add_orders_batch.call_args_list
        for call_arg in call_args:
            order_data = call_arg[0][0][0]  # 第一个订单
            # 验证交易金额 >= 5 USDT
            assert float(order_data["price"]) * float(order_data["quantity"]) >= 5.0

    def test_wash_interval_behavior(self, wash_controller):
        """测试间隔行为和价格调整"""
        symbol = "BTCUSDT"
        last_mid_price = 50000.0
        mid_price = 50100.0
        
        # 添加足够的历史数据以触发间隔行为
        wash_controller.returns = [0.001] * 61  # 超过60个间隔
        
        with patch("random.randint", return_value=1):  # 固定随机数
            result = wash_controller.wash(
                symbol=symbol,
                last_mid_price=last_mid_price,
                mid_price=mid_price,
                prec=4,
                prec_amount=2,
                interval=60
            )
        
        # 验证价格被调整
        assert result != mid_price  # 价格应该被调整
        # 验证收益率列表被重置
        assert len(wash_controller.returns) == 1

    @patch("random.randint")
    @patch("numpy.random.randint")
    def test_wash_order_creation_details(self, mock_np_randint, mock_randint, wash_controller):
        """测试订单创建的详细参数"""
        # 设置固定的随机数
        mock_randint.side_effect = [1, 0]  # 第二个用于rd变量
        mock_np_randint.return_value = 10  # 固定交易数量
        
        symbol = "BTCUSDT"
        last_mid_price = 50000.0
        mid_price = 50010.0
        
        wash_controller.wash(
            symbol=symbol,
            last_mid_price=last_mid_price,
            mid_price=mid_price,
            prec=4,
            prec_amount=2,
            interval=60
        )
        
        # 验证两个订单被创建
        assert wash_controller.order_manager.add_orders_batch.call_count == 2
        
        # 验证订单参数
        call_args = wash_controller.order_manager.add_orders_batch.call_args_list
        
        # 第一个订单 (BUY，因为rd=0)
        buy_order = call_args[0][0][0][0]
        assert buy_order["symbol"] == symbol
        assert buy_order["side"] == "BUY"
        assert buy_order["type"] == "LIMIT"
        assert buy_order["price"] == round(mid_price, 4)
        
        # 第二个订单 (SELL，因为rd=0)
        sell_order = call_args[1][0][0][0]
        assert sell_order["symbol"] == symbol
        assert sell_order["side"] == "SELL"
        assert sell_order["type"] == "LIMIT"
        assert sell_order["price"] == round(mid_price, 4)
        
        # 验证洗盘交易标志
        for call_arg in call_args:
            assert call_arg[1]["is_wash_trading"] is True

    def test_wash_exception_handling(self, wash_controller):
        """测试洗盘过程中的异常处理"""
        # 模拟订单管理器抛出异常
        wash_controller.order_manager.add_orders_batch.side_effect = Exception("Network error")
        
        symbol = "BTCUSDT"
        last_mid_price = 50000.0
        mid_price = 50010.0
        
        # 异常应该被捕获，不影响函数执行
        result = wash_controller.wash(
            symbol=symbol,
            last_mid_price=last_mid_price,
            mid_price=mid_price,
            prec=4,
            prec_amount=2,
            interval=60
        )
        
        assert result == mid_price

    def test_get_washing_price_with_market_maker(self, wash_controller):
        """测试使用市场做市器数据获取洗盘价格"""
        config = {
            "precision": 6,
            "wash": "mid_price"
        }
        
        # 市场做市器有最佳价格
        wash_controller.market_maker.best_sell = 1.01
        wash_controller.market_maker.best_buy = 0.99
        
        price = wash_controller.get_washing_price(config)
        
        expected_price = (1.01 + 0.99) / 2
        assert price == expected_price

    def test_get_washing_price_from_redis(self, wash_controller, redis_client):
        """测试从Redis获取洗盘价格"""
        # 设置市场做市器无数据
        wash_controller.market_maker.best_sell = 0
        
        # 在Redis中设置净值
        redis_client.set("netvalue_test", "1.05")
        
        config = {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.02,
            "precision": 6,
            "wash": "mid_price"
        }
        
        price = wash_controller.get_washing_price(config)
        
        # 验证价格基于Redis数据计算
        assert price == 1.05  # 中间价格

    def test_get_washing_price_fallback_to_default(self, wash_controller, redis_client):
        """测试获取洗盘价格时回退到默认值"""
        # 设置市场做市器无数据
        wash_controller.market_maker.best_sell = 0
        
        config = {
            "netvalue": "nonexistent_key",
            "bid_ask_spread": 0.02,
            "precision": 6,
            "wash": "mid_price"
        }
        
        price = wash_controller.get_washing_price(config)
        
        # 验证使用默认值 1.0
        assert price == 1.0

    def test_get_washing_price_best_sell_method(self, wash_controller):
        """测试使用best_sell方法获取洗盘价格"""
        config = {
            "precision": 6,
            "wash": "best_sell"
        }
        
        wash_controller.market_maker.best_sell = 1.01
        wash_controller.market_maker.best_buy = 0.99
        
        with patch("random.randint", return_value=5):
            price = wash_controller.get_washing_price(config)
        
        # 价格应该略低于best_sell
        expected_price = 1.01 - 1e-6 * 5
        assert abs(price - expected_price) < 1e-10

    @patch("time.sleep")
    @patch("random.randint")
    def test_run_main_loop(self, mock_randint, mock_sleep, wash_controller):
        """测试主运行循环"""
        # 模拟随机数和sleep
        mock_randint.side_effect = [3, 7, 5]  # 初始sleep, 循环sleep, 其他用途
        
        config = {
            "symbol": "BTCUSDT",
            "precision": 4,
            "prec_amount": 2,
            "kline_continuity_interval": 60
        }
        
        risk_controller = MagicMock()
        
        # 只运行一次循环
        wash_controller.market_maker.best_sell = 1.01
        wash_controller.market_maker.best_buy = 0.99
        
        def stop_after_one_iteration(*args):
            # 在第一次wash调用后停止
            raise KeyboardInterrupt("Test stop")
        
        wash_controller.wash = MagicMock(side_effect=stop_after_one_iteration)
        
        with pytest.raises(KeyboardInterrupt):
            wash_controller.run(risk_controller, config)
        
        # 验证初始化sleep被调用
        mock_sleep.assert_any_call(3)
        # 验证wash方法被调用
        wash_controller.wash.assert_called_once()

    def test_price_change_amount_calculation(self, wash_controller):
        """测试基于价格变化的交易数量计算"""
        symbol = "BTCUSDT"
        
        # 测试价格上涨情况
        with patch("numpy.random.randint", return_value=25) as mock_randint:
            wash_controller.wash(
                symbol=symbol,
                last_mid_price=50000.0,
                mid_price=50100.0,  # 上涨
                prec=4,
                prec_amount=2,
                interval=60
            )
            # 价格上涨时应该使用较大的交易量范围
            mock_randint.assert_called_with(1, 50)

        # 重置mock
        mock_randint.reset_mock()
        
        # 测试价格下跌情况
        with patch("numpy.random.randint", return_value=10) as mock_randint:
            wash_controller.wash(
                symbol=symbol,
                last_mid_price=50000.0,
                mid_price=49900.0,  # 下跌
                prec=4,
                prec_amount=2,
                interval=60
            )
            # 价格下跌时应该使用较小的交易量范围
            mock_randint.assert_called_with(1, 16)  # 50 // 3 = 16


def test_wash_controller_integration():
    """集成测试：模拟完整的洗盘交易流程"""
    # 创建模拟组件
    mock_order_manager = MagicMock()
    mock_order_manager.add_orders_batch.return_value = {"success": True}
    
    mock_market_maker = MagicMock()
    mock_market_maker.best_sell = 1.01
    mock_market_maker.best_buy = 0.99
    
    try:
        r = redis.Redis(host="localhost", port=6379, db=15)
        r.ping()
    except:
        pytest.skip("Redis not available")

    # 创建洗盘控制器
    with patch("etf.washing.redis.Redis", return_value=r):
        wc = WashController(mock_order_manager, mock_market_maker)

    # 设置测试数据
    r.set("netvalue_integration_test", "1.0")
    
    config = {
        "symbol": "integration_test_usdt",
        "netvalue": "netvalue_integration_test",
        "bid_ask_spread": 0.02,
        "precision": 4,
        "prec_amount": 2,
        "wash": "mid_price"
    }

    # 1. 获取洗盘价格
    price = wc.get_washing_price(config)
    assert price == 1.01  # 基于market_maker的中间价

    # 2. 执行洗盘交易
    result = wc.wash(
        symbol=config["symbol"],
        last_mid_price=1.0,
        mid_price=price,
        prec=config["precision"],
        prec_amount=config["prec_amount"],
        interval=60
    )

    # 验证结果
    assert result == price
    assert len(wc.returns) == 1
    assert mock_order_manager.add_orders_batch.call_count == 2

    # 清理
    r.flushdb()


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])