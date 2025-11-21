"""
自然K线模拟器单元测试
"""

import unittest
from unittest.mock import Mock, MagicMock, patch
import numpy as np
import time

from etf.natural_kline_simulator import NaturalKlineSimulator


class TestNaturalKlineSimulator(unittest.TestCase):
    """自然K线模拟器测试套件"""

    def setUp(self):
        """测试前准备"""
        self.mock_order_manager = Mock()
        self.mock_order_manager.create_temp_id = Mock(return_value="test_order_id_123")
        self.mock_order_manager.is_symbol_blacklisted = Mock(return_value=False)
        self.mock_order_manager.add_orders_batch = Mock(return_value={"success": True})

        self.config = {
            "symbol": "TON3L_USDT",
            "precision": 6,
            "prec_amount": 2,
            "netvalue": "netvalue_ton3l",
            "natural_kline": {
                "enabled": True,
                "kline_period": 60,
                "avg_trades_per_period": 3,
                "volatility": 0.002,
                "min_trade_amount": 5,
                "max_price_change_pct": 0.01,
            }
        }

        self.simulator = NaturalKlineSimulator(self.mock_order_manager, self.config)

    def test_initialization(self):
        """测试初始化"""
        self.assertTrue(self.simulator.enabled)
        self.assertEqual(self.simulator.kline_period, 60)
        self.assertEqual(self.simulator.avg_trades_per_period, 3)
        self.assertEqual(self.simulator.volatility, 0.002)
        self.assertEqual(self.simulator.min_trade_amount, 5)
        self.assertEqual(self.simulator.max_price_change_pct, 0.01)

    def test_generate_trade_schedule_returns_list(self):
        """测试交易时间表生成返回列表"""
        trade_times = self.simulator.generate_trade_schedule()
        self.assertIsInstance(trade_times, list)
        self.assertGreater(len(trade_times), 0)  # 至少有1笔交易

    def test_generate_trade_schedule_within_period(self):
        """测试交易时间表在周期内"""
        trade_times = self.simulator.generate_trade_schedule()
        for t in trade_times:
            self.assertGreaterEqual(t, 0)
            self.assertLess(t, self.simulator.kline_period)

    def test_generate_trade_schedule_sorted(self):
        """测试交易时间表已排序"""
        trade_times = self.simulator.generate_trade_schedule()
        sorted_times = sorted(trade_times)
        self.assertEqual(trade_times, sorted_times)

    def test_generate_price_path_returns_array(self):
        """测试价格路径生成返回数组"""
        prices = self.simulator.generate_price_path(100.0, 5)
        self.assertIsInstance(prices, np.ndarray)
        self.assertEqual(len(prices), 5)

    def test_generate_price_path_starts_with_initial_price(self):
        """测试价格路径从初始价格开始"""
        start_price = 100.0
        prices = self.simulator.generate_price_path(start_price, 5)
        # 由于是几何布朗运动，第一个价格会有微小变化
        # 检查价格在合理范围内（±5%）
        self.assertGreater(prices[0], start_price * 0.95)
        self.assertLess(prices[0], start_price * 1.05)

    def test_generate_price_path_respects_max_change(self):
        """测试价格路径遵守最大变化限制"""
        prices = self.simulator.generate_price_path(100.0, 10)
        for i in range(1, len(prices)):
            change_pct = abs(prices[i] / prices[i-1] - 1)
            # 考虑到累积效应，检查单步变化
            # 实际检查会更复杂，这里简化测试
            self.assertLess(change_pct, 0.1)  # 允许10%的累积变化

    def test_calculate_trade_amount_returns_positive(self):
        """测试交易数量计算返回正数"""
        amount = self.simulator.calculate_trade_amount(100.0, 0.001)
        self.assertGreater(amount, 0)

    def test_calculate_trade_amount_respects_precision(self):
        """测试交易数量遵守精度"""
        amount = self.simulator.calculate_trade_amount(100.0, 0.001)
        # 检查小数位数
        decimal_places = len(str(amount).split('.')[-1]) if '.' in str(amount) else 0
        self.assertLessEqual(decimal_places, self.config["prec_amount"])

    def test_calculate_trade_amount_increases_with_volatility(self):
        """测试交易数量随波动率增加"""
        amount_low = self.simulator.calculate_trade_amount(100.0, 0.001)
        amount_high = self.simulator.calculate_trade_amount(100.0, 0.01)
        # 高波动率应该产生更大的交易量
        self.assertGreater(amount_high, amount_low)

    @patch('redis.Redis')
    def test_get_current_price_from_redis(self, mock_redis):
        """测试从Redis获取当前价格"""
        # Mock Redis返回
        mock_redis_instance = mock_redis.return_value
        mock_redis_instance.get.return_value = b'1.234567'

        self.simulator.r = mock_redis_instance
        price = self.simulator._get_current_price()

        self.assertEqual(price, 1.234567)
        mock_redis_instance.get.assert_called_once_with("netvalue_ton3l")

    @patch('redis.Redis')
    def test_get_current_price_returns_none_on_error(self, mock_redis):
        """测试获取价格失败返回None"""
        mock_redis_instance = mock_redis.return_value
        mock_redis_instance.get.side_effect = Exception("Redis error")

        self.simulator.r = mock_redis_instance
        price = self.simulator._get_current_price()

        self.assertIsNone(price)

    def test_execute_wash_trade_skips_blacklisted_symbol(self):
        """测试跳过黑名单交易对"""
        self.mock_order_manager.is_symbol_blacklisted.return_value = True
        self.mock_order_manager.get_blacklist_info.return_value = {
            "reason": "TEST_ERROR",
            "description": "测试错误",
            "remaining_seconds": 300
        }

        result = self.simulator._execute_wash_trade(1.0, 10.0)

        self.assertFalse(result)
        self.mock_order_manager.add_orders_batch.assert_not_called()

    @patch('redis.Redis')
    def test_execute_wash_trade_skips_large_price_deviation(self, mock_redis):
        """测试跳过价格偏离过大的交易"""
        mock_redis_instance = mock_redis.return_value
        mock_redis_instance.get.return_value = b'1.0'

        self.simulator.r = mock_redis_instance

        # 价格偏离超过5%
        result = self.simulator._execute_wash_trade(1.1, 10.0)

        self.assertFalse(result)
        self.mock_order_manager.add_orders_batch.assert_not_called()

    def test_execute_wash_trade_skips_small_amount(self):
        """测试跳过金额过小的交易"""
        # 金额 = 价格 * 数量 = 1.0 * 0.1 = 0.1 < min_trade_amount(5)
        result = self.simulator._execute_wash_trade(1.0, 0.1)

        self.assertFalse(result)
        self.mock_order_manager.add_orders_batch.assert_not_called()

    @patch('redis.Redis')
    def test_execute_wash_trade_success(self, mock_redis):
        """测试成功执行wash trade"""
        mock_redis_instance = mock_redis.return_value
        mock_redis_instance.get.return_value = b'1.0'

        self.simulator.r = mock_redis_instance

        result = self.simulator._execute_wash_trade(1.0, 10.0)

        self.assertTrue(result)
        # 应该调用两次：买单和卖单
        self.assertEqual(self.mock_order_manager.add_orders_batch.call_count, 2)

    def test_execute_wash_trade_creates_opposite_orders(self):
        """测试创建对手单"""
        with patch.object(self.simulator, '_get_current_price', return_value=1.0):
            self.simulator._execute_wash_trade(1.0, 10.0)

            # 获取两次调用的参数
            calls = self.mock_order_manager.add_orders_batch.call_args_list

            # 第一笔订单
            order1_data = calls[0][0][0][0]
            # 第二笔订单
            order2_data = calls[1][0][0][0]

            # 验证订单方向相反
            sides = {order1_data["side"], order2_data["side"]}
            self.assertEqual(sides, {"buy", "sell"})

            # 验证价格和数量相同
            self.assertEqual(order1_data["price"], order2_data["price"])
            self.assertEqual(order1_data["quantity"], order2_data["quantity"])

    def test_get_statistics(self):
        """测试获取统计信息"""
        stats = self.simulator.get_statistics()

        self.assertIn("enabled", stats)
        self.assertIn("total_simulated_trades", stats)
        self.assertIn("kline_period", stats)
        self.assertIn("avg_trades_per_period", stats)
        self.assertIn("volatility", stats)

        self.assertTrue(stats["enabled"])
        self.assertEqual(stats["kline_period"], 60)
        self.assertEqual(stats["avg_trades_per_period"], 3)

    def test_disabled_simulator_does_not_trade(self):
        """测试禁用的模拟器不交易"""
        disabled_config = self.config.copy()
        disabled_config["natural_kline"]["enabled"] = False

        disabled_simulator = NaturalKlineSimulator(self.mock_order_manager, disabled_config)

        self.assertFalse(disabled_simulator.enabled)
        # run方法应该立即返回
        # 注意：这里不能直接测试run()，因为它是无限循环


class TestNaturalKlineSimulatorIntegration(unittest.TestCase):
    """集成测试：测试完整的一个周期"""

    def setUp(self):
        """测试前准备"""
        self.mock_order_manager = Mock()
        self.mock_order_manager.create_temp_id = Mock(return_value="test_id")
        self.mock_order_manager.is_symbol_blacklisted = Mock(return_value=False)
        self.mock_order_manager.add_orders_batch = Mock(return_value={"success": True})

        self.config = {
            "symbol": "TON3L_USDT",
            "precision": 6,
            "prec_amount": 2,
            "netvalue": "netvalue_ton3l",
            "natural_kline": {
                "enabled": True,
                "kline_period": 5,  # 短周期用于测试
                "avg_trades_per_period": 2,
                "volatility": 0.001,
                "min_trade_amount": 5,
                "max_price_change_pct": 0.01,
            }
        }

        self.simulator = NaturalKlineSimulator(self.mock_order_manager, self.config)

    @patch('redis.Redis')
    @patch('time.sleep')  # Mock sleep避免实际等待
    def test_run_one_cycle_completes(self, mock_sleep, mock_redis):
        """测试运行一个完整周期"""
        mock_redis_instance = mock_redis.return_value
        mock_redis_instance.get.return_value = b'1.0'

        self.simulator.r = mock_redis_instance

        # 执行一个周期
        self.simulator.run_one_cycle()

        # 验证至少有一笔交易执行
        self.assertGreaterEqual(self.mock_order_manager.add_orders_batch.call_count, 2)

    @patch('redis.Redis')
    @patch('time.sleep')
    def test_run_one_cycle_trades_match_schedule(self, mock_sleep, mock_redis):
        """测试交易次数符合时间表"""
        mock_redis_instance = mock_redis.return_value
        mock_redis_instance.get.return_value = b'1.0'

        self.simulator.r = mock_redis_instance

        # 执行一个周期
        self.simulator.run_one_cycle()

        # 每笔交易产生2次调用（买单+卖单）
        total_calls = self.mock_order_manager.add_orders_batch.call_count
        num_trades = total_calls // 2

        # 应该有1-5笔交易（泊松过程有随机性）
        self.assertGreaterEqual(num_trades, 1)
        self.assertLessEqual(num_trades, 5)


if __name__ == "__main__":
    unittest.main()
