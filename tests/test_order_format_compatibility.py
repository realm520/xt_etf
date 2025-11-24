"""
测试订单格式兼容性

验证 OrderbookFactory 生成的订单格式与 optimize_order_matching 期望的格式兼容
"""

from decimal import Decimal
from etf.orderbook.base import OrderLevel, OrderbookSnapshot
from etf.utils.optimization import optimize_order_matching


class TestOrderFormatCompatibility:
    """订单格式兼容性测试"""

    def test_order_format_has_required_fields(self):
        """测试订单格式包含所有必需字段"""
        # 模拟 OrderLevel
        level = OrderLevel(
            price=Decimal("1.5"),
            quantity=Decimal("100.0"),
            value=Decimal("150.0"),
            side="bid"
        )

        # 模拟 market_making.py 中的转换逻辑
        price_precision = 6
        price_tolerance = 10 ** (-price_precision)

        order = {
            "price": float(level.price),
            "quantity": float(level.quantity),
            "amount": float(level.quantity),
            "direction": "bid",
            "min_price": float(level.price) - price_tolerance,
            "max_price": float(level.price) + price_tolerance,
        }

        # 验证所有必需字段都存在
        required_fields = ['price', 'quantity', 'amount', 'direction', 'min_price', 'max_price']
        for field in required_fields:
            assert field in order, f"缺少必需字段: {field}"

        # 验证字段类型
        assert isinstance(order['price'], float)
        assert isinstance(order['quantity'], float)
        assert isinstance(order['amount'], float)
        assert isinstance(order['direction'], str)
        assert isinstance(order['min_price'], float)
        assert isinstance(order['max_price'], float)

        # 验证价格范围合理性
        assert order['min_price'] < order['price']
        assert order['max_price'] > order['price']
        assert order['amount'] == order['quantity']

    def test_price_tolerance_calculation(self):
        """测试价格容差计算的正确性"""
        test_cases = [
            (6, 1e-6),   # 6位精度
            (4, 1e-4),   # 4位精度
            (2, 1e-2),   # 2位精度
            (8, 1e-8),   # 8位精度
        ]

        for precision, expected_tolerance in test_cases:
            tolerance = 10 ** (-precision)
            assert tolerance == expected_tolerance, \
                f"精度 {precision} 的容差应该是 {expected_tolerance}，实际是 {tolerance}"

    def test_optimize_order_matching_with_new_format(self):
        """测试 optimize_order_matching 能处理新格式订单"""
        # 准备测试数据
        current_orders = []

        # 目标订单（新格式）
        goal_orders = [
            {
                "price": 1.5,
                "quantity": 100.0,
                "amount": 100.0,
                "direction": "bid",
                "min_price": 1.499999,
                "max_price": 1.500001,
                "symbol": "test_usdt",
            },
            {
                "price": 1.51,
                "quantity": 100.0,
                "amount": 100.0,
                "direction": "ask",
                "min_price": 1.509999,
                "max_price": 1.510001,
                "symbol": "test_usdt",
            }
        ]

        # 调用优化匹配算法（不应该抛出 KeyError）
        try:
            add_orders, cancel_orders = optimize_order_matching(
                current_orders,
                goal_orders,
                max_layer=500
            )
            # 验证返回结果
            assert isinstance(add_orders, list)
            assert isinstance(cancel_orders, list)
            # 应该添加2个新订单（因为当前没有订单）
            assert len(add_orders) == 2
            assert len(cancel_orders) == 0
        except KeyError as e:
            raise AssertionError(f"optimize_order_matching 抛出 KeyError: {e}")

    def test_batch_order_conversion(self):
        """测试批量订单转换逻辑"""
        # 模拟 OrderLevel 列表
        bids = [
            OrderLevel(Decimal("1.5"), Decimal("100.0"), Decimal("150.0"), "bid"),
            OrderLevel(Decimal("1.49"), Decimal("100.0"), Decimal("149.0"), "bid"),
        ]
        asks = [
            OrderLevel(Decimal("1.51"), Decimal("100.0"), Decimal("151.0"), "ask"),
            OrderLevel(Decimal("1.52"), Decimal("100.0"), Decimal("152.0"), "ask"),
        ]

        price_precision = 6
        price_tolerance = 10 ** (-price_precision)

        # 转换为兼容格式
        batch_order_bid = [
            {
                "price": float(level.price),
                "quantity": float(level.quantity),
                "amount": float(level.quantity),
                "direction": "bid",
                "min_price": float(level.price) - price_tolerance,
                "max_price": float(level.price) + price_tolerance,
            }
            for level in bids
        ]

        batch_order_ask = [
            {
                "price": float(level.price),
                "quantity": float(level.quantity),
                "amount": float(level.quantity),
                "direction": "ask",
                "min_price": float(level.price) - price_tolerance,
                "max_price": float(level.price) + price_tolerance,
            }
            for level in asks
        ]

        # 验证转换结果
        assert len(batch_order_bid) == 2
        assert len(batch_order_ask) == 2

        # 验证第一个买单
        bid1 = batch_order_bid[0]
        assert bid1['price'] == 1.5
        assert bid1['quantity'] == 100.0
        assert bid1['amount'] == 100.0
        assert bid1['direction'] == 'bid'
        assert abs(bid1['min_price'] - 1.499999) < 1e-10
        assert abs(bid1['max_price'] - 1.500001) < 1e-10

        # 验证第一个卖单
        ask1 = batch_order_ask[0]
        assert ask1['price'] == 1.51
        assert ask1['quantity'] == 100.0
        assert ask1['amount'] == 100.0
        assert ask1['direction'] == 'ask'
        assert abs(ask1['min_price'] - 1.509999) < 1e-10
        assert abs(ask1['max_price'] - 1.510001) < 1e-10

    def test_edge_cases(self):
        """测试边界情况"""
        # 测试非常小的价格
        level = OrderLevel(Decimal("0.000001"), Decimal("1000000.0"), Decimal("1.0"), "bid")
        price_precision = 8
        price_tolerance = 10 ** (-price_precision)

        order = {
            "price": float(level.price),
            "quantity": float(level.quantity),
            "amount": float(level.quantity),
            "direction": "bid",
            "min_price": float(level.price) - price_tolerance,
            "max_price": float(level.price) + price_tolerance,
        }

        assert order['min_price'] >= 0, "价格范围下界不应该为负数"
        assert order['max_price'] > order['min_price'], "价格范围上界应该大于下界"

    def test_different_precisions(self):
        """测试不同精度下的订单格式"""
        test_precisions = [2, 4, 6, 8]
        base_price = 100.0

        for precision in test_precisions:
            level = OrderLevel(
                Decimal(str(base_price)),
                Decimal("10.0"),
                Decimal("1000.0"),
                "bid"
            )

            price_tolerance = 10 ** (-precision)

            order = {
                "price": float(level.price),
                "quantity": float(level.quantity),
                "amount": float(level.quantity),
                "direction": "bid",
                "min_price": float(level.price) - price_tolerance,
                "max_price": float(level.price) + price_tolerance,
            }

            # 验证价格范围与精度一致
            expected_range = 2 * price_tolerance
            actual_range = order['max_price'] - order['min_price']
            assert abs(actual_range - expected_range) < 1e-12, \
                f"精度 {precision} 时价格范围不正确: 期望 {expected_range}, 实际 {actual_range}"
