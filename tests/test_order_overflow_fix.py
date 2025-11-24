"""
测试订单数量溢出修复

验证订单匹配算法的超范围订单清理和数量保护功能
"""

import pytest
from typing import List, Dict, Any
from etf.utils.optimization import optimize_order_matching


def create_order(price: float, quantity: float, side: str = "BUY") -> Dict[str, Any]:
    """创建测试订单"""
    return {
        "price": str(price),
        "origQty": str(quantity),
        "side": side,
        "state": "NEW",
        "orderId": f"order_{price}_{quantity}",
    }


def create_goal_order(
    price: float,
    min_price: float,
    max_price: float,
    amount: float,
    direction: str = "bid"
) -> Dict[str, Any]:
    """创建目标订单"""
    return {
        "price": price,
        "min_price": min_price,
        "max_price": max_price,
        "amount": amount,
        "direction": direction,
        "symbol": "TON3S_USDT",
    }


class TestOrderOverflowFix:
    """测试订单溢出修复功能"""

    def test_out_of_range_orders_cleanup(self):
        """测试超范围订单自动清理"""
        # 当前订单：价格范围 0.95 ~ 1.05（旧订单簿）
        current_orders = [
            create_order(0.95, 10),
            create_order(0.96, 10),
            create_order(0.97, 10),  # 这些订单应该被清理
            create_order(0.98, 10),
            create_order(0.99, 10),
            create_order(1.00, 10),  # 重叠区
            create_order(1.01, 10, "SELL"),  # 重叠区
            create_order(1.02, 10, "SELL"),
            create_order(1.03, 10, "SELL"),
            create_order(1.04, 10, "SELL"),  # 这些订单应该被清理
            create_order(1.05, 10, "SELL"),
        ]

        # 目标订单：价格范围 0.99 ~ 1.03（新订单簿，价格上涨2%）
        goal_orders = [
            create_goal_order(0.99, 0.985, 0.995, 10, "bid"),
            create_goal_order(1.00, 0.995, 1.005, 10, "bid"),
            create_goal_order(1.01, 1.005, 1.015, 10, "ask"),
            create_goal_order(1.02, 1.015, 1.025, 10, "ask"),
            create_goal_order(1.03, 1.025, 1.035, 10, "ask"),
        ]

        # 执行匹配（不启用数量保护，仅测试超范围清理）
        add_orders, cancel_orders = optimize_order_matching(
            current_orders,
            goal_orders,
            max_layer=None  # 不启用数量保护
        )

        # 验证：应该清理超出目标范围的订单
        # 目标范围：0.985 ~ 1.035
        # 应清理：0.95, 0.96, 0.97 (买单) + 1.04, 1.05 (卖单) = 5个
        cancel_prices = {float(o["price"]) for o in cancel_orders}

        assert 0.95 in cancel_prices, "应该清理价格0.95的订单"
        assert 0.96 in cancel_prices, "应该清理价格0.96的订单"
        assert 0.97 in cancel_prices, "应该清理价格0.97的订单"
        assert 1.04 in cancel_prices, "应该清理价格1.04的订单"
        assert 1.05 in cancel_prices, "应该清理价格1.05的订单"

    def test_order_count_limit_protection(self):
        """测试订单数量上限保护"""
        # 创建800个当前订单（超过500档配置）
        current_orders = []
        for i in range(400):
            price = 0.90 + i * 0.0001  # 买单：0.90 ~ 0.94
            current_orders.append(create_order(price, 10))

        for i in range(400):
            price = 1.06 + i * 0.0001  # 卖单：1.06 ~ 1.10
            current_orders.append(create_order(price, 10, "SELL"))

        # 目标订单：500档（买250+卖250）
        goal_orders = []
        for i in range(250):
            price = 0.98 + i * 0.00004  # 买单：0.98 ~ 0.99
            goal_orders.append(
                create_goal_order(price, price - 0.00002, price + 0.00002, 10, "bid")
            )

        for i in range(250):
            price = 1.01 + i * 0.00004  # 卖单：1.01 ~ 1.02
            goal_orders.append(
                create_goal_order(price, price - 0.00002, price + 0.00002, 10, "ask")
            )

        # 执行匹配（启用数量保护：max_layer=500）
        add_orders, cancel_orders = optimize_order_matching(
            current_orders,
            goal_orders,
            max_layer=500,           # 最大500档
            cleanup_threshold=1.5    # 150%阈值（750档触发强制清理）
        )

        # 验证：当前800档 > 500*1.5=750档，应该触发强制清理
        # 应清理至少 800 - 500 = 300 个订单
        assert len(cancel_orders) >= 300, \
            f"应至少清理300个订单，实际清理{len(cancel_orders)}个"

    def test_normal_operation_no_cleanup(self):
        """测试正常情况下不触发清理"""
        # 当前订单：500档（符合配置）
        current_orders = []
        for i in range(250):
            price = 0.99 + i * 0.00004
            current_orders.append(create_order(price, 10))

        for i in range(250):
            price = 1.01 + i * 0.00004
            current_orders.append(create_order(price, 10, "SELL"))

        # 目标订单：相同的500档（价格微调0.0001）
        goal_orders = []
        for i in range(250):
            price = 0.99 + i * 0.00004 + 0.0001  # 微调
            goal_orders.append(
                create_goal_order(price, price - 0.00002, price + 0.00002, 10, "bid")
            )

        for i in range(250):
            price = 1.01 + i * 0.00004 + 0.0001  # 微调
            goal_orders.append(
                create_goal_order(price, price - 0.00002, price + 0.00002, 10, "ask")
            )

        # 执行匹配
        add_orders, cancel_orders = optimize_order_matching(
            current_orders,
            goal_orders,
            max_layer=500,
            cleanup_threshold=1.5
        )

        # 验证：正常情况下，新增≈取消（净增≈0）
        # 允许10%的偏差（由于价格微调）
        net_change = abs(len(add_orders) - len(cancel_orders))
        assert net_change < 50, \
            f"正常情况净变化应<50，实际净变化{net_change}（新增{len(add_orders)}，取消{len(cancel_orders)}）"

    def test_price_range_calculation(self):
        """测试价格范围正确计算"""
        # 目标订单：不同价格档位
        goal_orders = [
            create_goal_order(1.00, 0.995, 1.005, 10, "bid"),
            create_goal_order(1.50, 1.495, 1.505, 10, "ask"),
        ]

        current_orders = [
            create_order(0.90, 10),  # 应清理（< 0.995）
            create_order(1.00, 10),  # 保留（在范围内）
            create_order(1.50, 10, "SELL"),  # 保留（在范围内）
            create_order(2.00, 10, "SELL"),  # 应清理（> 1.505）
        ]

        add_orders, cancel_orders = optimize_order_matching(
            current_orders,
            goal_orders,
            max_layer=None
        )

        cancel_prices = {float(o["price"]) for o in cancel_orders}

        # 全局范围：0.995 ~ 1.505
        assert 0.90 in cancel_prices, "0.90 < 0.995，应被清理"
        assert 2.00 in cancel_prices, "2.00 > 1.505，应被清理"
        assert 1.00 not in cancel_prices, "1.00在范围内，不应被清理"
        assert 1.50 not in cancel_prices, "1.50在范围内，不应被清理"

    def test_empty_current_orders(self):
        """测试当前订单为空的情况"""
        current_orders = []

        goal_orders = [
            create_goal_order(1.00, 0.995, 1.005, 10, "bid"),
            create_goal_order(1.01, 1.005, 1.015, 10, "ask"),
        ]

        add_orders, cancel_orders = optimize_order_matching(
            current_orders,
            goal_orders,
            max_layer=500
        )

        # 验证：应该新增所有目标订单，不取消任何订单
        assert len(add_orders) == 2, "应新增2个订单"
        assert len(cancel_orders) == 0, "不应取消任何订单"

    def test_ton3s_real_scenario(self):
        """测试ton3s真实场景：700档累积到500档"""
        # 模拟真实场景：当前700档订单
        current_orders = []

        # 旧订单簿（基于净值1.10）
        for i in range(350):
            price = 1.05 + i * 0.0001  # 买单
            current_orders.append(create_order(price, 10))

        for i in range(350):
            price = 1.16 + i * 0.0001  # 卖单
            current_orders.append(create_order(price, 10, "SELL"))

        # 新订单簿（基于净值1.12，上涨约1.8%）
        goal_orders = []
        for i in range(250):
            price = 1.07 + i * 0.00008  # 买250档
            goal_orders.append(
                create_goal_order(price, price - 0.00004, price + 0.00004, 10, "bid")
            )

        for i in range(250):
            price = 1.18 + i * 0.00008  # 卖250档
            goal_orders.append(
                create_goal_order(price, price - 0.00004, price + 0.00004, 10, "ask")
            )

        # 执行匹配
        add_orders, cancel_orders = optimize_order_matching(
            current_orders,
            goal_orders,
            max_layer=500,
            cleanup_threshold=1.5
        )

        # 验证：
        # 1. 应清理大量超范围订单（700->500，至少清理200个）
        assert len(cancel_orders) >= 200, \
            f"700档->500档，应至少清理200个订单，实际{len(cancel_orders)}个"

        # 2. 清理后订单数应接近500档
        final_count = len(current_orders) - len(cancel_orders) + len(add_orders)
        assert 450 <= final_count <= 550, \
            f"最终订单数应在450-550之间，实际{final_count}档"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
