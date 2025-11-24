"""
订单簿模块基础测试

测试：
1. 算法注册和工厂
2. 自然算法生成
3. 订单簿差异计算
4. 执行器模拟
"""

import pytest
from decimal import Decimal

from etf.orderbook import (
    OrderbookConfig,
    OrderbookFactory,
    OrderbookDiff,
    OrderOperation,
)


class TestAlgorithmFactory:
    """测试算法工厂"""

    def test_list_algorithms(self):
        """测试算法列表"""
        algorithms = OrderbookFactory.list_algorithms()
        assert 'natural' in algorithms

    def test_create_natural_algorithm(self):
        """测试创建自然算法"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=1000,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol='TEST_USDT',
        )

        algorithm = OrderbookFactory.create('natural', config)
        assert algorithm.algorithm_name == 'natural'

    def test_create_unknown_algorithm(self):
        """测试创建未知算法"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=100,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol='TEST_USDT',
        )

        with pytest.raises(ValueError, match="Unknown algorithm"):
            OrderbookFactory.create('unknown', config)


class TestNaturalAlgorithm:
    """测试自然算法"""

    def test_generate_snapshot_small(self):
        """测试小档位生成（1000档）"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=1000,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol='TEST_USDT',
            extra_params={'naturalness': 'medium'}
        )

        algorithm = OrderbookFactory.create('natural', config)
        snapshot = algorithm.generate_snapshot()

        # 验证档位数
        assert len(snapshot.bids) + len(snapshot.asks) == 1000

        # 验证买卖盘分布
        assert abs(len(snapshot.bids) - 500) < 5  # 允许±5误差

        # 验证总预算
        total_value = float(snapshot.total_value)
        assert 900 < total_value < 1100  # 允许±10%误差

        # 验证生成时间
        assert snapshot.generation_time < 1.0  # 应该<1秒

    def test_generate_snapshot_large(self):
        """测试大档位生成（10000档）"""
        config = OrderbookConfig(
            total_budget=5000.0,
            layer=10000,
            mid_price=50000.0,
            bid_ask_spread=0.01,
            symbol='BTC_USDT',
            extra_params={'naturalness': 'high'}
        )

        algorithm = OrderbookFactory.create('natural', config)
        snapshot = algorithm.generate_snapshot()

        assert len(snapshot.bids) + len(snapshot.asks) == 10000
        assert snapshot.generation_time < 2.0  # 应该<2秒

    def test_price_distribution(self):
        """测试价格分布特征"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=1000,
            mid_price=100.0,
            bid_ask_spread=0.01,
            symbol='TEST_USDT',
        )

        algorithm = OrderbookFactory.create('natural', config)
        snapshot = algorithm.generate_snapshot()

        # 买盘应该递减
        bid_prices = [float(level.price) for level in snapshot.bids]
        assert bid_prices == sorted(bid_prices, reverse=True)

        # 卖盘应该递增
        ask_prices = [float(level.price) for level in snapshot.asks]
        assert ask_prices == sorted(ask_prices)

        # BBO价差应该接近配置
        bbo_spread = (ask_prices[0] - bid_prices[0]) / 100.0
        assert 0.008 < bbo_spread < 0.012  # 配置0.01，允许±20%


class TestOrderbookDiff:
    """测试订单簿差异"""

    def test_compute_diff_empty_to_new(self):
        """测试从空订单簿到新订单簿"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=100,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol='TEST_USDT',
        )

        algorithm = OrderbookFactory.create('natural', config)

        # 当前订单簿为空
        current_orders = {'bids': [], 'asks': []}

        diff = algorithm.compute_diff(current_orders)

        # 应该只有add操作
        assert diff.num_adds == 100
        assert diff.num_cancels == 0

    def test_compute_diff_refresh(self):
        """测试刷新订单簿（取消旧的，添加新的）"""
        config = OrderbookConfig(
            total_budget=1000.0,
            layer=100,
            mid_price=1.0,
            bid_ask_spread=0.01,
            symbol='TEST_USDT',
        )

        algorithm = OrderbookFactory.create('natural', config)

        # 模拟当前订单簿
        current_orders = {
            'bids': [
                {'order_id': 'bid1', 'price': 0.99, 'quantity': 10},
                {'order_id': 'bid2', 'price': 0.98, 'quantity': 10},
            ],
            'asks': [
                {'order_id': 'ask1', 'price': 1.01, 'quantity': 10},
                {'order_id': 'ask2', 'price': 1.02, 'quantity': 10},
            ],
        }

        diff = algorithm.compute_diff(current_orders)

        # 应该先取消4个旧订单，再添加100个新订单
        assert diff.num_cancels == 4
        assert diff.num_adds == 100


class TestOrderOperation:
    """测试订单操作"""

    def test_add_operation(self):
        """测试添加操作"""
        op = OrderOperation(
            action='add',
            side='bid',
            price=Decimal('1.0'),
            quantity=Decimal('10.0'),
        )

        assert op.action == 'add'
        assert op.side == 'bid'

    def test_cancel_operation(self):
        """测试取消操作"""
        op = OrderOperation(
            action='cancel',
            side='ask',
            order_id='test_order_123',
        )

        assert op.action == 'cancel'
        assert op.order_id == 'test_order_123'

    def test_invalid_add_operation(self):
        """测试无效的添加操作（缺少价格）"""
        with pytest.raises(ValueError):
            OrderOperation(
                action='add',
                side='bid',
                # 缺少price和quantity
            )

    def test_invalid_cancel_operation(self):
        """测试无效的取消操作（缺少order_id）"""
        with pytest.raises(ValueError):
            OrderOperation(
                action='cancel',
                side='bid',
                # 缺少order_id
            )


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
