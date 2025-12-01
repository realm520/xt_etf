"""
订单簿管理模块单元测试

测试 OrderManager 的新增订单簿管理功能：
- Phase 1: 数据结构（类型索引、价格索引、线程锁）
- Phase 2: 内部操作方法（_add_to_orderbook, _remove_from_orderbook, _update_orderbook）
- Phase 4: 查询接口（get_orders_by_type, get_best_bid/ask, get_orderbook_snapshot）
"""

import pytest
import time
import threading
from unittest.mock import MagicMock, patch


class MockClient:
    """模拟交易所客户端"""
    def __init__(self):
        self.orders = {}
        self.order_counter = 0

    def order(self, **kwargs):
        self.order_counter += 1
        return {
            "orderId": f"ORDER_{self.order_counter}",
            "symbol": kwargs.get("symbol"),
            "side": kwargs.get("side"),
            "price": kwargs.get("price"),
            "quantity": kwargs.get("quantity"),
            "state": "NEW",
        }

    def cancel_order(self, order_id):
        return {"orderId": order_id, "state": "CANCELED"}

    def get_open_orders(self, symbol=None):
        return []


@pytest.fixture
def order_manager():
    """创建测试用的 OrderManager 实例"""
    # 使用 patch 跳过复杂的初始化
    # Phase 5.1: 移除 OrderStateManager patch（已废弃）
    with patch('etf.order_manager.OrderWebSocketClient'), \
         patch('etf.order_manager.redis.Redis'), \
         patch('etf.order_manager.ORDER_RECORDER_AVAILABLE', False):
        from etf.order_manager import OrderManager
        client = MockClient()
        om = OrderManager(client, strategy_name="test", tier=100)
        return om


class TestParseOrderType:
    """测试 _parse_order_type 方法"""

    def test_parse_mm_order(self, order_manager):
        """测试解析做市订单类型"""
        assert order_manager._parse_order_type("mm_12345") == "mm"

    def test_parse_wash_order(self, order_manager):
        """测试解析洗盘订单类型"""
        assert order_manager._parse_order_type("wash_abc") == "wash"

    def test_parse_hedge_order(self, order_manager):
        """测试解析对冲订单类型"""
        assert order_manager._parse_order_type("hedge_xyz") == "hedge"

    def test_parse_antipin_order(self, order_manager):
        """测试解析反针订单类型"""
        assert order_manager._parse_order_type("antipin_001") == "antipin"

    def test_parse_rebal_order(self, order_manager):
        """测试解析再平衡订单类型"""
        assert order_manager._parse_order_type("rebal_002") == "rebal"

    def test_parse_layer_adjust_order(self, order_manager):
        """测试解析分层调整订单类型"""
        assert order_manager._parse_order_type("layer_adjust_003") == "layer_adjust"

    def test_parse_unknown_order(self, order_manager):
        """测试解析未知订单类型"""
        assert order_manager._parse_order_type("random_id") == "unknown"
        assert order_manager._parse_order_type("") == "unknown"
        assert order_manager._parse_order_type(None) == "unknown"


class TestAddToOrderbook:
    """测试 _add_to_orderbook 方法"""

    def test_add_buy_order(self, order_manager):
        """测试添加买单"""
        order = {
            "orderId": "ORD001",
            "clientOrderId": "mm_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
            "state": "NEW",
        }
        order_manager._add_to_orderbook(order)

        # 验证主存储
        assert "ORD001" in order_manager.open_orders
        assert order_manager.open_orders["ORD001"]["price"] == 50000.0

        # 验证类型索引
        assert "ORD001" in order_manager._orders_by_type["mm"]

        # 验证价格索引
        assert 50000.0 in order_manager._bids
        assert "ORD001" in order_manager._bids[50000.0]

    def test_add_sell_order(self, order_manager):
        """测试添加卖单"""
        order = {
            "orderId": "ORD002",
            "clientOrderId": "wash_002",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "price": 51000.0,
            "quantity": 0.2,
            "state": "NEW",
        }
        order_manager._add_to_orderbook(order)

        # 验证价格索引
        assert 51000.0 in order_manager._asks
        assert "ORD002" in order_manager._asks[51000.0]
        assert "ORD002" in order_manager._orders_by_type["wash"]

    def test_add_multiple_orders_same_price(self, order_manager):
        """测试同价格添加多个订单"""
        for i in range(3):
            order = {
                "orderId": f"ORD{i}",
                "clientOrderId": f"mm_{i}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": 50000.0,
                "quantity": 0.1,
            }
            order_manager._add_to_orderbook(order)

        assert len(order_manager._bids[50000.0]) == 3

    def test_add_order_without_id_ignored(self, order_manager):
        """测试无orderId的订单被忽略"""
        order = {
            "clientOrderId": "mm_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
        }
        order_manager._add_to_orderbook(order)
        assert len(order_manager.open_orders) == 0


class TestRemoveFromOrderbook:
    """测试 _remove_from_orderbook 方法"""

    def test_remove_existing_order(self, order_manager):
        """测试移除现有订单"""
        # 先添加订单
        order = {
            "orderId": "ORD001",
            "clientOrderId": "mm_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
        }
        order_manager._add_to_orderbook(order)

        # 移除订单
        removed = order_manager._remove_from_orderbook("ORD001")

        assert removed is not None
        assert removed["orderId"] == "ORD001"
        assert "ORD001" not in order_manager.open_orders
        assert "ORD001" not in order_manager._orders_by_type["mm"]
        assert 50000.0 not in order_manager._bids  # 价格档位已清空

    def test_remove_nonexistent_order(self, order_manager):
        """测试移除不存在的订单"""
        removed = order_manager._remove_from_orderbook("NONEXISTENT")
        assert removed is None

    def test_remove_preserves_other_orders_at_price(self, order_manager):
        """测试移除订单时保留同价格其他订单"""
        # 添加两个同价格订单
        for i in range(2):
            order = {
                "orderId": f"ORD{i}",
                "clientOrderId": f"mm_{i}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": 50000.0,
                "quantity": 0.1,
            }
            order_manager._add_to_orderbook(order)

        # 移除一个
        order_manager._remove_from_orderbook("ORD0")

        assert "ORD1" in order_manager.open_orders
        assert 50000.0 in order_manager._bids
        assert "ORD1" in order_manager._bids[50000.0]
        assert "ORD0" not in order_manager._bids[50000.0]


class TestUpdateOrderbook:
    """测试 _update_orderbook 方法"""

    def test_update_existing_order_state(self, order_manager):
        """测试更新现有订单状态"""
        # 添加订单
        order = {
            "orderId": "ORD001",
            "clientOrderId": "mm_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
            "state": "NEW",
        }
        order_manager._add_to_orderbook(order)

        # 更新状态为部分成交
        result = order_manager._update_orderbook("ORD001", "PARTIALLY_FILLED", executed_qty=0.05)

        assert result is True
        assert order_manager.open_orders["ORD001"]["state"] == "PARTIALLY_FILLED"
        assert order_manager.open_orders["ORD001"]["executedQty"] == 0.05

    def test_update_to_filled_moves_to_history(self, order_manager):
        """测试更新为FILLED状态将订单移到历史"""
        # 添加订单
        order = {
            "orderId": "ORD001",
            "clientOrderId": "mm_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
        }
        order_manager._add_to_orderbook(order)

        # 更新为完全成交
        order_manager._update_orderbook("ORD001", "FILLED", executed_qty=0.1)

        assert "ORD001" not in order_manager.open_orders
        assert len(order_manager.filled_orders) >= 1
        assert any(o["orderId"] == "ORD001" for o in order_manager.filled_orders)

    def test_update_to_canceled_moves_to_history(self, order_manager):
        """测试更新为CANCELED状态将订单移到历史"""
        order = {
            "orderId": "ORD001",
            "clientOrderId": "mm_001",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
        }
        order_manager._add_to_orderbook(order)

        order_manager._update_orderbook("ORD001", "CANCELED")

        assert "ORD001" not in order_manager.open_orders
        assert any(o["orderId"] == "ORD001" for o in order_manager.canceled_orders)

    def test_update_nonexistent_with_new_state_adds_order(self, order_manager):
        """测试更新不存在的订单但状态为NEW时添加订单"""
        order_data = {
            "orderId": "ORD_NEW",
            "clientOrderId": "hedge_001",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "price": 52000.0,
            "quantity": 0.1,
        }
        result = order_manager._update_orderbook("ORD_NEW", "NEW", order_data=order_data)

        assert result is True
        assert "ORD_NEW" in order_manager.open_orders
        assert "ORD_NEW" in order_manager._orders_by_type["hedge"]

    def test_update_nonexistent_without_data_returns_false(self, order_manager):
        """测试更新不存在的订单且无数据时返回False"""
        result = order_manager._update_orderbook("NONEXISTENT", "FILLED")
        assert result is False


class TestQueryInterfaces:
    """测试查询接口"""

    def test_get_orders_by_type(self, order_manager):
        """测试按类型获取订单"""
        # 添加不同类型的订单
        for i, prefix in enumerate(["mm", "wash", "hedge"]):
            order = {
                "orderId": f"ORD{i}",
                "clientOrderId": f"{prefix}_{i}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": 50000.0 + i * 100,
                "quantity": 0.1,
            }
            order_manager._add_to_orderbook(order)

        mm_orders = order_manager.get_orders_by_type("mm")
        wash_orders = order_manager.get_orders_by_type("wash")
        hedge_orders = order_manager.get_orders_by_type("hedge")

        assert len(mm_orders) == 1
        assert len(wash_orders) == 1
        assert len(hedge_orders) == 1
        assert mm_orders[0]["clientOrderId"].startswith("mm_")

    def test_get_best_bid_ask(self, order_manager):
        """测试获取最优买卖价"""
        # 添加多个买单
        for price in [50000, 50100, 50200]:
            order = {
                "orderId": f"BUY_{price}",
                "clientOrderId": f"mm_buy_{price}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": float(price),
                "quantity": 0.1,
            }
            order_manager._add_to_orderbook(order)

        # 添加多个卖单
        for price in [51000, 51100, 51200]:
            order = {
                "orderId": f"SELL_{price}",
                "clientOrderId": f"mm_sell_{price}",
                "symbol": "BTCUSDT",
                "side": "SELL",
                "price": float(price),
                "quantity": 0.1,
            }
            order_manager._add_to_orderbook(order)

        assert order_manager.get_best_bid() == 50200.0  # 最高买价
        assert order_manager.get_best_ask() == 51000.0  # 最低卖价

    def test_get_spread(self, order_manager):
        """测试获取买卖价差"""
        order_manager._add_to_orderbook({
            "orderId": "BUY1",
            "clientOrderId": "mm_buy",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
        })
        order_manager._add_to_orderbook({
            "orderId": "SELL1",
            "clientOrderId": "mm_sell",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "price": 51000.0,
            "quantity": 0.1,
        })

        spread = order_manager.get_spread()
        expected_spread = (51000 - 50000) / 50000  # 2%
        assert abs(spread - expected_spread) < 0.0001

    def test_get_orderbook_snapshot(self, order_manager):
        """测试获取订单簿快照"""
        # 添加一些订单
        order_manager._add_to_orderbook({
            "orderId": "BUY1",
            "clientOrderId": "mm_buy",
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": 50000.0,
            "quantity": 0.1,
        })
        order_manager._add_to_orderbook({
            "orderId": "SELL1",
            "clientOrderId": "wash_sell",
            "symbol": "BTCUSDT",
            "side": "SELL",
            "price": 51000.0,
            "quantity": 0.2,
        })

        snapshot = order_manager.get_orderbook_snapshot()

        assert "bids" in snapshot
        assert "asks" in snapshot
        assert snapshot["best_bid"] == 50000.0
        assert snapshot["best_ask"] == 51000.0
        assert snapshot["total_orders"] == 2
        assert snapshot["by_type"]["mm"] == 1
        assert snapshot["by_type"]["wash"] == 1

    def test_get_order_count_by_type(self, order_manager):
        """测试获取各类型订单数量"""
        for i in range(3):
            order_manager._add_to_orderbook({
                "orderId": f"MM{i}",
                "clientOrderId": f"mm_{i}",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": 50000.0 + i,
                "quantity": 0.1,
            })
        for i in range(2):
            order_manager._add_to_orderbook({
                "orderId": f"WASH{i}",
                "clientOrderId": f"wash_{i}",
                "symbol": "BTCUSDT",
                "side": "SELL",
                "price": 51000.0 + i,
                "quantity": 0.1,
            })

        counts = order_manager.get_order_count_by_type()
        assert counts["mm"] == 3
        assert counts["wash"] == 2
        assert counts["hedge"] == 0


class TestRebuildOrderbookIndexes:
    """测试重建订单簿索引"""

    def test_rebuild_clears_and_rebuilds(self, order_manager):
        """测试重建索引清空并重建"""
        # 直接往 open_orders 添加数据（模拟 reset_open_orders 的行为）
        order_manager.open_orders = {
            "ORD1": {
                "orderId": "ORD1",
                "clientOrderId": "mm_001",
                "symbol": "BTCUSDT",
                "side": "BUY",
                "price": 50000.0,
                "quantity": 0.1,
            },
            "ORD2": {
                "orderId": "ORD2",
                "clientOrderId": "wash_002",
                "symbol": "BTCUSDT",
                "side": "SELL",
                "price": 51000.0,
                "quantity": 0.2,
            },
        }

        # 重建索引
        order_manager._rebuild_orderbook_indexes()

        # 验证索引已正确重建
        assert "ORD1" in order_manager._orders_by_type["mm"]
        assert "ORD2" in order_manager._orders_by_type["wash"]
        assert 50000.0 in order_manager._bids
        assert 51000.0 in order_manager._asks


class TestThreadSafety:
    """测试线程安全性"""

    def test_concurrent_add_remove(self, order_manager):
        """测试并发添加和移除订单"""
        errors = []

        def add_orders(start_id, count):
            try:
                for i in range(count):
                    order = {
                        "orderId": f"ORD_{start_id}_{i}",
                        "clientOrderId": f"mm_{start_id}_{i}",
                        "symbol": "BTCUSDT",
                        "side": "BUY" if i % 2 == 0 else "SELL",
                        "price": 50000.0 + i,
                        "quantity": 0.1,
                    }
                    order_manager._add_to_orderbook(order)
            except Exception as e:
                errors.append(e)

        def remove_orders(start_id, count):
            try:
                time.sleep(0.01)  # 稍微延迟让添加先执行
                for i in range(count):
                    order_manager._remove_from_orderbook(f"ORD_{start_id}_{i}")
            except Exception as e:
                errors.append(e)

        threads = []
        for t_id in range(5):
            t1 = threading.Thread(target=add_orders, args=(t_id, 20))
            t2 = threading.Thread(target=remove_orders, args=(t_id, 20))
            threads.extend([t1, t2])

        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # 不应有任何错误
        assert len(errors) == 0, f"并发操作出错: {errors}"
