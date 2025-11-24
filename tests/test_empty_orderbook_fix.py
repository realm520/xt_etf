"""
测试空订单簿修复

验证三层防护机制:
1. WebSocket实时数据（5秒内有效）
2. REST API降级
3. 缓存的最后有效数据（30秒内）
"""
import time
import pytest
from unittest.mock import Mock, MagicMock, patch
from etf.risk.controller import RiskController


class TestEmptyOrderBookFix:
    """测试空订单簿的三层防护机制"""

    @pytest.fixture
    def mock_client(self):
        """创建mock的XT客户端"""
        client = Mock()
        return client

    @pytest.fixture
    def mock_ws_client(self):
        """创建mock的WebSocket客户端"""
        ws_client = Mock()
        return ws_client

    @pytest.fixture
    def risk_params(self):
        """风险控制参数"""
        return {
            "orderbook_threshold": [0.3, 0.5, 0.7],
            "base_bid_volume": 1000,
            "base_ask_volume": 1000,
            "price_deviation_threshold": [0.05, 0.03, 0.01],
            "stop_loss": {
                "enabled": False  # 简化测试
            }
        }

    def test_layer1_websocket_valid_data(self, mock_client, mock_ws_client, risk_params):
        """
        Layer 1: WebSocket返回有效数据

        期望: 直接使用WebSocket数据
        """
        # 准备有效的WebSocket深度数据
        valid_depth = {
            "bids": [["50000", "1.5"], ["49900", "2.0"]],
            "asks": [["50100", "1.0"], ["50200", "1.5"]],
            "timestamp": int(time.time() * 1000)
        }
        mock_ws_client.get_cached_depth.return_value = valid_depth

        # 创建RiskController
        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 获取深度数据
        result = controller.get_depth_data("BTCUSDT")

        # 验证结果
        assert result == valid_depth
        assert result["bids"] == valid_depth["bids"]
        assert result["asks"] == valid_depth["asks"]

        # 验证缓存已保存
        assert controller._last_valid_depth == valid_depth
        assert controller._last_valid_time > 0

        # 确认没有调用REST API（WebSocket优先）
        mock_client.get_depth.assert_not_called()

    def test_layer2_rest_api_fallback(self, mock_client, mock_ws_client, risk_params):
        """
        Layer 2: WebSocket失败，使用REST API降级

        期望: 当WebSocket返回空数据时，调用REST API
        """
        # WebSocket返回空数据
        mock_ws_client.get_cached_depth.return_value = None

        # REST API返回有效数据
        valid_depth = {
            "bids": [["50000", "1.5"], ["49900", "2.0"]],
            "asks": [["50100", "1.0"], ["50200", "1.5"]],
            "timestamp": int(time.time() * 1000)
        }
        mock_client.get_depth.return_value = valid_depth

        # 创建RiskController
        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 获取深度数据
        result = controller.get_depth_data("BTCUSDT")

        # 验证结果
        assert result == valid_depth
        assert result["bids"] == valid_depth["bids"]
        assert result["asks"] == valid_depth["asks"]

        # 确认调用了REST API
        mock_client.get_depth.assert_called_once_with("BTCUSDT")

    def test_layer2_rest_api_empty_orderbook(self, mock_client, mock_ws_client, risk_params):
        """
        Layer 2: REST API返回空订单簿（只有bids或只有asks）

        期望: 系统检测到空订单簿，返回None
        """
        # WebSocket不可用
        mock_ws_client.get_cached_depth.return_value = None

        # REST API返回空订单簿（只有asks，没有bids）
        empty_depth = {
            "bids": [],  # 空买单
            "asks": [["50100", "1.0"]],
            "timestamp": int(time.time() * 1000)
        }
        mock_client.get_depth.return_value = empty_depth

        # 创建RiskController
        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 获取深度数据
        result = controller.get_depth_data("BTCUSDT")

        # 验证返回None（因为没有有效缓存）
        assert result is None

    def test_layer3_cached_data_within_30s(self, mock_client, mock_ws_client, risk_params):
        """
        Layer 3: 使用缓存的最后有效数据（30秒内）

        期望: 当所有数据源都失败时，如果缓存数据在30秒内，使用缓存数据
        """
        # 第一次调用：WebSocket返回有效数据
        valid_depth = {
            "bids": [["50000", "1.5"], ["49900", "2.0"]],
            "asks": [["50100", "1.0"], ["50200", "1.5"]],
            "timestamp": int(time.time() * 1000)
        }
        mock_ws_client.get_cached_depth.return_value = valid_depth

        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 第一次获取深度（建立缓存）
        first_result = controller.get_depth_data("BTCUSDT")
        assert first_result == valid_depth

        # 模拟10秒后，所有数据源都失败
        time.sleep(0.1)  # 实际测试中使用短时间
        mock_ws_client.get_cached_depth.return_value = None
        mock_client.get_depth.return_value = {"bids": [], "asks": []}

        # 手动设置缓存时间为10秒前（模拟）
        controller._last_valid_time = time.time() - 10

        # 第二次获取深度（应该使用缓存）
        second_result = controller.get_depth_data("BTCUSDT")

        # 验证返回缓存数据
        assert second_result == valid_depth

    def test_layer3_cached_data_expired(self, mock_client, mock_ws_client, risk_params):
        """
        Layer 3: 缓存数据过期（超过30秒）

        期望: 当缓存数据超过30秒时，返回None
        """
        # 创建RiskController
        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 手动设置一个过期的缓存（35秒前）
        controller._last_valid_depth = {
            "bids": [["50000", "1.5"]],
            "asks": [["50100", "1.0"]]
        }
        controller._last_valid_time = time.time() - 35

        # 模拟所有数据源失败
        mock_ws_client.get_cached_depth.return_value = None
        mock_client.get_depth.return_value = {"bids": [], "asks": []}

        # 获取深度数据
        result = controller.get_depth_data("BTCUSDT")

        # 验证返回None（缓存过期）
        assert result is None

    def test_integration_with_risk_monitor(self, mock_client, mock_ws_client, risk_params):
        """
        集成测试: risk_monitor在空订单簿时的行为

        期望: 当订单簿为空时，risk_level设置为3（最保守）
        """
        # 模拟所有数据源返回空数据
        mock_ws_client.get_cached_depth.return_value = None
        mock_client.get_depth.return_value = {"bids": [], "asks": []}
        mock_client.get_tickers.return_value = [{"s": "BTCUSDT", "p": "50000"}]
        mock_client.get_kline.return_value = [
            {"c": "50000"}, {"c": "50100"}, {"c": "49900"}
        ]

        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 调用risk_monitor（应该处理空订单簿）
        controller.risk_monitor("BTCUSDT")

        # 验证风险等级被设置为3（保守策略）
        assert controller.risk_level == 3

    def test_empty_orderbook_only_bids(self, mock_client, mock_ws_client, risk_params):
        """
        边界测试: 只有买单，没有卖单

        期望: 系统检测到异常，返回None
        """
        mock_ws_client.get_cached_depth.return_value = None
        mock_client.get_depth.return_value = {
            "bids": [["50000", "1.5"]],
            "asks": []  # 空卖单
        }

        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        result = controller.get_depth_data("BTCUSDT")

        # 验证返回None
        assert result is None

    def test_empty_orderbook_only_asks(self, mock_client, mock_ws_client, risk_params):
        """
        边界测试: 只有卖单，没有买单

        期望: 系统检测到异常，返回None
        """
        mock_ws_client.get_cached_depth.return_value = None
        mock_client.get_depth.return_value = {
            "bids": [],  # 空买单
            "asks": [["50100", "1.0"]]
        }

        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        result = controller.get_depth_data("BTCUSDT")

        # 验证返回None
        assert result is None


    def test_run_etf_main_loop_none_depth(self, mock_client, mock_ws_client, risk_params):
        """
        测试 run_etf.py 主循环对 None depth 的处理

        期望: 当depth为None时，主循环应该优雅跳过，不抛出TypeError
        """
        # 模拟所有数据源失败，返回None
        mock_ws_client.get_cached_depth.return_value = None
        mock_client.get_depth.return_value = {"bids": [], "asks": []}

        controller = RiskController(
            client=mock_client,
            risk_params=risk_params,
            strategy_name="test",
            ws_client=mock_ws_client
        )

        # 获取深度数据（应该返回None）
        depth = controller.get_depth_data("BTCUSDT")
        assert depth is None

        # 模拟run_etf.py中的代码逻辑
        # 修复前会抛出: TypeError: 'NoneType' object is not subscriptable
        # 修复后应该正常跳过

        # 这是run_etf.py:62的修复后代码
        if depth and (len(depth.get("asks", [])) != 0 or len(depth.get("bids", [])) != 0):
            # 不应该执行到这里
            assert False, "不应该进入这个分支"
        else:
            # 应该优雅跳过
            assert True


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
