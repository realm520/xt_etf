#!/usr/bin/env python3
"""
WebSocket订单同步集成测试

测试OrderManager与OrderWebSocketClient的集成功能
"""
import pytest
import time
import logging
from unittest.mock import Mock, MagicMock, patch
from etf.order_manager import OrderManager

logging.basicConfig(level=logging.DEBUG)


class TestWebSocketIntegration:
    """WebSocket订单同步集成测试"""

    @pytest.fixture
    def mock_client(self):
        """创建模拟XT客户端"""
        client = Mock()
        client.api_key = "test_access_key"
        client.api_secret = "test_secret_key"
        return client

    @pytest.fixture
    def mock_symbol_config(self):
        """创建模拟Symbol配置"""
        config = Mock()
        config._config_cache = {"btc_usdt": {"price_precision": 2}}
        return config

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    def test_websocket_initialization(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试WebSocket初始化"""
        # 创建模拟WebSocket客户端
        mock_ws_instance = MagicMock()
        mock_ws_class.return_value = mock_ws_instance

        # 创建OrderManager（启用WebSocket）
        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 验证WebSocket初始化
        assert order_manager.use_order_websocket is True
        assert order_manager.order_ws_client is not None
        mock_ws_instance.start.assert_called_once()

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', False)
    def test_websocket_disabled(self, mock_client, mock_symbol_config):
        """测试WebSocket不可用时的降级"""
        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 验证降级到REST API
        assert order_manager.use_order_websocket is False
        assert order_manager.order_ws_client is None

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    def test_order_update_callback(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试订单更新回调"""
        mock_ws_instance = MagicMock()
        mock_ws_class.return_value = mock_ws_instance

        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 模拟订单更新
        order_data = {
            "orderId": "12345",
            "state": "NEW",
            "symbol": "btc_usdt",
            "side": "BUY",
            "price": "50000",
            "origQty": "0.001",
            "executedQty": "0",
            "time": 1737039804101,
            "updatedTime": 1737039804101
        }

        # 调用回调
        order_manager._on_order_update(order_data)

        # 验证订单被添加到open_orders
        assert "12345" in order_manager.open_orders
        assert order_manager.open_orders["12345"]["symbol"] == "btc_usdt"
        assert order_manager.open_orders["12345"]["side"] == "BUY"

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    def test_partially_filled_callback(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试部分成交订单回调"""
        mock_ws_instance = MagicMock()
        mock_ws_class.return_value = mock_ws_instance

        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 模拟部分成交订单
        order_data = {
            "orderId": "12345",
            "state": "PARTIALLY_FILLED",
            "symbol": "btc_usdt",
            "side": "BUY",
            "price": "50000",
            "origQty": "0.001",
            "executedQty": "0.0005",
            "time": 1737039804101,
            "updatedTime": 1737039805123
        }

        # 调用回调
        order_manager._on_order_update(order_data)

        # 验证订单被添加到open_orders和partially_filled_orders
        assert "12345" in order_manager.open_orders
        assert "12345" in order_manager.partially_filled_orders
        assert order_manager.partially_filled_orders["12345"]["executedQty"] == "0.0005"

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    def test_filled_order_callback(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试完全成交订单回调"""
        mock_ws_instance = MagicMock()
        mock_ws_class.return_value = mock_ws_instance

        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 先添加订单到open_orders
        order_manager.open_orders["12345"] = {
            "symbol": "btc_usdt",
            "side": "BUY",
            "price": "50000",
            "quantity": "0.001"
        }

        # 模拟完全成交
        order_data = {
            "orderId": "12345",
            "state": "FILLED",
            "symbol": "btc_usdt",
            "side": "BUY",
            "price": "50000",
            "origQty": "0.001",
            "executedQty": "0.001",
            "time": 1737039804101,
            "updatedTime": 1737039805123
        }

        # 调用回调
        order_manager._on_order_update(order_data)

        # 验证订单从open_orders中移除，添加到filled_orders
        assert "12345" not in order_manager.open_orders
        assert "12345" in order_manager.filled_orders

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    @patch('etf.order_manager.ORDER_RECORDER_AVAILABLE', False)
    def test_trade_callback(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试成交推送回调"""
        mock_ws_instance = MagicMock()
        mock_ws_class.return_value = mock_ws_instance

        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 模拟成交推送
        trade_data = {
            "tradeId": "67890",
            "orderId": "12345",
            "symbol": "btc_usdt",
            "side": "BUY",
            "price": "50000",
            "quantity": "0.001",
            "fee": "0.025",
            "feeCurrency": "USDT",
            "isMaker": False,
            "time": 1737039805123
        }

        # 调用回调
        order_manager._on_trade(trade_data)

        # 验证成交被记录到trading_history
        assert len(order_manager.trading_history) > 0
        latest_trade = order_manager.trading_history[-1]
        assert latest_trade["order_id"] == "12345"
        assert latest_trade["price"] == 50000.0
        assert latest_trade["quantity"] == 0.001

        # 验证成交被记录到recent_fills
        assert len(order_manager.recent_fills) > 0

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    def test_cleanup(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试资源清理"""
        mock_ws_instance = MagicMock()
        mock_ws_class.return_value = mock_ws_instance

        order_manager = OrderManager(
            spot=mock_client,
            strategy_name="test_stg",
            symbol_config=mock_symbol_config,
            enable_websocket=True
        )

        # 调用清理方法
        order_manager.cleanup()

        # 验证WebSocket被停止
        mock_ws_instance.stop.assert_called_once()

    @patch('etf.order_manager.ORDER_WEBSOCKET_AVAILABLE', True)
    @patch('etf.order_manager.OrderWebSocketClient')
    def test_get_position_with_websocket(self, mock_ws_class, mock_client, mock_symbol_config):
        """测试使用WebSocket获取持仓"""
        mock_ws_instance = MagicMock()
        mock_ws_instance.get_stats.return_value = {
            'connected': True,
            'messages_received': 100,
            'order_updates': 50
        }
        mock_ws_class.return_value = mock_ws_instance

        # Mock get_depth_data
        with patch.object(OrderManager, 'get_depth_data') as mock_depth:
            mock_depth.return_value = {
                'bids': [['50000', '1.0']],
                'asks': [['50100', '1.0']]
            }

            order_manager = OrderManager(
                spot=mock_client,
                strategy_name="test_stg",
                symbol_config=mock_symbol_config,
                enable_websocket=True
            )

            # 添加模拟订单
            order_manager.open_orders = {}

            # 调用get_position（应该跳过reset_open_orders）
            result = order_manager.get_position("btc_usdt")

            # 验证结果
            assert result == 0  # 没有订单时返回0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
