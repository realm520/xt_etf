"""
买卖差价验证和修复功能测试（严格模式）

规则：实际差价必须≤目标差价
- 实际买一 >= 目标买一
- 实际卖一 <= 目标卖一
- 不满足条件立即修复

测试：
1. 差价计算 (_get_actual_spread_from_orders)
2. 差价验证 (verify_and_repair_spread)
3. 差价修复 (_repair_spread)
4. 集成测试
"""

import pytest
from unittest.mock import Mock, MagicMock, patch
from typing import List, Dict, Any

from etf.orderbook.executor import OrderExecutor, ExecutionSummary


class MockOrderManager:
    """模拟OrderManager"""
    
    def __init__(self):
        self.client = MockClient()
        self.symbol_config_manager = MockSymbolConfigManager()
        self._temp_id_counter = 0
    
    def create_temp_id(self) -> str:
        self._temp_id_counter += 1
        return f"test_{self._temp_id_counter}"


class MockClient:
    """模拟交易所客户端"""
    
    def __init__(self):
        self._orders: List[Dict[str, Any]] = []
        self._batch_order_result: List[Dict] = None  # None表示使用默认行为
        self._batch_order_result_set = False  # 标记是否设置过结果
    
    def set_orders(self, orders: List[Dict[str, Any]]):
        """设置当前订单（测试用）"""
        self._orders = orders
    
    def set_batch_order_result(self, result: List[Dict]):
        """设置批量下单结果（测试用）
        
        传入空列表[]表示下单失败（没有成功的订单）
        """
        self._batch_order_result = result
        self._batch_order_result_set = True
    
    def get_open_orders(self, symbol: str = None) -> List[Dict[str, Any]]:
        """获取当前订单"""
        return self._orders
    
    def batch_order(self, orders: List[Dict]) -> List[Dict]:
        """批量下单"""
        # 如果显式设置了结果（包括空列表），使用设置的结果
        if self._batch_order_result_set:
            return self._batch_order_result
        # 默认返回成功结果
        return [{"orderId": f"order_{i}"} for i in range(len(orders))]


class MockSymbolConfigManager:
    """模拟Symbol配置管理器"""
    
    def get_price_precision(self, symbol: str) -> int:
        return 6
    
    def get_quantity_precision(self, symbol: str) -> int:
        return 4


def create_order(
    side: str,
    price: float,
    quantity: float = 100.0,
    client_order_id: str = None
) -> Dict[str, Any]:
    """创建订单字典"""
    return {
        "side": side,
        "price": price,
        "quantity": quantity,
        "orderId": f"order_{price}_{side}",
        "clientOrderId": client_order_id or f"mm_{price}",
    }


class TestGetActualSpreadFromOrders:
    """测试 _get_actual_spread_from_orders 方法"""
    
    def setup_method(self):
        """每个测试前初始化"""
        self.order_manager = MockOrderManager()
        self.executor = OrderExecutor(
            order_manager=self.order_manager,
            symbol="TEST_USDT",
            strategy_name="test_strategy",
        )
    
    def test_normal_spread_calculation(self):
        """测试正常差价计算"""
        orders = [
            create_order("BUY", 1.0000),
            create_order("BUY", 0.9990),
            create_order("BUY", 0.9980),
            create_order("SELL", 1.0010),
            create_order("SELL", 1.0020),
            create_order("SELL", 1.0030),
        ]
        
        best_bid, best_ask, spread_ratio = self.executor._get_actual_spread_from_orders(orders)
        
        assert best_bid == 1.0000  # 最高买价
        assert best_ask == 1.0010  # 最低卖价
        assert abs(spread_ratio - 0.001) < 0.0001  # 0.1% 差价
    
    def test_empty_orders(self):
        """测试空订单列表"""
        orders = []
        
        best_bid, best_ask, spread_ratio = self.executor._get_actual_spread_from_orders(orders)
        
        assert best_bid is None
        assert best_ask is None
        assert spread_ratio is None
    
    def test_only_buy_orders(self):
        """测试只有买单"""
        orders = [
            create_order("BUY", 1.0000),
            create_order("BUY", 0.9990),
        ]
        
        best_bid, best_ask, spread_ratio = self.executor._get_actual_spread_from_orders(orders)
        
        assert best_bid == 1.0000
        assert best_ask is None
        assert spread_ratio is None
    
    def test_only_sell_orders(self):
        """测试只有卖单"""
        orders = [
            create_order("SELL", 1.0010),
            create_order("SELL", 1.0020),
        ]
        
        best_bid, best_ask, spread_ratio = self.executor._get_actual_spread_from_orders(orders)
        
        assert best_bid is None
        assert best_ask == 1.0010
        assert spread_ratio is None
    
    def test_large_spread(self):
        """测试大差价"""
        orders = [
            create_order("BUY", 1.0000),
            create_order("SELL", 1.0500),  # 5% 差价
        ]
        
        best_bid, best_ask, spread_ratio = self.executor._get_actual_spread_from_orders(orders)
        
        assert best_bid == 1.0000
        assert best_ask == 1.0500
        assert abs(spread_ratio - 0.05) < 0.0001  # 5% 差价
    
    def test_invalid_price_ignored(self):
        """测试无效价格被忽略"""
        orders = [
            create_order("BUY", 1.0000),
            create_order("BUY", 0),  # 无效价格
            create_order("BUY", -1.0),  # 无效价格
            create_order("SELL", 1.0010),
        ]
        
        best_bid, best_ask, spread_ratio = self.executor._get_actual_spread_from_orders(orders)
        
        assert best_bid == 1.0000
        assert best_ask == 1.0010


class TestVerifyAndRepairSpread:
    """测试 verify_and_repair_spread 方法（严格模式）"""
    
    def setup_method(self):
        """每个测试前初始化"""
        self.order_manager = MockOrderManager()
        self.executor = OrderExecutor(
            order_manager=self.order_manager,
            symbol="TEST_USDT",
            strategy_name="test_strategy",
        )
    
    def test_spread_exactly_equal_target(self):
        """测试差价等于目标（正常）"""
        # 实际买卖一 == 目标买卖一
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9950),
            create_order("SELL", 1.0050),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is True
        assert result["repaired"] is False
    
    def test_spread_smaller_than_target(self):
        """测试差价小于目标（正常）"""
        # 实际买一更高、卖一更低 → 差价更小
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9960),   # 比目标高
            create_order("SELL", 1.0040),  # 比目标低
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is True
        assert result["repaired"] is False
    
    def test_bid_too_low_triggers_repair(self):
        """测试买一偏低触发修复"""
        # 买一比目标低 → 需要修复
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9900),   # 比目标低
            create_order("SELL", 1.0050),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True
        assert result["repair_orders"] >= 1
    
    def test_ask_too_high_triggers_repair(self):
        """测试卖一偏高触发修复"""
        # 卖一比目标高 → 需要修复
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9950),
            create_order("SELL", 1.0100),  # 比目标高
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True
        assert result["repair_orders"] >= 1
    
    def test_both_sides_abnormal_triggers_repair(self):
        """测试买卖两侧都异常触发修复"""
        # 买一偏低 + 卖一偏高
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9900),   # 比目标低
            create_order("SELL", 1.0100),  # 比目标高
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True
        assert result["repair_orders"] == 2  # 两侧都修复
    
    def test_incomplete_orderbook_triggers_repair(self):
        """测试不完整订单簿触发修复"""
        # 只有买单
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9950),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True
    
    def test_empty_orderbook_triggers_repair(self):
        """测试空订单簿触发修复"""
        self.order_manager.client.set_orders([])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True


class TestRepairSpread:
    """测试 _repair_spread 方法（严格模式）"""
    
    def setup_method(self):
        """每个测试前初始化"""
        self.order_manager = MockOrderManager()
        self.executor = OrderExecutor(
            order_manager=self.order_manager,
            symbol="TEST_USDT",
            strategy_name="test_strategy",
        )
    
    def test_repair_bid_only(self):
        """测试只修复买一"""
        orders = [
            create_order("BUY", 0.9900),  # 实际买一偏低
            create_order("SELL", 1.0050),  # 卖一正常
        ]
        
        result = self.executor._repair_spread(
            current_orders=orders,
            actual_bid=0.9900,
            actual_ask=1.0050,
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["success"] is True
        assert result["orders_added"] == 1
    
    def test_repair_ask_only(self):
        """测试只修复卖一"""
        orders = [
            create_order("BUY", 0.9950),   # 买一正常
            create_order("SELL", 1.0100),  # 实际卖一偏高
        ]
        
        result = self.executor._repair_spread(
            current_orders=orders,
            actual_bid=0.9950,
            actual_ask=1.0100,
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["success"] is True
        assert result["orders_added"] == 1
    
    def test_repair_both_sides(self):
        """测试同时修复买卖"""
        orders = [
            create_order("BUY", 0.9900),   # 买一偏低
            create_order("SELL", 1.0100),  # 卖一偏高
        ]
        
        result = self.executor._repair_spread(
            current_orders=orders,
            actual_bid=0.9900,
            actual_ask=1.0100,
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["success"] is True
        assert result["orders_added"] == 2  # 买卖各一单
    
    def test_no_repair_when_spread_ok(self):
        """测试差价正常时不修复"""
        orders = [
            create_order("BUY", 0.9950),
            create_order("SELL", 1.0050),
        ]
        
        result = self.executor._repair_spread(
            current_orders=orders,
            actual_bid=0.9950,
            actual_ask=1.0050,
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["success"] is True
        assert result["orders_added"] == 0
        assert "无需修复" in result["message"]
    
    def test_batch_order_failure(self):
        """测试批量下单失败"""
        orders = [
            create_order("BUY", 0.9900),
            create_order("SELL", 1.0100),
        ]
        
        # 模拟下单失败
        self.order_manager.client.set_batch_order_result([])
        
        result = self.executor._repair_spread(
            current_orders=orders,
            actual_bid=0.9900,
            actual_ask=1.0100,
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["success"] is False
        assert "失败" in result["message"]


class TestSpreadVerificationIntegration:
    """集成测试：完整流程"""
    
    def setup_method(self):
        """每个测试前初始化"""
        self.order_manager = MockOrderManager()
        self.executor = OrderExecutor(
            order_manager=self.order_manager,
            symbol="TEST_USDT",
            strategy_name="test_strategy",
            max_layer=100,
        )
    
    def test_full_flow_normal(self):
        """测试完整流程 - 正常情况"""
        # 模拟正常差价（等于目标）
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9950, client_order_id="mm_1"),
            create_order("BUY", 0.9940, client_order_id="mm_2"),
            create_order("SELL", 1.0050, client_order_id="mm_3"),
            create_order("SELL", 1.0060, client_order_id="mm_4"),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is True
        assert result["actual_best_bid"] == 0.9950
        assert result["actual_best_ask"] == 1.0050
        assert result["repaired"] is False
    
    def test_full_flow_abnormal_bid(self):
        """测试完整流程 - 买一被吃掉"""
        # 模拟买一被吃掉
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9900, client_order_id="mm_1"),  # 买一偏低
            create_order("BUY", 0.9890, client_order_id="mm_2"),
            create_order("SELL", 1.0050, client_order_id="mm_3"),
            create_order("SELL", 1.0060, client_order_id="mm_4"),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True
        assert result["repair_orders"] >= 1
    
    def test_full_flow_abnormal_ask(self):
        """测试完整流程 - 卖一被吃掉"""
        # 模拟卖一被吃掉
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9950, client_order_id="mm_1"),
            create_order("BUY", 0.9940, client_order_id="mm_2"),
            create_order("SELL", 1.0100, client_order_id="mm_3"),  # 卖一偏高
            create_order("SELL", 1.0110, client_order_id="mm_4"),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is False
        assert result["repaired"] is True
        assert result["repair_orders"] >= 1


class TestEdgeCases:
    """边界情况测试"""
    
    def setup_method(self):
        """每个测试前初始化"""
        self.order_manager = MockOrderManager()
        self.executor = OrderExecutor(
            order_manager=self.order_manager,
            symbol="TEST_USDT",
            strategy_name="test_strategy",
        )
    
    def test_very_small_prices(self):
        """测试小数价格"""
        self.order_manager.client.set_orders([
            create_order("BUY", 0.000995),
            create_order("SELL", 0.001005),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.000995,
            target_best_sell=0.001005,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is True
    
    def test_large_prices(self):
        """测试大数价格"""
        self.order_manager.client.set_orders([
            create_order("BUY", 50000.00),
            create_order("SELL", 50050.00),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=50000.00,
            target_best_sell=50050.00,
        )
        
        assert result["checked"] is True
        assert result["spread_ok"] is True
    
    def test_api_error_handling(self):
        """测试API错误处理"""
        # 模拟API错误
        def raise_error(*args, **kwargs):
            raise Exception("API Error")
        
        self.order_manager.client.get_open_orders = raise_error
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        assert result["checked"] is False
        assert "获取订单失败" in result["message"]
    
    def test_tiny_deviation_still_repairs(self):
        """测试微小偏差也会修复（严格模式）"""
        # 买一比目标低 0.0001
        self.order_manager.client.set_orders([
            create_order("BUY", 0.9949),   # 微小偏差
            create_order("SELL", 1.0050),
        ])
        
        result = self.executor.verify_and_repair_spread(
            target_best_buy=0.9950,
            target_best_sell=1.0050,
        )
        
        # 严格模式：任何偏差都修复
        assert result["spread_ok"] is False
        assert result["repaired"] is True
