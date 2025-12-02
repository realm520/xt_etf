# -*- coding:utf-8 -*-

"""
测试订单执行器溢出判定逻辑

验证优化后的 _is_order_overflow() 函数:
- 允许临时超限以保持 add_first 策略
- 避免盘口深度骤降导致插针

Author: Claude Code
Date: 2025-12
"""

import pytest
from unittest.mock import MagicMock, patch


class TestOrderOverflowLogic:
    """测试订单溢出判定逻辑"""

    def _create_executor(self, config=None):
        """创建测试用的执行器实例"""
        from etf.orderbook.executor_v2 import OrderExecutorV2

        mock_order_manager = MagicMock()
        mock_order_manager.open_orders = {}

        default_config = {
            "max_orders": 200,
            "order_overflow_threshold": 0.85,
            "max_temp_overflow": 50,
        }
        if config:
            default_config.update(config)

        return OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TON3L_USDT",
            strategy_name="test_strategy",
            config=default_config,
        )

    def test_no_overflow_normal_case(self):
        """测试正常情况：订单数在阈值内"""
        executor = self._create_executor()

        # 当前 100 个订单，加 20 个，删 10 个
        # 峰值 = 100 + 20 = 120 < 200，最终 = 110
        result = executor._is_order_overflow(
            current_count=100,
            add_count=20,
            cancel_count=10,
        )

        assert result is False, "正常情况应该返回 False（使用 add_first）"

    def test_allow_temp_overflow_within_limit(self):
        """测试允许临时超限：峰值超过 max_orders 但在允许范围内"""
        executor = self._create_executor()

        # 当前 194 个订单，加 20 个，删 80 个
        # 峰值 = 194 + 20 = 214，超过 200 但只超 14 个（< 50）
        # 最终 = 194 + 20 - 80 = 134 < 200
        result = executor._is_order_overflow(
            current_count=194,
            add_count=20,
            cancel_count=80,
        )

        assert result is False, "临时超限 14 个应该允许（使用 add_first）"

    def test_temp_overflow_at_boundary(self):
        """测试临时超限边界：刚好在允许的最大值"""
        executor = self._create_executor()

        # 当前 200 个订单，加 50 个，删 50 个
        # 峰值 = 200 + 50 = 250，超过 50 个刚好等于 max_temp_overflow
        # 最终 = 200 + 50 - 50 = 200
        result = executor._is_order_overflow(
            current_count=200,
            add_count=50,
            cancel_count=50,
        )

        assert result is False, "临时超限 50 个应该允许（边界值）"

    def test_temp_overflow_exceeds_limit(self):
        """测试临时超限超过限制：需要使用 cancel_first"""
        executor = self._create_executor()

        # 当前 200 个订单，加 60 个，删 60 个
        # 峰值 = 200 + 60 = 260，超过 60 个 > 50
        # 最终 = 200
        result = executor._is_order_overflow(
            current_count=200,
            add_count=60,
            cancel_count=60,
        )

        assert result is True, "临时超限 60 个应该拒绝（使用 cancel_first）"

    def test_final_count_exceeds_max(self):
        """测试最终订单数超过限制"""
        executor = self._create_executor()

        # 当前 180 个订单，加 30 个，删 5 个
        # 最终 = 180 + 30 - 5 = 205 > 200
        result = executor._is_order_overflow(
            current_count=180,
            add_count=30,
            cancel_count=5,
        )

        assert result is True, "最终订单数超限应该拒绝"

    def test_custom_max_temp_overflow(self):
        """测试自定义 max_temp_overflow 配置"""
        # 设置更小的临时超限允许值
        executor = self._create_executor({"max_temp_overflow": 20})

        # 峰值超过 30 个，超过自定义限制 20
        result = executor._is_order_overflow(
            current_count=200,
            add_count=30,
            cancel_count=30,
        )

        assert result is True, "超过自定义 max_temp_overflow 应该拒绝"

    def test_no_temp_overflow_config(self):
        """测试未配置 max_temp_overflow 时使用默认值 50"""
        executor = self._create_executor({})
        # 移除 max_temp_overflow 配置，测试默认值
        del executor.config["max_temp_overflow"]

        # 临时超限 40 个，应该在默认值 50 内
        result = executor._is_order_overflow(
            current_count=200,
            add_count=40,
            cancel_count=40,
        )

        assert result is False, "默认 max_temp_overflow=50 应该允许 40 个临时超限"

    def test_zero_operations(self):
        """测试无操作情况"""
        executor = self._create_executor()

        result = executor._is_order_overflow(
            current_count=150,
            add_count=0,
            cancel_count=0,
        )

        assert result is False, "无操作应该返回 False"

    def test_only_cancel_operations(self):
        """测试只有取消操作"""
        executor = self._create_executor()

        result = executor._is_order_overflow(
            current_count=200,
            add_count=0,
            cancel_count=50,
        )

        assert result is False, "只有取消操作不会导致溢出"

    def test_scenario_from_logs(self):
        """测试日志中的真实场景
        
        日志场景:
        - 当前 194 个订单
        - 生成 +20 add, -80 cancel
        - 净值变化 -0.2%，复用率从 62% 降到 0%
        
        期望结果: 允许使用 add_first，避免盘口深度骤降
        """
        executor = self._create_executor()

        result = executor._is_order_overflow(
            current_count=194,
            add_count=20,
            cancel_count=80,
        )

        # 峰值 = 214，临时超限 14 个 < 50
        # 最终 = 134 < 200
        assert result is False, "日志场景应该使用 add_first"

    def test_worst_case_scenario(self):
        """测试极端场景：净值剧烈变化导致全部订单需要替换"""
        executor = self._create_executor()

        # 极端情况：所有订单都需要替换
        # 当前 200 个，加 200 个新订单，删 200 个旧订单
        # 峰值 = 400，临时超限 200 个 > 50
        result = executor._is_order_overflow(
            current_count=200,
            add_count=200,
            cancel_count=200,
        )

        assert result is True, "极端场景应该使用 cancel_first"


class TestOrderOverflowIntegration:
    """集成测试：验证溢出逻辑与执行流程的配合"""

    def test_execute_with_add_first_strategy(self):
        """测试允许 add_first 时的执行流程"""
        from etf.orderbook.executor_v2 import OrderExecutorV2, ExecutionStats
        from etf.orderbook.base import OrderOperation
        from decimal import Decimal

        mock_order_manager = MagicMock()
        mock_order_manager.open_orders = {}
        mock_order_manager.create_temp_id.return_value = "test_id"
        mock_order_manager.add_orders_batch.return_value = {
            "items": [{"orderId": "123", "rejected": False}]
        }
        mock_order_manager.cancel_order.return_value = True

        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TON3L_USDT",
            strategy_name="test",
            config={"max_orders": 200, "max_temp_overflow": 50},
        )

        # 创建测试操作
        operations = [
            OrderOperation(
                action="add",
                side="bid",
                price=Decimal("1.5"),
                quantity=Decimal("100"),
                reason="test_add",
            ),
            OrderOperation(
                action="cancel",
                side="ask",
                order_id="old_123",
                price=Decimal("1.6"),
                quantity=Decimal("100"),
                reason="test_cancel",
            ),
        ]

        # 执行，当前订单数 190，临时超限 1 个
        result = executor.execute(operations, current_order_count=190)

        assert result.success is True
        assert result.stats.execution_order == "add_first"

    def test_execute_with_cancel_first_strategy(self):
        """测试需要 cancel_first 时的执行流程"""
        from etf.orderbook.executor_v2 import OrderExecutorV2
        from etf.orderbook.base import OrderOperation
        from decimal import Decimal

        mock_order_manager = MagicMock()
        mock_order_manager.open_orders = {}
        mock_order_manager.create_temp_id.return_value = "test_id"
        mock_order_manager.add_orders_batch.return_value = {
            "items": [{"orderId": "123", "rejected": False}]
        }
        mock_order_manager.cancel_order.return_value = True

        executor = OrderExecutorV2(
            order_manager=mock_order_manager,
            symbol="TON3L_USDT",
            strategy_name="test",
            config={"max_orders": 200, "max_temp_overflow": 50},
        )

        # 创建大量添加操作，触发溢出保护
        operations = [
            OrderOperation(
                action="add",
                side="bid",
                price=Decimal("1.5"),
                quantity=Decimal("100"),
                reason="test_add",
            )
            for _ in range(60)
        ] + [
            OrderOperation(
                action="cancel",
                side="ask",
                order_id=f"old_{i}",
                price=Decimal("1.6"),
                quantity=Decimal("100"),
                reason="test_cancel",
            )
            for i in range(60)
        ]

        # 执行，当前订单数 200，临时超限 60 个 > 50
        result = executor.execute(operations, current_order_count=200)

        assert result.stats.execution_order == "cancel_first"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
