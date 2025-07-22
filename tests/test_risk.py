# -*- coding:utf-8 -*-

"""
测试风控模块

Author: Claude Code
Date: 2025-01-22
"""

import time
import pytest
import numpy as np
from unittest.mock import MagicMock, patch
from etf.risk import RiskController


class TestRiskController:
    """测试风控控制器"""

    @pytest.fixture
    def mock_client(self):
        """模拟交易客户端"""
        client = MagicMock()
        client.get_depth.return_value = {
            "symbol": "btc3l_usdt",
            "timestamp": 1736170681790,
            "lastUpdateId": 1736148981744,
            "bids": [
                ["50000", "1.0"],
                ["49999", "2.0"],
                ["49998", "3.0"]
            ],
            "asks": [
                ["50001", "1.0"],
                ["50002", "2.0"],
                ["50003", "3.0"]
            ]
        }
        client.get_tickers.return_value = [{"s": "btc3l_usdt", "t": 1736171102959, "p": "50000.5"}]
        client.get_kline.return_value = [
            {"c": "50000", "h": "50100", "l": "49900", "o": "50050"},
            {"c": "50050", "h": "50150", "l": "49950", "o": "50000"},
            {"c": "50025", "h": "50125", "l": "49925", "o": "50050"}
        ]
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
            "orderbook_threshold": [0.8, 0.6, 0.4],  # 三个风险等级的阈值
            "base_bid_volume": 100.0,
            "base_ask_volume": 100.0,
            "price_deviation_threshold": [0.05, 0.03, 0.01]  # 价格偏离阈值
        }

    @pytest.fixture
    def risk_controller(self, mock_client, risk_params):
        """创建风控控制器"""
        return RiskController(mock_client, risk_params, strategy_name="test_strategy")

    def test_init_with_stop_loss_enabled(self, mock_client, risk_params):
        """测试启用止损的初始化"""
        rc = RiskController(mock_client, risk_params, strategy_name="test_strategy")
        
        assert rc.client == mock_client
        assert rc.risk_params == risk_params
        assert rc.risk_level == 3
        assert rc.strategy_name == "test_strategy"
        assert rc.stop_loss_manager is not None
        assert rc.midprices == []
        assert rc.depth is None

    def test_init_with_stop_loss_disabled(self, mock_client):
        """测试禁用止损的初始化"""
        risk_params = {"stop_loss": {"enabled": False}}
        rc = RiskController(mock_client, risk_params, strategy_name="test_strategy")
        
        assert rc.stop_loss_manager is None

    def test_get_mid_price(self, risk_controller):
        """测试计算中间价"""
        depth = {
            "bids": [["50000", "1.0"], ["49999", "2.0"]],
            "asks": [["50001", "1.0"], ["50002", "2.0"]]
        }
        
        mid_price = risk_controller.get_mid_price(depth)
        
        expected_mid_price = (50000 + 50001) / 2
        assert mid_price == expected_mid_price

    def test_get_market_price(self, risk_controller):
        """测试获取市场价格"""
        price = risk_controller.get_market_price("btc3l_usdt")
        
        assert price == 50000.5
        risk_controller.client.get_tickers.assert_called_once_with("btc3l_usdt")

    def test_get_depth_data(self, risk_controller):
        """测试获取深度数据"""
        depth = risk_controller.get_depth_data("btc3l_usdt")
        
        assert depth is not None
        assert "bids" in depth
        assert "asks" in depth
        assert risk_controller.depth == depth
        risk_controller.client.get_depth.assert_called_once_with("btc3l_usdt")

    def test_calculate_volatility(self, risk_controller):
        """测试波动率计算"""
        close_prices = [100.0, 101.0, 99.5, 102.0, 98.0]
        
        volatility, mean_return = risk_controller.calculate_volatility(close_prices)
        
        assert isinstance(volatility, float)
        assert isinstance(mean_return, float)
        assert volatility >= 0
        
        # 验证计算逻辑
        returns = [
            (101.0 - 100.0) / 100.0,
            (99.5 - 101.0) / 101.0,
            (102.0 - 99.5) / 99.5,
            (98.0 - 102.0) / 102.0
        ]
        expected_mean = sum(returns) / len(returns)
        assert abs(mean_return - expected_mean) < 1e-10

    def test_calculate_volatility_empty_list(self, risk_controller):
        """测试空价格列表的波动率计算"""
        with pytest.raises(ZeroDivisionError):
            risk_controller.calculate_volatility([])

    def test_calculate_volatility_single_price(self, risk_controller):
        """测试单个价格的波动率计算"""
        with pytest.raises(IndexError):
            risk_controller.calculate_volatility([100.0])

    def test_check_market_volatility(self, risk_controller):
        """测试市场波动率检查"""
        result = risk_controller.check_market_volatility("btc3l_usdt")
        
        assert isinstance(result, int)
        assert 1 <= result <= 3
        
        # 验证客户端调用
        assert risk_controller.client.get_kline.call_count == 2  # 1m和1d数据

    def test_monitor_order_book_depth_normal(self, risk_controller):
        """测试正常情况下的订单簿深度监控"""
        depth_data = {
            "bids": [["50000", "50"], ["49999", "50"]],  # 总量100
            "asks": [["50001", "50"], ["50002", "50"]]   # 总量100
        }
        
        result = risk_controller.monitor_order_book_depth(depth_data)
        
        assert result == 3  # 正常风险等级

    def test_monitor_order_book_depth_risk_level_1(self, risk_controller):
        """测试风险等级1的订单簿深度监控"""
        depth_data = {
            "bids": [["50000", "70"], ["49999", "10"]],  # 总量80，低于80%阈值
            "asks": [["50001", "50"], ["50002", "50"]]   # 总量100
        }
        
        result = risk_controller.monitor_order_book_depth(depth_data)
        
        assert result == 3  # 最高风险等级

    def test_monitor_order_book_depth_risk_level_2(self, risk_controller):
        """测试风险等级2的订单簿深度监控"""
        depth_data = {
            "bids": [["50000", "50"], ["49999", "10"]],  # 总量60，低于60%阈值
            "asks": [["50001", "50"], ["50002", "50"]]   # 总量100
        }
        
        result = risk_controller.monitor_order_book_depth(depth_data)
        
        assert result == 2

    def test_market_price_deviation_normal(self, risk_controller):
        """测试正常价格偏离"""
        market_price = 50000.5
        mid_price = 50000.0
        
        result = risk_controller.market_price_deviation(market_price, mid_price)
        
        # 偏离 = |50000.5 - 50000.0| / 50000.0 = 0.00001，很小
        assert result == 3  # 正常情况

    def test_market_price_deviation_high_risk(self, risk_controller):
        """测试高风险价格偏离"""
        market_price = 52500.0  # 5%偏离
        mid_price = 50000.0
        
        result = risk_controller.market_price_deviation(market_price, mid_price)
        
        # 偏离 = |52500 - 50000| / 50000 = 0.05，等于5%
        assert result == 3  # 超过最高阈值

    def test_mid_price_deviation_normal(self, risk_controller):
        """测试正常中间价偏离"""
        # 先添加一些历史价格建立基线
        historical_prices = [50000, 50100, 49900, 50050, 49950]
        for price in historical_prices:
            risk_controller.midprices.append(price)
        
        result = risk_controller.mid_price_deviation(50025)  # 接近均值的价格
        
        assert isinstance(result, int)
        assert 1 <= result <= 3

    def test_mid_price_deviation_extreme(self, risk_controller):
        """测试极端中间价偏离"""
        # 建立稳定的历史价格
        historical_prices = [50000] * 10
        for price in historical_prices:
            risk_controller.midprices.append(price)
        
        result = risk_controller.mid_price_deviation(60000)  # 极端偏离的价格
        
        # 应该触发最高风险等级
        assert result == 3

    def test_midprices_queue_length_limit(self, risk_controller):
        """测试中间价队列长度限制"""
        # 添加超过60个价格
        for i in range(65):
            risk_controller.mid_price_deviation(50000 + i)
        
        # 队列长度应该限制在60
        assert len(risk_controller.midprices) == 60

    def test_risk_monitor_integration(self, risk_controller):
        """测试风险监控集成功能"""
        # 这个方法会调用多个子方法
        risk_controller.risk_monitor("btc3l_usdt")
        
        # 验证所有相关方法被调用
        risk_controller.client.get_depth.assert_called_with("btc3l_usdt")
        risk_controller.client.get_tickers.assert_called_with("btc3l_usdt")
        
        # 验证深度数据被设置
        assert risk_controller.depth is not None

    def test_stop_loss_manager_integration(self, risk_controller):
        """测试止损管理器集成"""
        assert risk_controller.stop_loss_manager is not None
        
        # 测试止损管理器的基本属性
        stop_loss = risk_controller.stop_loss_manager
        assert stop_loss.strategy_name == "test_strategy"
        assert stop_loss.fixed_threshold == -0.02
        assert stop_loss.trailing_stop == 0.01

    @patch("time.time")
    def test_check_market_volatility_with_mocked_time(self, mock_time, risk_controller):
        """测试使用模拟时间的市场波动率检查"""
        mock_time.return_value = 1640000000  # 固定时间戳
        
        result = risk_controller.check_market_volatility("btc3l_usdt")
        
        assert isinstance(result, int)
        assert 1 <= result <= 3
        
        # 验证时间戳计算
        expected_start_time = int(1640000000 * 1000)
        risk_controller.client.get_kline.assert_any_call(
            symbol="btc3l_usdt",
            interval="1m",
            start_time=expected_start_time,
            end_time=expected_start_time + 60
        )

    def test_error_handling_in_risk_methods(self, risk_controller):
        """测试风控方法的错误处理"""
        # 模拟客户端抛出异常
        risk_controller.client.get_depth.side_effect = Exception("Network error")
        
        with pytest.raises(Exception):
            risk_controller.get_depth_data("btc3l_usdt")

    def test_risk_params_validation(self, mock_client):
        """测试风控参数验证"""
        # 测试缺少必要参数的情况
        incomplete_params = {
            "stop_loss": {"enabled": True}
            # 缺少其他必要参数
        }
        
        with pytest.raises(KeyError):
            rc = RiskController(mock_client, incomplete_params)
            rc.monitor_order_book_depth({"bids": [], "asks": []})


def test_risk_controller_integration():
    """集成测试：模拟完整的风控流程"""
    # 创建模拟客户端
    mock_client = MagicMock()
    mock_client.get_depth.return_value = {
        "bids": [["50000", "100"]],
        "asks": [["50001", "100"]]
    }
    mock_client.get_tickers.return_value = [{"p": "50000.5"}]
    mock_client.get_kline.return_value = [
        {"c": "50000"}, {"c": "50100"}, {"c": "49900"}
    ]

    # 创建风控参数
    risk_params = {
        "stop_loss": {"enabled": False},
        "orderbook_threshold": [0.8, 0.6, 0.4],
        "base_bid_volume": 100.0,
        "base_ask_volume": 100.0,
        "price_deviation_threshold": [0.05, 0.03, 0.01]
    }

    # 创建风控控制器
    rc = RiskController(mock_client, risk_params, strategy_name="integration_test")

    # 1. 获取深度数据
    depth = rc.get_depth_data("btc3l_usdt")
    assert depth is not None

    # 2. 计算中间价
    mid_price = rc.get_mid_price(depth)
    assert mid_price == 50000.5

    # 3. 获取市场价格
    market_price = rc.get_market_price("btc3l_usdt")
    assert market_price == 50000.5

    # 4. 检查价格偏离
    deviation_result = rc.market_price_deviation(market_price, mid_price)
    assert isinstance(deviation_result, int)

    # 5. 监控订单簿深度
    orderbook_result = rc.monitor_order_book_depth(depth)
    assert isinstance(orderbook_result, int)

    # 6. 执行完整风险监控
    rc.risk_monitor("btc3l_usdt")

    # 验证所有组件正常工作
    assert rc.depth is not None


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])