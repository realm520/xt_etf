"""
测试做市商订单更新优化

测试要点：
1. 价格变化检测机制
2. 先挂新单再撤旧单的执行顺序
3. 避免盘口BBO spread扩大
"""
import pytest
from unittest.mock import Mock, MagicMock, patch, call
from etf.market_making import MarketMaker


class TestMarketMakerOptimization:
    """做市商优化测试"""

    @pytest.fixture
    def mock_order_manager(self):
        """创建模拟订单管理器"""
        manager = Mock()
        manager.create_temp_id = Mock(side_effect=lambda: f"order_{id(object())}")
        manager.netvalue = 1.0
        manager.get_min_order_value = Mock(return_value=1.2)
        manager.client = Mock()
        manager.client.get_open_orders = Mock(return_value=[])
        manager.add_orders_batch = Mock(return_value={"success": True})
        manager.cancel_orders_batch = Mock(return_value={"success": True})
        return manager

    @pytest.fixture
    def market_maker(self, mock_order_manager):
        """创建做市商实例"""
        mm = MarketMaker(mock_order_manager)
        # Mock Redis
        mm.r = Mock()
        mm.r.get = Mock(return_value=b"1.0")
        mm.r.set = Mock()
        return mm

    @pytest.fixture
    def config(self):
        """测试配置"""
        return {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.01,
            "anti_pin_rate": 0.20,
            "anti_pin_usdt": 300,
            "precision": 6,
            "prec_amount": 2,
        }

    def test_price_change_detection_skip_update(self, market_maker, config):
        """测试价格变化不大时跳过更新"""
        # 设置初始净值
        market_maker.last_netvalue = 1.0
        market_maker.r.get.return_value = b"1.0003"  # 0.03%变化，小于阈值0.05%

        # 执行
        market_maker.place_orders(config, symbol="test_usdt")

        # 验证：不应该调用订单管理器
        market_maker.order_manager.add_orders_batch.assert_not_called()
        market_maker.order_manager.cancel_orders_batch.assert_not_called()

    def test_price_change_detection_trigger_update(self, market_maker, config):
        """测试价格显著变化时触发更新"""
        # 设置初始净值
        market_maker.last_netvalue = 1.0
        market_maker.r.get.return_value = b"1.0006"  # 0.06%变化，超过阈值0.05%

        with patch('etf.market_making.get_orderbook') as mock_orderbook, \
             patch('etf.market_making.optimize_order_matching') as mock_matching:

            # 模拟订单簿生成
            mock_orderbook.return_value = (
                [{"price": 0.99, "amount": 2.0, "direction": "bid", "min_price": 0.985, "max_price": 0.995}],
                [{"price": 1.01, "amount": 2.0, "direction": "ask", "min_price": 1.005, "max_price": 1.015}]
            )

            # 模拟订单匹配
            mock_matching.return_value = (
                [{"symbol": "test_usdt", "side": "BUY", "price": 0.99, "quantity": 2.0}],  # add
                []  # cancel
            )

            # 执行
            market_maker.place_orders(config, symbol="test_usdt")

            # 验证：应该调用订单管理器
            market_maker.order_manager.add_orders_batch.assert_called()

    @patch('time.sleep')  # Mock sleep to speed up tests
    def test_add_before_cancel_execution_order(self, mock_sleep, market_maker, config):
        """测试先挂新单再撤旧单的执行顺序"""
        # 设置有变化的净值
        market_maker.last_netvalue = 1.0
        market_maker.r.get.return_value = b"1.01"  # 1%变化

        # 模拟当前有旧订单
        market_maker.order_manager.client.get_open_orders.return_value = [
            {"orderId": "old_1", "price": "0.98", "side": "BUY", "quantity": "2.0"},
        ]

        with patch('etf.market_making.get_orderbook') as mock_orderbook, \
             patch('etf.market_making.optimize_order_matching') as mock_matching:

            # 模拟订单簿
            mock_orderbook.return_value = (
                [{"price": 1.00, "amount": 2.0, "direction": "bid", "min_price": 0.995, "max_price": 1.005}],
                [{"price": 1.02, "amount": 2.0, "direction": "ask", "min_price": 1.015, "max_price": 1.025}]
            )

            # 模拟订单匹配结果：需要添加新单和取消旧单
            new_orders = [{"symbol": "test_usdt", "side": "BUY", "price": 1.00, "quantity": 2.0}]
            old_orders = [{"orderId": "old_1", "price": "0.98", "side": "BUY"}]
            mock_matching.return_value = (new_orders, old_orders)

            # 记录调用顺序
            call_order = []
            market_maker.order_manager.add_orders_batch.side_effect = lambda *args, **kwargs: call_order.append("add")
            market_maker.order_manager.cancel_orders_batch.side_effect = lambda *args, **kwargs: call_order.append("cancel")

            # 执行
            market_maker.place_orders(config, symbol="test_usdt")

            # 验证：先add后cancel
            assert call_order == ["add", "cancel"], f"执行顺序错误: {call_order}"

            # 验证：sleep被调用（等待新订单上盘）
            mock_sleep.assert_called_with(0.1)

    def test_first_run_initialization(self, market_maker, config):
        """测试首次运行初始化"""
        # 首次运行，last_netvalue为None
        assert market_maker.last_netvalue is None

        market_maker.r.get.return_value = b"1.0"

        with patch('etf.market_making.get_orderbook') as mock_orderbook, \
             patch('etf.market_making.optimize_order_matching') as mock_matching:

            mock_orderbook.return_value = (
                [{"price": 0.99, "amount": 2.0, "direction": "bid", "min_price": 0.985, "max_price": 0.995}],
                [{"price": 1.01, "amount": 2.0, "direction": "ask", "min_price": 1.005, "max_price": 1.015}]
            )
            mock_matching.return_value = ([{"symbol": "test_usdt", "side": "BUY", "price": 0.99, "quantity": 2.0}], [])

            # 执行
            market_maker.place_orders(config, symbol="test_usdt")

            # 验证：首次运行应该更新订单
            market_maker.order_manager.add_orders_batch.assert_called()

            # 验证：last_netvalue被设置
            assert market_maker.last_netvalue == 1.0

    def test_anti_pin_orders_included_in_add_batch(self, market_maker, config):
        """测试反针对订单包含在新增订单批次中"""
        market_maker.last_netvalue = None  # 首次运行
        market_maker.r.get.return_value = b"1.0"

        with patch('etf.market_making.get_orderbook') as mock_orderbook, \
             patch('etf.market_making.optimize_order_matching') as mock_matching:

            mock_orderbook.return_value = (
                [{"price": 0.99, "amount": 2.0, "direction": "bid", "min_price": 0.985, "max_price": 0.995}],
                [{"price": 1.01, "amount": 2.0, "direction": "ask", "min_price": 1.005, "max_price": 1.015}]
            )
            mock_matching.return_value = ([], [])

            # 执行
            market_maker.place_orders(config, symbol="test_usdt")

            # 获取add_orders_batch的调用参数
            assert market_maker.order_manager.add_orders_batch.called
            call_args = market_maker.order_manager.add_orders_batch.call_args
            added_orders = call_args[0][0]  # 第一个参数是订单列表

            # 验证：应该有2个反针对订单（买+卖）
            anti_pin_orders = [o for o in added_orders if o.get("clientOrderId") in market_maker.current_anti_pin_order_ids]
            assert len(anti_pin_orders) == 2

            # 验证：一个买单一个卖单
            sides = [o["side"] for o in anti_pin_orders]
            assert "BUY" in sides
            assert "SELL" in sides


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
