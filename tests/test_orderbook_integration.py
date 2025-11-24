"""
订单簿算法集成测试

验证新订单簿算法与 MarketMaker 的集成
"""

import pytest
import asyncio
from decimal import Decimal
from unittest.mock import Mock, MagicMock, patch
import redis

from etf.market_making import MarketMaker
from etf.orderbook.base import OrderbookConfig, OrderbookFactory
from etf.order_manager import OrderManager


class TestOrderbookIntegration:
    """订单簿集成测试类"""

    @pytest.fixture
    def mock_order_manager(self):
        """创建模拟的OrderManager"""
        manager = Mock(spec=OrderManager)
        manager.client = Mock()
        manager.netvalue = 1.0
        manager.create_temp_id = Mock(side_effect=lambda: f"test_{id(object())}")
        manager.get_min_order_value = Mock(return_value=1.2)

        # 模拟Redis
        manager.r = Mock(spec=redis.Redis)

        return manager

    @pytest.fixture
    def market_maker(self, mock_order_manager):
        """创建MarketMaker实例"""
        return MarketMaker(mock_order_manager)

    @pytest.fixture
    def base_config(self):
        """基础策略配置"""
        return {
            "netvalue": "netvalue_ton3s",
            "bid_ask_spread": 0.01,
            "precision": 6,
            "prec_amount": 2,
            "anti_pin_rate": 0.2,
            "anti_pin_usdt": 300,
            "layer": 30,
        }

    def test_orderbook_algorithm_config(self, base_config):
        """测试1: 验证订单簿算法配置正确"""
        # 测试natural算法配置
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=5000,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol="TON3S_USDT",
            price_precision=6,
            quantity_precision=2,
            extra_params={"naturalness": "high"}
        )

        # 创建算法实例
        algorithm = OrderbookFactory.create("natural", config)

        assert algorithm.algorithm_name == "natural"
        assert algorithm.config.layer == 5000
        assert algorithm.config.total_budget == 1000.0

    def test_orderbook_generation_performance(self, base_config):
        """测试2: 验证订单簿生成性能"""
        import time

        # 测试不同档位的生成速度
        layer_tests = [1000, 5000, 10000, 50000]

        for layer in layer_tests:
            config = OrderbookConfig(
                total_budget=10000.0,
                layer=layer,
                mid_price=1.0,
                bid_ask_spread=0.01,
                symbol="TEST_USDT",
                extra_params={"naturalness": "high"}
            )

            algorithm = OrderbookFactory.create("natural", config)

            start = time.time()
            snapshot = algorithm.generate_snapshot()
            elapsed = time.time() - start

            # 验证档位数正确
            total_layers = len(snapshot.bids) + len(snapshot.asks)
            assert total_layers == layer, f"档位数不匹配: {total_layers} vs {layer}"

            # 验证性能要求（根据文档）
            if layer == 5000:
                assert elapsed < 0.05, f"5000档生成耗时 {elapsed:.3f}s 超过50ms"
            elif layer == 10000:
                assert elapsed < 0.10, f"10000档生成耗时 {elapsed:.3f}s 超过100ms"
            elif layer == 50000:
                assert elapsed < 0.50, f"50000档生成耗时 {elapsed:.3f}s 超过500ms"

            print(f"{layer:>6}档: {elapsed*1000:>7.2f}ms, {float(snapshot.total_value):>10.2f} USDT")

    def test_market_maker_integration_with_new_algorithm(
        self, market_maker, mock_order_manager, base_config
    ):
        """测试3: 验证MarketMaker与新算法的集成"""
        # 配置使用新算法
        config = base_config.copy()
        config["orderbook_algorithm"] = "natural"
        config["orderbook_config"] = {
            "total_budget": 1000.0,
            "layer": 5000,
            "extra_params": {"naturalness": "high"}
        }

        # 模拟Redis返回净值
        mock_order_manager.r.get = Mock(return_value=b"1.0")

        # 模拟获取当前订单
        mock_order_manager.client.get_open_orders = Mock(return_value=[])

        # 模拟批量下单和撤单
        mock_order_manager.add_orders_batch = Mock(return_value={"status": "success"})
        mock_order_manager.cancel_orders_batch = Mock(return_value={"status": "success"})

        # 执行place_orders
        market_maker.place_orders(
            config=config,
            symbol="ton3s_usdt",
            env="qa"
        )

        # 验证：调用了add_orders_batch（说明订单簿生成成功）
        assert mock_order_manager.add_orders_batch.called, "未调用批量下单"

        # 验证：生成的订单数量正确（5000档 + 2个反针对订单）
        call_args = mock_order_manager.add_orders_batch.call_args_list
        total_orders = sum(len(call[0][0]) for call in call_args)

        # 应该有5000档订单 + 2个反针对订单
        assert total_orders > 5000, f"订单数量不足: {total_orders}"

    def test_backward_compatibility_with_old_orderbook(
        self, market_maker, mock_order_manager, base_config
    ):
        """测试4: 验证向后兼容性（旧订单簿系统）"""
        # 不配置orderbook_algorithm，使用默认订单簿
        config = base_config.copy()

        # 模拟Redis返回净值
        mock_order_manager.r.get = Mock(return_value=b"1.0")
        mock_order_manager.client.get_open_orders = Mock(return_value=[])
        mock_order_manager.add_orders_batch = Mock(return_value={"status": "success"})
        mock_order_manager.cancel_orders_batch = Mock(return_value={"status": "success"})

        # 执行place_orders
        market_maker.place_orders(
            config=config,
            symbol="ton3s_usdt",
            env="qa"
        )

        # 验证：仍然可以正常下单
        assert mock_order_manager.add_orders_batch.called

    def test_orderbook_snapshot_format_compatibility(self):
        """测试5: 验证订单簿快照格式兼容性"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=1000,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol="TEST_USDT",
            extra_params={"naturalness": "medium"}
        )

        algorithm = OrderbookFactory.create("natural", config)
        snapshot = algorithm.generate_snapshot()

        # 验证：可以转换为字典格式
        dict_format = snapshot.to_dict()

        assert "bids" in dict_format
        assert "asks" in dict_format
        assert "algorithm" in dict_format
        assert "metadata" in dict_format

        # 验证：bids和asks格式正确（[[price, quantity], ...]）
        assert isinstance(dict_format["bids"], list)
        assert isinstance(dict_format["asks"], list)

        if len(dict_format["bids"]) > 0:
            assert len(dict_format["bids"][0]) == 2  # [price, quantity]
            assert isinstance(dict_format["bids"][0][0], float)
            assert isinstance(dict_format["bids"][0][1], float)

    def test_price_change_threshold_optimization(
        self, market_maker, mock_order_manager, base_config
    ):
        """测试6: 验证价格变化阈值优化"""
        config = base_config.copy()
        config["orderbook_algorithm"] = "natural"
        config["orderbook_config"] = {
            "total_budget": 1000.0,
            "layer": 1000,
            "extra_params": {"naturalness": "medium"}
        }

        # 模拟Redis返回净值
        mock_order_manager.r.get = Mock(return_value=b"1.0")
        mock_order_manager.client.get_open_orders = Mock(return_value=[])
        mock_order_manager.add_orders_batch = Mock(return_value={"status": "success"})

        # 第一次调用：初始化
        market_maker.place_orders(config=config, symbol="ton3s_usdt", env="qa")
        first_call_count = mock_order_manager.add_orders_batch.call_count

        # 重置mock
        mock_order_manager.add_orders_batch.reset_mock()

        # 第二次调用：价格变化很小（0.01%）
        mock_order_manager.r.get = Mock(return_value=b"1.0001")
        market_maker.place_orders(config=config, symbol="ton3s_usdt", env="qa")

        # 验证：由于价格变化小于阈值（0.05%），不应重新下单
        assert mock_order_manager.add_orders_batch.call_count == 0, \
            "价格变化小于阈值时不应重新下单"

        # 重置mock
        mock_order_manager.add_orders_batch.reset_mock()

        # 第三次调用：价格变化大（0.1%）
        mock_order_manager.r.get = Mock(return_value=b"1.001")
        mock_order_manager.client.get_open_orders = Mock(return_value=[])
        market_maker.place_orders(config=config, symbol="ton3s_usdt", env="qa")

        # 验证：价格变化超过阈值，应该重新下单
        assert mock_order_manager.add_orders_batch.call_count > 0, \
            "价格变化超过阈值时应该重新下单"


class TestOrderbookAlgorithmSelection:
    """测试订单簿算法选择逻辑"""

    @pytest.fixture
    def mock_order_manager(self):
        """创建模拟的OrderManager（独立fixture）"""
        manager = Mock(spec=OrderManager)
        manager.client = Mock()
        manager.netvalue = 1.0
        manager.create_temp_id = Mock(side_effect=lambda: f"test_{id(object())}")
        manager.get_min_order_value = Mock(return_value=1.2)
        manager.r = Mock(spec=redis.Redis)
        return manager

    def test_priority_orderbook_algorithm_over_equal_value(self, mock_order_manager):
        """测试7: 验证算法优先级（orderbook_algorithm > use_equal_value_orderbook）"""
        market_maker = MarketMaker(mock_order_manager)

        config = {
            "netvalue": "netvalue_test",
            "bid_ask_spread": 0.01,
            "precision": 6,
            "prec_amount": 2,
            "anti_pin_rate": 0.2,
            "anti_pin_usdt": 300,

            # 同时配置两种
            "orderbook_algorithm": "natural",
            "use_equal_value_orderbook": True,

            "orderbook_config": {
                "total_budget": 1000.0,
                "layer": 1000,
                "extra_params": {"naturalness": "low"}
            },
            "target_value_per_order": 2.0,
        }

        # 模拟
        mock_order_manager.r.get = Mock(return_value=b"1.0")
        mock_order_manager.client.get_open_orders = Mock(return_value=[])
        mock_order_manager.add_orders_batch = Mock(return_value={"status": "success"})
        mock_order_manager.cancel_orders_batch = Mock(return_value={"status": "success"})

        # 执行
        market_maker.place_orders(config=config, symbol="test_usdt", env="qa")

        # 验证：应该使用natural算法（日志中会显示）
        # 这里我们通过订单数量验证：natural 1000档 vs 等价值30档
        call_args = mock_order_manager.add_orders_batch.call_args_list
        total_orders = sum(len(call[0][0]) for call in call_args)

        # natural算法生成1000档，等价值只有30档左右
        assert total_orders > 900, f"应该使用natural算法（1000档）而非等价值算法，实际{total_orders}档"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
