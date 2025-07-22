# -*- coding:utf-8 -*-

"""
测试订单簿模块

Author: Claude Code
Date: 2025-01-22
"""

import pytest
import numpy as np
from etf.orderbook import Orderbook, get_orderbook


class TestOrderbook:
    """测试订单簿类"""

    def test_init(self):
        """测试订单簿初始化"""
        orderbook = Orderbook(
            bid_0=99.5,
            ask_0=100.5,
            layer=10,
            prec_price=2,
            prec_amount=3
        )
        
        assert orderbook.bid_0 == 99.5
        assert orderbook.ask_0 == 100.5
        assert orderbook.layer == 10
        assert orderbook.prec_price == 2
        assert orderbook.prec_amount == 3

    def test_init_invalid_layer(self):
        """测试无效层数的初始化"""
        with pytest.raises(AssertionError, match="illegal layer"):
            Orderbook(layer=0)

    def test_prec_to_tick(self):
        """测试精度转换为最小价格单位"""
        assert Orderbook.prec_to_tick(0) == 1.0
        assert Orderbook.prec_to_tick(1) == 0.1
        assert Orderbook.prec_to_tick(2) == 0.01
        assert Orderbook.prec_to_tick(3) == 0.001
        assert Orderbook.prec_to_tick(4) == 0.0001

    def test_num_step(self):
        """测试数值步进处理"""
        # 四舍五入到步进值
        assert Orderbook.num_step(1.2, 0.5) == 1.0  # 舍去
        assert Orderbook.num_step(1.3, 0.5) == 1.5  # 进位
        assert Orderbook.num_step(1.25, 0.5) == 1.5  # 进位（等于一半）
        assert Orderbook.num_step(2.7, 0.5) == 2.5  # 舍去
        assert Orderbook.num_step(2.8, 0.5) == 3.0  # 进位

    def test_sparse_linear(self):
        """测试线性稀疏价格计算"""
        orderbook = Orderbook(layer=5, prec_price=4)
        
        min_price, max_price = orderbook.sparse("linear", 100.0, 5)
        
        tick = Orderbook.prec_to_tick(4)  # 0.0001
        expected_min = round(100.0 - 5 * tick, 4)
        expected_max = round(100.0 + 5 * tick, 4)
        
        assert min_price == expected_min
        assert max_price == expected_max

    def test_sparse_power(self):
        """测试幂函数稀疏价格计算"""
        orderbook = Orderbook(layer=5, prec_price=4)
        
        min_price, max_price = orderbook.sparse("power", 100.0, 0.01)
        
        expected_min = round(100.0 * (1 - 0.01), 4)
        expected_max = round(100.0 * (1 + 0.01), 4)
        
        assert min_price == expected_min
        assert max_price == expected_max

    def test_sparse_power2(self):
        """测试幂函数2稀疏价格计算"""
        orderbook = Orderbook(layer=5, prec_price=4)
        
        min_price, max_price = orderbook.sparse("power2", 100.0, 0.01)
        
        expected_min = round(100.0 * (1 - 0.01), 4)
        expected_max = round(100.0 * (1 + 0.01), 4)
        
        assert min_price == expected_min
        assert max_price == expected_max

    def test_power_bid_direction(self):
        """测试买方向幂函数价格生成"""
        orderbook = Orderbook(bid_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.power("bid", 0.01)
        
        assert len(prices) == 3
        # 买方向价格应该递减
        assert prices[0] == 99.0  # 100 * (1 - 0.01)^1
        assert prices[1] == 98.01  # 100 * (1 - 0.01)^2
        assert prices[2] == 97.03  # 100 * (1 - 0.01)^3

    def test_power_ask_direction(self):
        """测试卖方向幂函数价格生成"""
        orderbook = Orderbook(ask_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.power("ask", 0.01)
        
        assert len(prices) == 3
        # 卖方向价格应该递增
        assert prices[0] == 101.0  # 100 * (1 + 0.01)^1
        assert prices[1] == 102.01  # 100 * (1 + 0.01)^2
        assert prices[2] == 103.03  # 100 * (1 + 0.01)^3

    def test_power_invalid_direction(self):
        """测试无效方向的幂函数"""
        orderbook = Orderbook(layer=3, prec_price=2)
        
        with pytest.raises(AssertionError, match="'direction' not in"):
            orderbook.power("invalid", 0.01)

    def test_power2_bid_direction(self):
        """测试买方向幂函数2价格生成"""
        orderbook = Orderbook(bid_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.power2("bid", 0.01)
        
        assert len(prices) == 3
        # 价格应该使用指数函数递减
        expected_1 = round(100.0 * np.exp(-0.01 * 1), 2)
        expected_2 = round(100.0 * np.exp(-0.01 * 2), 2)
        expected_3 = round(100.0 * np.exp(-0.01 * 3), 2)
        
        assert prices[0] == expected_1
        assert prices[1] == expected_2
        assert prices[2] == expected_3

    def test_power2_ask_direction(self):
        """测试卖方向幂函数2价格生成"""
        orderbook = Orderbook(ask_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.power2("ask", 0.01)
        
        assert len(prices) == 3
        # 价格应该使用指数函数递增
        expected_1 = round(100.0 * np.exp(0.01 * 1), 2)
        expected_2 = round(100.0 * np.exp(0.01 * 2), 2)
        expected_3 = round(100.0 * np.exp(0.01 * 3), 2)
        
        assert prices[0] == expected_1
        assert prices[1] == expected_2
        assert prices[2] == expected_3

    def test_linear_bid_direction(self):
        """测试买方向线性价格生成"""
        orderbook = Orderbook(bid_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.linear("bid", 0.5)
        
        assert len(prices) == 3
        # 买方向价格应该线性递减
        assert prices[0] == 99.5   # 100 - 0.5 * 1
        assert prices[1] == 99.0   # 100 - 0.5 * 2
        assert prices[2] == 98.5   # 100 - 0.5 * 3

    def test_linear_ask_direction(self):
        """测试卖方向线性价格生成"""
        orderbook = Orderbook(ask_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.linear("ask", 0.5)
        
        assert len(prices) == 3
        # 卖方向价格应该线性递增
        assert prices[0] == 100.5  # 100 + 0.5 * 1
        assert prices[1] == 101.0  # 100 + 0.5 * 2
        assert prices[2] == 101.5  # 100 + 0.5 * 3

    def test_linear_with_price_step(self):
        """测试带价格步进的线性生成"""
        orderbook = Orderbook(ask_0=100.0, layer=3, prec_price=2)
        
        prices = orderbook.linear("ask", 0.3, 0.5)  # 使用price_step
        
        assert len(prices) == 3
        # 应该使用price_step而不是price_tick
        assert prices[0] == 100.5  # 100 + 0.5 * 1
        assert prices[1] == 101.0  # 100 + 0.5 * 2
        assert prices[2] == 101.5  # 100 + 0.5 * 3

    def test_normal_distribution(self):
        """测试正态分布数量生成"""
        orderbook = Orderbook(layer=100, prec_price=2)
        
        amounts = orderbook.normal(mean=50, scale=10, size=100)
        
        assert len(amounts) == 100
        assert isinstance(amounts, np.ndarray)
        # 检查分布的大致特性
        assert 30 < np.mean(amounts) < 70  # 均值应该接近50
        assert 5 < np.std(amounts) < 15    # 标准差应该接近10

    def test_uniform_distribution(self):
        """测试均匀分布数量生成"""
        orderbook = Orderbook(layer=100, prec_price=2)
        
        amounts = orderbook.uniform(min=10, max=50, size=100)
        
        assert len(amounts) == 100
        assert isinstance(amounts, np.ndarray)
        assert np.all(amounts >= 10)
        assert np.all(amounts <= 50)

    def test_powera_distribution(self):
        """测试幂函数数量生成"""
        orderbook = Orderbook(layer=5, prec_price=2)
        
        amounts = orderbook.powera(init_price=10, price_percent=0.1)
        
        assert len(amounts) == 5
        # 数量应该指数增长
        for i in range(1, len(amounts)):
            assert amounts[i] > amounts[i-1]

    def test_make_with_linear_price_normal_amount(self):
        """测试使用线性价格和正态分布数量创建订单簿"""
        orderbook = Orderbook(bid_0=100.0, ask_0=101.0, layer=5, prec_price=2, prec_amount=1)
        
        batch_order = orderbook.make(
            direction="bid",
            make_price=orderbook.linear,
            make_amount=orderbook.normal,
            price_tick=0.5,
            price_step=None,
            mean=50,
            scale=10,
            sparse=0.01
        )
        
        assert len(batch_order) == 5
        for order in batch_order:
            assert "price" in order
            assert "amount" in order
            assert "direction" in order
            assert "min_price" in order
            assert "max_price" in order
            assert "order_id" in order
            assert order["direction"] == "bid"

    def test_make_with_power_price_uniform_amount(self):
        """测试使用幂函数价格和均匀分布数量创建订单簿"""
        orderbook = Orderbook(ask_0=101.0, layer=3, prec_price=2, prec_amount=1)
        
        batch_order = orderbook.make(
            direction="ask",
            make_price=orderbook.power,
            make_amount=orderbook.uniform,
            price_percent=0.01,
            min=10,
            max=50,
            sparse=0.01
        )
        
        assert len(batch_order) == 3
        for order in batch_order:
            assert order["direction"] == "ask"
            assert 10 <= order["amount"] <= 50

    def test_make_with_power2_price_powera_amount(self):
        """测试使用幂函数2价格和幂函数数量创建订单簿"""
        orderbook = Orderbook(bid_0=100.0, layer=3, prec_price=2, prec_amount=1)
        
        batch_order = orderbook.make(
            direction="bid",
            make_price=orderbook.power2,
            make_amount=orderbook.powera,
            price_percent=0.01,
            mean=50,
            scale=10,
            sparse=0.01
        )
        
        assert len(batch_order) == 3
        for order in batch_order:
            assert order["direction"] == "bid"

    def test_make_negative_price_handling(self):
        """测试负价格处理"""
        # 设置一个会产生负价格的场景
        orderbook = Orderbook(bid_0=0.5, layer=5, prec_price=2, prec_amount=1)
        
        batch_order = orderbook.make(
            direction="bid",
            make_price=orderbook.linear,
            make_amount=orderbook.normal,
            price_tick=0.2,  # 大步长，可能产生负价格
            price_step=None,
            mean=50,
            scale=10,
            sparse=0.01
        )
        
        # 所有价格都应该大于0
        for order in batch_order:
            assert order["price"] > 0


class TestGetOrderbook:
    """测试获取订单簿函数"""

    def test_get_orderbook_default_params(self):
        """测试使用默认参数获取订单簿"""
        batch_order_bid, batch_order_ask = get_orderbook()
        
        # 验证返回两个列表
        assert isinstance(batch_order_bid, list)
        assert isinstance(batch_order_ask, list)
        assert len(batch_order_bid) == 30  # 默认层数
        assert len(batch_order_ask) == 30

    def test_get_orderbook_with_custom_params(self):
        """测试使用自定义参数获取订单簿"""
        mid_price = 1000.0
        bid_ask_spread = 0.02
        
        batch_order_bid, batch_order_ask = get_orderbook(
            mid_price=mid_price,
            bid_ask_spread=bid_ask_spread
        )
        
        # 验证价格分布
        expected_bid_0 = mid_price - (mid_price * bid_ask_spread) / 2
        expected_ask_0 = mid_price + (mid_price * bid_ask_spread) / 2
        
        # 第一层买单价格应该接近expected_bid_0
        first_bid_price = batch_order_bid[0]["price"]
        assert abs(first_bid_price - expected_bid_0) < 1.0  # 允许一定误差
        
        # 第一层卖单价格应该接近expected_ask_0
        first_ask_price = batch_order_ask[0]["price"]
        assert abs(first_ask_price - expected_ask_0) < 1.0  # 允许一定误差

    def test_get_orderbook_bid_ask_structure(self):
        """测试订单簿买卖方向结构"""
        batch_order_bid, batch_order_ask = get_orderbook(mid_price=100.0)
        
        # 验证买单结构
        for order in batch_order_bid:
            assert order["direction"] == "bid"
            assert "price" in order
            assert "amount" in order
            assert "min_price" in order
            assert "max_price" in order
            assert "order_id" in order
        
        # 验证卖单结构
        for order in batch_order_ask:
            assert order["direction"] == "ask"
            assert "price" in order
            assert "amount" in order
            assert "min_price" in order
            assert "max_price" in order
            assert "order_id" in order

    def test_get_orderbook_price_distribution(self):
        """测试订单簿价格分布"""
        mid_price = 100.0
        batch_order_bid, batch_order_ask = get_orderbook(mid_price=mid_price)
        
        # 验证买单价格递减
        bid_prices = [order["price"] for order in batch_order_bid]
        for i in range(1, len(bid_prices)):
            assert bid_prices[i] <= bid_prices[i-1], "买单价格应该递减"
        
        # 验证卖单价格递增
        ask_prices = [order["price"] for order in batch_order_ask]
        for i in range(1, len(ask_prices)):
            assert ask_prices[i] >= ask_prices[i-1], "卖单价格应该递增"
        
        # 验证所有买单价格都低于中间价
        for price in bid_prices:
            assert price < mid_price
        
        # 验证所有卖单价格都高于中间价
        for price in ask_prices:
            assert price > mid_price

    def test_get_orderbook_amount_distribution(self):
        """测试订单簿数量分布"""
        batch_order_bid, batch_order_ask = get_orderbook(mid_price=100.0)
        
        # 验证数量都为正数
        for order in batch_order_bid + batch_order_ask:
            assert order["amount"] > 0

    def test_get_orderbook_precision(self):
        """测试订单簿精度"""
        batch_order_bid, batch_order_ask = get_orderbook(mid_price=100.0)
        
        # 默认价格精度为6位小数
        for order in batch_order_bid + batch_order_ask:
            price_str = str(order["price"])
            if "." in price_str:
                decimal_places = len(price_str.split(".")[1])
                assert decimal_places <= 6
        
        # 默认数量精度为2位小数
        for order in batch_order_bid + batch_order_ask:
            amount_str = str(order["amount"])
            if "." in amount_str:
                decimal_places = len(amount_str.split(".")[1])
                assert decimal_places <= 2

    def test_get_orderbook_min_max_prices(self):
        """测试订单簿最小最大价格范围"""
        batch_order_bid, batch_order_ask = get_orderbook(mid_price=100.0)
        
        # 验证min_price和max_price的合理性
        for order in batch_order_bid + batch_order_ask:
            assert order["min_price"] <= order["price"] <= order["max_price"]


def test_orderbook_integration():
    """集成测试：模拟完整的订单簿创建流程"""
    # 1. 创建订单簿实例
    orderbook = Orderbook(
        bid_0=99.0,
        ask_0=101.0,
        layer=10,
        prec_price=4,
        prec_amount=2
    )

    # 2. 生成买方订单簿
    bid_orders = orderbook.make(
        direction="bid",
        make_price=orderbook.power2,
        make_amount=orderbook.powera,
        price_percent=0.01,
        mean=50,
        scale=10,
        sparse=0.001
    )

    # 3. 生成卖方订单簿
    ask_orders = orderbook.make(
        direction="ask",
        make_price=orderbook.power2,
        make_amount=orderbook.powera,
        price_percent=0.01,
        mean=50,
        scale=10,
        sparse=0.001
    )

    # 4. 验证结果
    assert len(bid_orders) == 10
    assert len(ask_orders) == 10
    
    # 验证买卖价差
    highest_bid = max(order["price"] for order in bid_orders)
    lowest_ask = min(order["price"] for order in ask_orders)
    assert highest_bid < lowest_ask, "最高买价应该低于最低卖价"

    # 5. 使用便捷函数生成订单簿
    convenience_bid, convenience_ask = get_orderbook(mid_price=100.0, bid_ask_spread=0.02)
    
    assert len(convenience_bid) == 30  # 默认层数
    assert len(convenience_ask) == 30
    
    # 验证价格合理性
    bid_prices = [order["price"] for order in convenience_bid]
    ask_prices = [order["price"] for order in convenience_ask]
    
    assert max(bid_prices) < 100.0 < min(ask_prices)


if __name__ == "__main__":
    # 运行测试
    pytest.main([__file__, "-v"])