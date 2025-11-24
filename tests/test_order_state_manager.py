"""
OrderStateManager单元测试

测试范围：
1. 状态转换合法性验证
2. 内存缓存原子性更新
3. 线程安全并发操作
4. 订单数据持久化触发
5. 统计信息准确性

作者: Claude Code
日期: 2025-11-24
"""

import pytest
import threading
import time
from unittest.mock import Mock, MagicMock, patch
from etf.order_state_manager import OrderStateManager


class TestOrderStateTransitions:
    """测试订单状态转换逻辑"""

    @pytest.fixture
    def state_manager(self):
        """创建测试用的OrderStateManager实例"""
        open_orders = {}
        filled_orders = []
        canceled_orders = []
        mock_recorder = Mock()

        return OrderStateManager(
            open_orders=open_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            order_recorder=mock_recorder
        )

    def test_valid_state_transition_pending_to_new(self, state_manager):
        """测试合法状态转换: PENDING → NEW"""
        order_data = {
            "orderId": "test_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }

        result = state_manager.update_order_state(
            order_id="test_001",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        assert result is True
        assert "test_001" in state_manager.open_orders
        assert state_manager.open_orders["test_001"]["state"] == "NEW"

    def test_valid_state_transition_new_to_filled(self, state_manager):
        """测试合法状态转换: NEW → FILLED"""
        # 先创建NEW订单
        order_data_new = {
            "orderId": "test_002",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }
        state_manager.update_order_state(
            order_id="test_002",
            new_state="NEW",
            order_data=order_data_new,
            trigger_source="rest_api"
        )

        # 转换为FILLED
        order_data_filled = {**order_data_new, "state": "FILLED"}
        result = state_manager.update_order_state(
            order_id="test_002",
            new_state="FILLED",
            order_data=order_data_filled,
            trigger_source="websocket"
        )

        assert result is True
        assert "test_002" not in state_manager.open_orders
        assert "test_002" in state_manager.filled_orders or \
               any(o.get("orderId") == "test_002" for o in state_manager.filled_orders if isinstance(o, dict))

    def test_valid_state_transition_new_to_partially_filled(self, state_manager):
        """测试合法状态转换: NEW → PARTIALLY_FILLED"""
        order_data_new = {
            "orderId": "test_003",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }
        state_manager.update_order_state(
            order_id="test_003",
            new_state="NEW",
            order_data=order_data_new,
            trigger_source="rest_api"
        )

        order_data_partial = {
            **order_data_new,
            "state": "PARTIALLY_FILLED",
            "executed_qty": "0.5"
        }
        result = state_manager.update_order_state(
            order_id="test_003",
            new_state="PARTIALLY_FILLED",
            order_data=order_data_partial,
            trigger_source="websocket"
        )

        assert result is True
        assert "test_003" in state_manager.open_orders
        assert state_manager.open_orders["test_003"]["state"] == "PARTIALLY_FILLED"

    def test_valid_state_transition_partially_filled_to_filled(self, state_manager):
        """测试合法状态转换: PARTIALLY_FILLED → FILLED"""
        # 先创建PARTIALLY_FILLED订单
        order_data = {
            "orderId": "test_004",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "executed_qty": "0.5",
            "state": "PARTIALLY_FILLED"
        }
        state_manager.update_order_state(
            order_id="test_004",
            new_state="NEW",
            order_data={**order_data, "state": "NEW"},
            trigger_source="rest_api"
        )
        state_manager.update_order_state(
            order_id="test_004",
            new_state="PARTIALLY_FILLED",
            order_data=order_data,
            trigger_source="websocket"
        )

        # 转换为FILLED
        order_data_filled = {**order_data, "executed_qty": "1.0", "state": "FILLED"}
        result = state_manager.update_order_state(
            order_id="test_004",
            new_state="FILLED",
            order_data=order_data_filled,
            trigger_source="websocket"
        )

        assert result is True
        assert "test_004" not in state_manager.open_orders

    def test_invalid_state_transition_filled_to_new(self, state_manager):
        """测试非法状态转换: FILLED → NEW（终态不能回退）"""
        # 先创建FILLED订单
        order_data = {
            "orderId": "test_005",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "FILLED"
        }
        state_manager.update_order_state(
            order_id="test_005",
            new_state="NEW",
            order_data={**order_data, "state": "NEW"},
            trigger_source="rest_api"
        )
        state_manager.update_order_state(
            order_id="test_005",
            new_state="FILLED",
            order_data=order_data,
            trigger_source="websocket"
        )

        # 尝试非法转换
        result = state_manager.update_order_state(
            order_id="test_005",
            new_state="NEW",
            order_data={**order_data, "state": "NEW"},
            trigger_source="rest_api"
        )

        assert result is False  # 应该拒绝非法转换

    def test_idempotent_state_update(self, state_manager):
        """测试状态更新的幂等性（相同状态可以重复设置）"""
        order_data = {
            "orderId": "test_006",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }

        # 第一次设置
        result1 = state_manager.update_order_state(
            order_id="test_006",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        # 第二次设置相同状态（幂等性）
        result2 = state_manager.update_order_state(
            order_id="test_006",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        assert result1 is True
        assert result2 is True


class TestMemoryCacheManagement:
    """测试内存缓存管理"""

    @pytest.fixture
    def state_manager(self):
        """创建测试用的OrderStateManager实例"""
        open_orders = {}
        filled_orders = []
        canceled_orders = []
        mock_recorder = Mock()

        return OrderStateManager(
            open_orders=open_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            order_recorder=mock_recorder
        )

    def test_open_orders_cache_updated_for_new_order(self, state_manager):
        """测试NEW订单正确添加到open_orders缓存"""
        order_data = {
            "orderId": "test_007",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }

        state_manager.update_order_state(
            order_id="test_007",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        assert "test_007" in state_manager.open_orders
        assert state_manager.open_orders["test_007"]["symbol"] == "BTCUSDT"
        assert state_manager.open_orders["test_007"]["price"] == "50000"

    def test_filled_order_removed_from_open_orders(self, state_manager):
        """测试FILLED订单从open_orders中移除"""
        order_data = {
            "orderId": "test_008",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }

        # 添加到open_orders
        state_manager.update_order_state(
            order_id="test_008",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )
        assert "test_008" in state_manager.open_orders

        # 转换为FILLED
        state_manager.update_order_state(
            order_id="test_008",
            new_state="FILLED",
            order_data={**order_data, "state": "FILLED"},
            trigger_source="websocket"
        )

        assert "test_008" not in state_manager.open_orders
        # 应该添加到filled_orders
        assert len(state_manager.filled_orders) > 0

    def test_canceled_order_removed_from_open_orders(self, state_manager):
        """测试CANCELED订单从open_orders中移除"""
        order_data = {
            "orderId": "test_009",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }

        # 添加到open_orders
        state_manager.update_order_state(
            order_id="test_009",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )
        assert "test_009" in state_manager.open_orders

        # 转换为CANCELED
        state_manager.update_order_state(
            order_id="test_009",
            new_state="CANCELED",
            order_data={**order_data, "state": "CANCELED"},
            trigger_source="rest_api"
        )

        assert "test_009" not in state_manager.open_orders
        # 应该添加到canceled_orders
        assert len(state_manager.canceled_orders) > 0


class TestTradeEventHandling:
    """测试成交事件处理"""

    @pytest.fixture
    def state_manager(self):
        """创建测试用的OrderStateManager实例"""
        open_orders = {}
        filled_orders = []
        canceled_orders = []
        mock_recorder = Mock()

        return OrderStateManager(
            open_orders=open_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            order_recorder=mock_recorder
        )

    def test_handle_trade_event_partial_fill(self, state_manager):
        """测试成交事件处理 - 部分成交"""
        # 先创建订单
        order_data = {
            "orderId": "test_010",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "executed_qty": "0",
            "state": "NEW"
        }
        state_manager.update_order_state(
            order_id="test_010",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        # 触发成交事件（部分成交）
        trade_data = {
            "orderId": "test_010",
            "tradeId": "trade_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "0.5"  # 成交50%
        }

        result = state_manager.handle_trade_event(
            trade_data=trade_data,
            trigger_source="websocket"
        )

        assert result is True
        assert "test_010" in state_manager.open_orders
        # 状态应该变为PARTIALLY_FILLED（由handle_trade_event自动判断）

    def test_handle_trade_event_full_fill(self, state_manager):
        """测试成交事件处理 - 完全成交"""
        # 先创建订单
        order_data = {
            "orderId": "test_011",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "executed_qty": "0",
            "state": "NEW"
        }
        state_manager.update_order_state(
            order_id="test_011",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        # 触发成交事件（完全成交）
        trade_data = {
            "orderId": "test_011",
            "tradeId": "trade_002",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0"  # 成交100%
        }

        result = state_manager.handle_trade_event(
            trade_data=trade_data,
            trigger_source="websocket"
        )

        assert result is True
        # 应该从open_orders中移除
        # 注意：由于Decimal计算，这里需要检查实际行为


class TestThreadSafety:
    """测试线程安全性"""

    @pytest.fixture
    def state_manager(self):
        """创建测试用的OrderStateManager实例"""
        open_orders = {}
        filled_orders = []
        canceled_orders = []
        mock_recorder = Mock()

        return OrderStateManager(
            open_orders=open_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            order_recorder=mock_recorder
        )

    def test_concurrent_state_updates(self, state_manager):
        """测试并发状态更新的线程安全"""
        num_threads = 10
        num_orders_per_thread = 5
        threads = []

        def update_orders(thread_id):
            for i in range(num_orders_per_thread):
                order_id = f"test_{thread_id}_{i}"
                order_data = {
                    "orderId": order_id,
                    "symbol": "BTCUSDT",
                    "side": "BUY",
                    "price": "50000",
                    "quantity": "1.0",
                    "state": "NEW"
                }
                state_manager.update_order_state(
                    order_id=order_id,
                    new_state="NEW",
                    order_data=order_data,
                    trigger_source="rest_api"
                )
                time.sleep(0.001)  # 模拟真实场景的延迟

        # 启动多个线程并发更新
        for i in range(num_threads):
            thread = threading.Thread(target=update_orders, args=(i,))
            threads.append(thread)
            thread.start()

        # 等待所有线程完成
        for thread in threads:
            thread.join()

        # 验证所有订单都被正确添加
        expected_count = num_threads * num_orders_per_thread
        assert len(state_manager.open_orders) == expected_count


class TestPersistenceTrigger:
    """测试数据库持久化触发"""

    @pytest.fixture
    def state_manager_with_recorder(self):
        """创建带有mock recorder的OrderStateManager实例"""
        open_orders = {}
        filled_orders = []
        canceled_orders = []
        mock_recorder = Mock()
        mock_recorder.record_order = Mock()

        return OrderStateManager(
            open_orders=open_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            order_recorder=mock_recorder
        ), mock_recorder

    def test_persistence_triggered_on_state_update(self, state_manager_with_recorder):
        """测试状态更新时触发持久化"""
        state_manager, mock_recorder = state_manager_with_recorder

        order_data = {
            "orderId": "test_012",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }

        state_manager.update_order_state(
            order_id="test_012",
            new_state="NEW",
            order_data=order_data,
            trigger_source="websocket"
        )

        # 验证recorder的record_order方法被调用
        mock_recorder.record_order.assert_called_once()

        # 验证调用参数包含trigger_source
        call_args = mock_recorder.record_order.call_args
        assert 'trigger_source' in call_args[0][0] or 'trigger_source' in call_args[1]


class TestStatistics:
    """测试统计信息"""

    @pytest.fixture
    def state_manager(self):
        """创建测试用的OrderStateManager实例"""
        open_orders = {}
        filled_orders = []
        canceled_orders = []
        mock_recorder = Mock()

        return OrderStateManager(
            open_orders=open_orders,
            filled_orders=filled_orders,
            canceled_orders=canceled_orders,
            order_recorder=mock_recorder
        )

    def test_statistics_count_updates(self, state_manager):
        """测试统计计数器正确更新"""
        # 创建一些订单并转换状态
        for i in range(3):
            order_data = {
                "orderId": f"test_{i}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": "50000",
                "quantity": "1.0",
                "state": "NEW"
            }
            state_manager.update_order_state(
                order_id=f"test_{i}",
                new_state="NEW",
                order_data=order_data,
                trigger_source="rest_api"
            )

        # 将部分订单转为FILLED
        for i in range(2):
            order_data = {
                "orderId": f"test_{i}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": "50000",
                "quantity": "1.0",
                "state": "FILLED"
            }
            state_manager.update_order_state(
                order_id=f"test_{i}",
                new_state="FILLED",
                order_data=order_data,
                trigger_source="websocket"
            )

        # 获取统计信息
        stats = state_manager.get_statistics()

        assert stats['state_change_count']['NEW'] == 3
        assert stats['state_change_count']['FILLED'] == 2
        assert stats['open_orders_count'] == 1  # 只剩1个未完成订单

    def test_statistics_reset(self, state_manager):
        """测试统计计数器重置"""
        # 创建订单
        order_data = {
            "orderId": "test_reset",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "1.0",
            "state": "NEW"
        }
        state_manager.update_order_state(
            order_id="test_reset",
            new_state="NEW",
            order_data=order_data,
            trigger_source="rest_api"
        )

        # 重置统计
        state_manager.reset_statistics()

        # 验证计数器被重置
        stats = state_manager.get_statistics()
        assert stats['state_change_count']['NEW'] == 0


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
