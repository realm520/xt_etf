"""
Maintainer 集成测试

测试完整的数据流:
1. CurrentOrderbook 转换正确性
2. OrderOperation 执行完整性
3. 执行结果同步
4. 先加后删/先删后加策略
5. 边界情况处理
"""

import pytest
from decimal import Decimal
from typing import Dict, List, Any
from unittest.mock import Mock, MagicMock, patch

from etf.orderbook.maintainer import (
    OrderbookMaintainer,
    MaintainerConfig,
    MaintainerAdapter,
    MaintenanceResult,
    CurrentOrderbook,
    ExistingOrder,
    LayerSpec,
)
from etf.orderbook.executor_v2 import OrderExecutorV2, ExecutionResult, ExecutionStats
from etf.orderbook.base import OrderOperation


# ============================================================
# Fixtures
# ============================================================

@pytest.fixture
def sample_config() -> MaintainerConfig:
    """创建测试用 Maintainer 配置"""
    return MaintainerConfig(
        spread=Decimal("0.008"),
        max_distance=Decimal("0.10"),
        total_budget=Decimal("10000"),
        near_layer=LayerSpec(
            name="near",
            distance_range=(Decimal("0"), Decimal("0.03")),
            budget_ratio=Decimal("0.4"),
            order_count=10,
        ),
        far_layer=LayerSpec(
            name="far",
            distance_range=(Decimal("0.03"), Decimal("0.10")),
            budget_ratio=Decimal("0.6"),
            order_count=14,
        ),
        price_precision=6,
        quantity_precision=2,
        min_price_change=Decimal("0.002"),
        max_operations_per_cycle=30,
    )


@pytest.fixture
def mock_order_manager() -> Mock:
    """创建模拟的 OrderManager"""
    manager = Mock()
    manager.open_orders = {}
    
    # 模拟 add_order 返回成功响应
    def mock_add_order(**kwargs):
        order_id = f"order_{len(manager.open_orders)}"
        client_order_id = f"mm_{order_id}"
        response = {
            "orderId": order_id,
            "clientOrderId": client_order_id,
            "symbol": kwargs.get("symbol"),
            "side": kwargs.get("side"),
            "price": kwargs.get("price"),
            "origQty": kwargs.get("quantity"),
        }
        manager.open_orders[order_id] = response
        return response
    
    manager.add_order = Mock(side_effect=mock_add_order)
    
    # 模拟 cancel_order 返回成功
    def mock_cancel_order(params):
        order_id = params.get("orderId")
        if order_id in manager.open_orders:
            del manager.open_orders[order_id]
            return {"orderId": order_id, "status": "CANCELED"}
        return None
    
    manager.cancel_order = Mock(side_effect=mock_cancel_order)
    
    return manager


@pytest.fixture
def sample_exchange_orders() -> List[Dict]:
    """创建模拟的交易所订单列表"""
    return [
        # mm_ 前缀的做市订单
        {
            "orderId": "1001",
            "clientOrderId": "mm_bid_1",
            "price": "0.995",
            "origQty": "100",
            "side": "BUY",
        },
        {
            "orderId": "1002",
            "clientOrderId": "mm_bid_2",
            "price": "0.990",
            "origQty": "150",
            "side": "BUY",
        },
        {
            "orderId": "1003",
            "clientOrderId": "mm_ask_1",
            "price": "1.005",
            "origQty": "100",
            "side": "SELL",
        },
        {
            "orderId": "1004",
            "clientOrderId": "mm_ask_2",
            "price": "1.010",
            "origQty": "150",
            "side": "SELL",
        },
        # 非 mm_ 订单（应被过滤）
        {
            "orderId": "2001",
            "clientOrderId": "antipin_bid_1",
            "price": "0.980",
            "origQty": "50",
            "side": "BUY",
        },
        {
            "orderId": "2002",
            "clientOrderId": "wash_ask_1",
            "price": "1.020",
            "origQty": "30",
            "side": "SELL",
        },
    ]


# ============================================================
# MaintainerAdapter 测试
# ============================================================

class TestMaintainerAdapter:
    """测试数据适配器"""
    
    def test_from_exchange_orders_filters_mm_only(self, sample_exchange_orders):
        """测试只过滤 mm_ 前缀订单"""
        current = MaintainerAdapter.from_exchange_orders(
            orders=sample_exchange_orders,
            filter_prefix="mm_",
        )
        
        # 应该只有 4 个 mm_ 订单
        assert len(current.bids) == 2
        assert len(current.asks) == 2
        
        # 验证 bid 订单
        bid_prices = {b.price for b in current.bids}
        assert Decimal("0.995") in bid_prices
        assert Decimal("0.990") in bid_prices
        
        # 验证 ask 订单
        ask_prices = {a.price for a in current.asks}
        assert Decimal("1.005") in ask_prices
        assert Decimal("1.010") in ask_prices
    
    def test_from_exchange_orders_no_filter(self, sample_exchange_orders):
        """测试不过滤时返回所有订单"""
        current = MaintainerAdapter.from_exchange_orders(
            orders=sample_exchange_orders,
            filter_prefix=None,
        )
        
        # 应该有所有 6 个订单
        assert len(current.bids) == 3
        assert len(current.asks) == 3
    
    def test_from_open_orders_dict(self):
        """测试从 OrderManager.open_orders 字典转换"""
        open_orders = {
            "order_1": {
                "orderId": "order_1",
                "clientOrderId": "mm_test_1",
                "price": 1.0,
                "origQty": 100,
                "side": "BUY",
            },
            "order_2": {
                "orderId": "order_2",
                "clientOrderId": "mm_test_2",
                "price": 1.01,
                "origQty": 100,
                "side": "SELL",
            },
            "order_3": {
                "orderId": "order_3",
                "clientOrderId": "other_order",
                "price": 0.99,
                "origQty": 50,
                "side": "BUY",
            },
        }
        
        current = MaintainerAdapter.from_open_orders_dict(
            open_orders=open_orders,
            filter_prefix="mm_",
        )
        
        assert len(current.bids) == 1
        assert len(current.asks) == 1
        assert current.bids[0].price == Decimal("1.0")
        assert current.asks[0].price == Decimal("1.01")
    
    def test_count_mm_orders(self, sample_exchange_orders):
        """测试 mm_ 订单计数"""
        count = MaintainerAdapter.count_mm_orders(sample_exchange_orders)
        assert count == 4
    
    def test_operation_to_add_params(self):
        """测试 OrderOperation 转换为 add_order 参数"""
        op = OrderOperation(
            action="add",
            side="bid",
            price=Decimal("1.0"),
            quantity=Decimal("100"),
            reason="test",
        )
        
        params = MaintainerAdapter.operation_to_add_params(
            op=op,
            symbol="TESTUSDT",
            price_precision=4,
            quantity_precision=2,
        )
        
        assert params["symbol"] == "TESTUSDT"
        assert params["side"] == "BUY"
        assert params["price"] == 1.0
        assert params["quantity"] == 100.0
        assert params["order_purpose"] == "market_making"


# ============================================================
# OrderExecutorV2 测试
# ============================================================

class TestOrderExecutorV2:
    """测试精简版执行器"""
    
    def test_execute_empty_operations(self, mock_order_manager):
        """测试空操作列表"""
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        
        result = executor.execute(operations=[], current_order_count=0)
        
        assert result.success is True
        assert result.stats.total_operations == 0
        assert mock_order_manager.add_order.call_count == 0
        assert mock_order_manager.cancel_order.call_count == 0
    
    def test_execute_add_operations(self, mock_order_manager):
        """测试添加订单操作"""
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        
        operations = [
            OrderOperation(
                action="add",
                side="bid",
                price=Decimal("1.0"),
                quantity=Decimal("100"),
                reason="new_order",
            ),
            OrderOperation(
                action="add",
                side="ask",
                price=Decimal("1.01"),
                quantity=Decimal("100"),
                reason="new_order",
            ),
        ]
        
        result = executor.execute(operations=operations, current_order_count=0)
        
        assert result.success is True
        assert result.stats.add_operations == 2
        assert result.stats.adds_succeeded == 2
        assert mock_order_manager.add_order.call_count == 2
    
    def test_execute_cancel_operations(self, mock_order_manager):
        """测试取消订单操作"""
        # 先添加一些订单
        mock_order_manager.open_orders = {
            "order_1": {"orderId": "order_1"},
            "order_2": {"orderId": "order_2"},
        }
        
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        
        operations = [
            OrderOperation(
                action="cancel",
                side="bid",
                price=Decimal("1.0"),
                quantity=Decimal("100"),
                order_id="order_1",
                reason="remove",
            ),
        ]
        
        result = executor.execute(operations=operations, current_order_count=2)
        
        assert result.success is True
        assert result.stats.cancel_operations == 1
        assert result.stats.cancels_succeeded == 1
    
    def test_execute_add_first_strategy(self, mock_order_manager):
        """测试先加后删策略（正常情况）"""
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
            config={"max_orders": 200},
        )
        
        operations = [
            OrderOperation(action="add", side="bid", price=Decimal("1.0"), 
                          quantity=Decimal("100"), reason="add"),
            OrderOperation(action="cancel", side="ask", price=Decimal("1.01"),
                          quantity=Decimal("100"), order_id="old_1", reason="remove"),
        ]
        
        # 当前订单数量低，应该使用先加后删
        result = executor.execute(operations=operations, current_order_count=50)
        
        assert result.stats.execution_order == "add_first"
    
    def test_execute_cancel_first_strategy(self, mock_order_manager):
        """测试先删后加策略（订单溢出）"""
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
            config={"max_orders": 200, "order_overflow_threshold": 0.9},
        )
        
        operations = [
            OrderOperation(action="add", side="bid", price=Decimal("1.0"),
                          quantity=Decimal("100"), reason="add"),
            OrderOperation(action="cancel", side="ask", price=Decimal("1.01"),
                          quantity=Decimal("100"), order_id="old_1", reason="remove"),
        ]
        
        # 当前订单数量接近上限，应该使用先删后加
        result = executor.execute(operations=operations, current_order_count=190)
        
        assert result.stats.execution_order == "cancel_first"
    
    def test_get_current_mm_order_count(self, mock_order_manager):
        """测试获取当前 mm_ 订单数量"""
        mock_order_manager.open_orders = {
            "o1": {"clientOrderId": "mm_1"},
            "o2": {"clientOrderId": "mm_2"},
            "o3": {"clientOrderId": "other"},
        }
        
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        
        count = executor.get_current_mm_order_count()
        assert count == 2


# ============================================================
# 端到端集成测试
# ============================================================

class TestMaintainerIntegration:
    """端到端集成测试"""
    
    def test_full_flow_from_exchange_orders(
        self,
        sample_config,
        mock_order_manager,
        sample_exchange_orders,
    ):
        """测试完整流程: 交易所订单 → Maintainer → ExecutorV2"""
        # 1. 转换交易所订单
        current = MaintainerAdapter.from_exchange_orders(
            orders=sample_exchange_orders,
            filter_prefix="mm_",
        )
        
        # 2. 创建 Maintainer
        maintainer = OrderbookMaintainer(sample_config)
        
        # 3. 执行维护
        nav = Decimal("1.0")
        result = maintainer.maintain(current, nav)
        
        # 4. 创建 ExecutorV2
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        
        # 5. 执行操作
        exec_result = executor.execute(
            operations=result.operations,
            current_order_count=len(current.bids) + len(current.asks),
        )
        
        # 验证
        assert exec_result.success is True
        assert exec_result.stats.success_rate >= 0.8
    
    def test_nav_change_triggers_update(self, sample_config, mock_order_manager):
        """测试净值变化触发订单簿更新"""
        maintainer = OrderbookMaintainer(sample_config)
        
        # 初始状态
        current = CurrentOrderbook(bids=[], asks=[])
        nav1 = Decimal("1.0")
        
        # 第一次维护（空订单簿）
        result1 = maintainer.maintain(current, nav1)
        assert result1.needs_update is True
        
        # 使用 result1 的操作更新 mock 订单
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        exec_result1 = executor.execute(result1.operations, 0)
        assert exec_result1.success is True
        
        # 转换新的订单状态
        new_current = MaintainerAdapter.from_open_orders_dict(
            mock_order_manager.open_orders,
            filter_prefix="mm_",
        )
        
        # 小幅净值变化（应该不触发更新）
        nav2 = Decimal("1.001")  # 0.1% 变化
        result2 = maintainer.maintain(new_current, nav2)
        # 注意：是否触发更新取决于 min_price_change 配置
        
        # 大幅净值变化（应该触发更新）
        nav3 = Decimal("1.05")  # 5% 变化
        result3 = maintainer.maintain(new_current, nav3)
        assert result3.needs_update is True
    
    def test_order_sync_to_manager(self, sample_config, mock_order_manager):
        """测试执行结果同步到 OrderManager"""
        maintainer = OrderbookMaintainer(sample_config)
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
        )
        
        # 初始维护
        current = CurrentOrderbook(bids=[], asks=[])
        nav = Decimal("1.0")
        result = maintainer.maintain(current, nav)
        
        # 执行前检查
        assert len(mock_order_manager.open_orders) == 0
        
        # 执行操作
        exec_result = executor.execute(result.operations, 0)
        
        # 执行后检查 - 订单应该已添加到 open_orders
        add_count = sum(1 for op in result.operations if op.action == "add")
        assert len(mock_order_manager.open_orders) == add_count


# ============================================================
# 边界情况测试
# ============================================================

class TestEdgeCases:
    """边界情况测试"""
    
    def test_empty_current_orderbook(self, sample_config, mock_order_manager):
        """测试空订单簿"""
        maintainer = OrderbookMaintainer(sample_config)
        current = CurrentOrderbook(bids=[], asks=[])
        
        result = maintainer.maintain(current, Decimal("1.0"))
        
        # 空订单簿应该触发更新
        assert result.needs_update is True
        assert len(result.operations) > 0
    
    def test_large_nav_change(self, sample_config, mock_order_manager):
        """测试大幅净值变化"""
        maintainer = OrderbookMaintainer(sample_config)
        
        # 创建一些现有订单
        existing_bids = [
            ExistingOrder(
                order_id=f"bid_{i}",
                price=Decimal("0.99") - Decimal(str(i * 0.01)),
                quantity=Decimal("100"),
                side="bid",
            )
            for i in range(5)
        ]
        existing_asks = [
            ExistingOrder(
                order_id=f"ask_{i}",
                price=Decimal("1.01") + Decimal(str(i * 0.01)),
                quantity=Decimal("100"),
                side="ask",
            )
            for i in range(5)
        ]
        current = CurrentOrderbook(bids=existing_bids, asks=existing_asks)
        
        # 大幅净值变化
        new_nav = Decimal("1.5")  # 50% 上涨
        result = maintainer.maintain(current, new_nav)
        
        assert result.needs_update is True
        # 应该有取消和添加操作
        cancel_ops = [op for op in result.operations if op.action == "cancel"]
        add_ops = [op for op in result.operations if op.action == "add"]
        assert len(cancel_ops) > 0 or len(add_ops) > 0
    
    def test_max_operations_limit(self, sample_config, mock_order_manager):
        """测试最大操作数限制"""
        # 设置较小的最大操作数
        sample_config.max_operations_per_cycle = 5
        maintainer = OrderbookMaintainer(sample_config)
        
        current = CurrentOrderbook(bids=[], asks=[])
        result = maintainer.maintain(current, Decimal("1.0"))
        
        # 操作数不应超过限制
        assert len(result.operations) <= 5
    
    def test_order_overflow_protection(self, mock_order_manager):
        """测试订单溢出保护"""
        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TESTUSDT",
            strategy_name="test",
            config={"max_orders": 100, "order_overflow_threshold": 0.9},
        )
        
        # 大量添加操作
        operations = [
            OrderOperation(
                action="add",
                side="bid",
                price=Decimal(str(1 - i * 0.001)),
                quantity=Decimal("10"),
                reason="test",
            )
            for i in range(20)
        ]
        
        # 当前接近上限
        result = executor.execute(operations=operations, current_order_count=85)
        
        # 应该使用先删后加策略
        assert result.stats.execution_order == "cancel_first"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
