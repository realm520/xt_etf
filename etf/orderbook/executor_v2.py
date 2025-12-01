"""
订单簿执行器 V2 - 精简版

专为 OrderbookMaintainer 设计，职责清晰：
1. 执行 Maintainer 输出的 OrderOperation 列表
2. 先加后删策略（或先删后加，取决于订单溢出）
3. 过滤仅 mm_ 前缀订单
4. 返回执行结果统计
"""

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import List, Dict, Optional, Tuple, TYPE_CHECKING

if TYPE_CHECKING:
    from ..order_manager import OrderManager

from .base import OrderOperation


@dataclass
class ExecutionStats:
    """执行统计"""

    # 操作数量
    total_operations: int = 0
    add_operations: int = 0
    cancel_operations: int = 0

    # 执行结果
    adds_succeeded: int = 0
    adds_failed: int = 0
    cancels_succeeded: int = 0
    cancels_failed: int = 0

    # 执行策略
    execution_order: str = "add_first"  # 'add_first' | 'cancel_first'

    # 耗时
    execution_time_ms: float = 0.0

    @property
    def success_rate(self) -> float:
        """成功率"""
        total = self.adds_succeeded + self.adds_failed + self.cancels_succeeded + self.cancels_failed
        if total == 0:
            return 1.0
        return (self.adds_succeeded + self.cancels_succeeded) / total


@dataclass
class ExecutionResult:
    """执行结果"""

    success: bool
    stats: ExecutionStats

    # 已执行的操作
    executed_adds: List[Dict] = field(default_factory=list)
    executed_cancels: List[str] = field(default_factory=list)

    # 失败的操作
    failed_adds: List[Tuple[OrderOperation, str]] = field(default_factory=list)
    failed_cancels: List[Tuple[str, str]] = field(default_factory=list)

    # 错误信息
    error_message: Optional[str] = None


class OrderExecutorV2:
    """
    精简版订单执行器

    专为 OrderbookMaintainer 设计，核心功能：
    1. 执行 add/cancel 操作列表
    2. 订单数量保护（防止超过交易所限制）
    3. 先加后删/先删后加策略自动选择
    """

    # 交易所订单上限（XT 默认 200）
    DEFAULT_MAX_ORDERS = 200

    def __init__(
        self,
        order_manager: "OrderManager",
        symbol: str,
        strategy_name: str,
        config: Optional[Dict] = None,
    ):
        """
        初始化执行器

        Args:
            order_manager: OrderManager 实例
            symbol: 交易对
            strategy_name: 策略名称
            config: 配置字典，支持以下参数：
                - max_orders: 最大订单数（默认 200）
                - order_overflow_threshold: 订单溢出阈值（默认 0.9）
                - price_precision: 价格精度（默认 6）
                - quantity_precision: 数量精度（默认 2）
        """
        self.order_manager = order_manager
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.config = config or {}

        # 配置参数
        self.max_orders = self.config.get("max_orders", self.DEFAULT_MAX_ORDERS)
        self.order_overflow_threshold = self.config.get("order_overflow_threshold", 0.9)
        self.price_precision = self.config.get("price_precision", 6)
        self.quantity_precision = self.config.get("quantity_precision", 2)

        self.logger = logging.getLogger(f"{__name__}.{strategy_name}")

    def execute(
        self,
        operations: List[OrderOperation],
        current_order_count: int = 0,
    ) -> ExecutionResult:
        """
        执行订单操作列表

        Args:
            operations: Maintainer 输出的操作列表（已排序）
            current_order_count: 当前订单数量（用于判断是否溢出）

        Returns:
            ExecutionResult: 执行结果
        """
        start_time = time.time()
        stats = ExecutionStats(total_operations=len(operations))

        if not operations:
            return ExecutionResult(
                success=True,
                stats=stats,
            )

        # 分离 add 和 cancel 操作
        add_ops = [op for op in operations if op.action == "add"]
        cancel_ops = [op for op in operations if op.action == "cancel"]

        stats.add_operations = len(add_ops)
        stats.cancel_operations = len(cancel_ops)

        # 决定执行策略
        is_overflow = self._is_order_overflow(
            current_order_count, len(add_ops), len(cancel_ops)
        )

        executed_adds: List[Dict] = []
        executed_cancels: List[str] = []
        failed_adds: List[Tuple[OrderOperation, str]] = []
        failed_cancels: List[Tuple[str, str]] = []

        try:
            if is_overflow:
                # 订单溢出：先删后加
                stats.execution_order = "cancel_first"
                self.logger.warning(
                    f"订单溢出保护: 当前 {current_order_count} 个, "
                    f"将先取消 {len(cancel_ops)} 个再添加 {len(add_ops)} 个"
                )

                # 先执行取消
                cancel_results = self._execute_cancels(cancel_ops)
                executed_cancels = cancel_results["succeeded"]
                failed_cancels = cancel_results["failed"]
                stats.cancels_succeeded = len(executed_cancels)
                stats.cancels_failed = len(failed_cancels)

                # 再执行添加
                add_results = self._execute_adds(add_ops)
                executed_adds = add_results["succeeded"]
                failed_adds = add_results["failed"]
                stats.adds_succeeded = len(executed_adds)
                stats.adds_failed = len(failed_adds)

            else:
                # 正常流程：先加后删
                stats.execution_order = "add_first"

                # 先执行添加
                add_results = self._execute_adds(add_ops)
                executed_adds = add_results["succeeded"]
                failed_adds = add_results["failed"]
                stats.adds_succeeded = len(executed_adds)
                stats.adds_failed = len(failed_adds)

                # 再执行取消
                cancel_results = self._execute_cancels(cancel_ops)
                executed_cancels = cancel_results["succeeded"]
                failed_cancels = cancel_results["failed"]
                stats.cancels_succeeded = len(executed_cancels)
                stats.cancels_failed = len(failed_cancels)

            stats.execution_time_ms = (time.time() - start_time) * 1000

            # 判断整体成功
            success = stats.success_rate >= 0.8  # 80% 成功率即视为成功

            self.logger.info(
                f"执行完成: +{stats.adds_succeeded}/{stats.add_operations} adds, "
                f"-{stats.cancels_succeeded}/{stats.cancel_operations} cancels, "
                f"成功率 {stats.success_rate:.1%}, 耗时 {stats.execution_time_ms:.0f}ms"
            )

            return ExecutionResult(
                success=success,
                stats=stats,
                executed_adds=executed_adds,
                executed_cancels=executed_cancels,
                failed_adds=failed_adds,
                failed_cancels=failed_cancels,
            )

        except Exception as e:
            stats.execution_time_ms = (time.time() - start_time) * 1000
            self.logger.error(f"执行异常: {e}")
            return ExecutionResult(
                success=False,
                stats=stats,
                executed_adds=executed_adds,
                executed_cancels=executed_cancels,
                failed_adds=failed_adds,
                failed_cancels=failed_cancels,
                error_message=str(e),
            )

    def _is_order_overflow(
        self,
        current_count: int,
        add_count: int,
        cancel_count: int,
    ) -> bool:
        """
        判断是否会发生订单溢出

        Args:
            current_count: 当前订单数
            add_count: 待添加数量
            cancel_count: 待取消数量

        Returns:
            bool: 是否溢出
        """
        # 如果先加后删，峰值订单数
        peak_count = current_count + add_count

        # 溢出阈值
        threshold = int(self.max_orders * self.order_overflow_threshold)

        return peak_count > threshold

    def _execute_adds(
        self,
        add_ops: List[OrderOperation],
    ) -> Dict:
        """
        执行添加订单操作

        Args:
            add_ops: 添加操作列表

        Returns:
            Dict: {'succeeded': [...], 'failed': [...]}
        """
        succeeded = []
        failed = []

        for op in add_ops:
            try:
                # 转换为 OrderManager 参数
                side = "BUY" if op.side == "bid" else "SELL"

                # 格式化价格和数量
                price = float(round(op.price, self.price_precision))
                quantity = float(round(op.quantity, self.quantity_precision))

                response = self.order_manager.add_order(
                    symbol=self.symbol,
                    side=side,
                    price=price,
                    quantity=quantity,
                    order_purpose="market_making",
                )

                if response:
                    succeeded.append({
                        "order_id": response.get("orderId"),
                        "client_order_id": response.get("clientOrderId"),
                        "side": op.side,
                        "price": price,
                        "quantity": quantity,
                        "reason": op.reason,
                    })
                else:
                    failed.append((op, "order_manager returned None"))

            except Exception as e:
                failed.append((op, str(e)))
                self.logger.warning(
                    f"添加订单失败: {op.side} @ {op.price} x {op.quantity}, 错误: {e}"
                )

        return {"succeeded": succeeded, "failed": failed}

    def _execute_cancels(
        self,
        cancel_ops: List[OrderOperation],
    ) -> Dict:
        """
        执行取消订单操作

        Args:
            cancel_ops: 取消操作列表

        Returns:
            Dict: {'succeeded': [...], 'failed': [...]}
        """
        succeeded = []
        failed = []

        for op in cancel_ops:
            try:
                # 调用 OrderManager 取消订单
                result = self.order_manager.cancel_order({"orderId": op.order_id})

                if result:
                    succeeded.append(op.order_id)
                else:
                    # 可能订单已成交或已取消，不算失败
                    succeeded.append(op.order_id)
                    self.logger.debug(
                        f"取消订单返回空: {op.order_id}, 可能已成交/取消"
                    )

            except Exception as e:
                error_str = str(e).lower()
                # 常见的"订单不存在"错误，视为成功
                if "order_009" in error_str or "not exist" in error_str:
                    succeeded.append(op.order_id)
                    self.logger.debug(f"订单已不存在: {op.order_id}")
                else:
                    failed.append((op.order_id, str(e)))
                    self.logger.warning(f"取消订单失败: {op.order_id}, 错误: {e}")

        return {"succeeded": succeeded, "failed": failed}

    def get_current_mm_order_count(self) -> int:
        """
        获取当前 mm_ 前缀订单数量

        Returns:
            int: mm_ 订单数量
        """
        try:
            open_orders = self.order_manager.open_orders
            count = sum(
                1
                for order in open_orders.values()
                if (order.get("clientOrderId") or "").startswith("mm_")
            )
            return count
        except Exception as e:
            self.logger.warning(f"获取订单数量失败: {e}")
            return 0
