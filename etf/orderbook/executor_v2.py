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
from ..utils.constants import MAX_BATCH_SIZE_SEND


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
        判断是否会发生订单溢出（优化版）

        新逻辑：
        - 如果最终订单数 <= max_orders，允许临时超限（利用交易所弹性空间）
        - 临时超限最多允许 max_temp_overflow 个订单（默认50）
        - 这样可以保持"先加后删"策略，避免盘口深度骤降

        Args:
            current_count: 当前订单数
            add_count: 待添加数量
            cancel_count: 待取消数量

        Returns:
            bool: 是否溢出（True = 需要先删后加）
        """
        # 计算最终订单数（操作完成后）
        final_count = current_count + add_count - cancel_count

        # 获取允许的临时超限数量
        max_temp_overflow = self.config.get("max_temp_overflow", 50)

        # 如果最终订单数在限制内，考虑允许临时超限
        if final_count <= self.max_orders:
            # 计算峰值订单数（先加后删时的最大值）
            peak_count = current_count + add_count

            # 计算临时超限数量
            temp_overflow = peak_count - self.max_orders

            # 如果临时超限在允许范围内，不算溢出（使用 add_first）
            if temp_overflow <= max_temp_overflow:
                if temp_overflow > 0:
                    self.logger.debug(
                        f"允许临时超限: 当前 {current_count}, "
                        f"+{add_count}/-{cancel_count}, "
                        f"峰值 {peak_count}, 最终 {final_count}, "
                        f"临时超限 {temp_overflow} <= {max_temp_overflow}"
                    )
                return False

            # 临时超限过多，需要先删后加
            self.logger.info(
                f"临时超限过多: 峰值 {peak_count}, "
                f"超限 {temp_overflow} > {max_temp_overflow}, 使用 cancel_first"
            )
            return True

        # 最终订单数超限，必须先删后加
        self.logger.warning(
            f"最终订单数超限: {final_count} > {self.max_orders}, 必须使用 cancel_first"
        )
        return True

    def _execute_adds(
        self,
        add_ops: List[OrderOperation],
    ) -> Dict:
        """
        执行添加订单操作（批量下单，自动分批）

        Args:
            add_ops: 添加操作列表

        Returns:
            Dict: {'succeeded': [...], 'failed': [...]}
        """
        succeeded = []
        failed = []

        if not add_ops:
            return {"succeeded": succeeded, "failed": failed}

        # 构建批量订单数据
        all_orders = []
        all_mappings = []  # 记录每个订单对应的原始操作

        for op in add_ops:
            try:
                side = "BUY" if op.side == "bid" else "SELL"
                price = float(round(op.price, self.price_precision))
                quantity = float(round(op.quantity, self.quantity_precision))

                # 生成 clientOrderId
                base_id = self.order_manager.create_temp_id()
                client_order_id = f"mm_{base_id}"

                all_orders.append({
                    "symbol": self.symbol,
                    "side": side,
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": price,
                    "quantity": quantity,
                    "clientOrderId": client_order_id,
                    "order_purpose": "market_making",
                })
                all_mappings.append({
                    "op": op,
                    "price": price,
                    "quantity": quantity,
                    "client_order_id": client_order_id,
                })

            except Exception as e:
                failed.append((op, f"构建订单失败: {e}"))
                self.logger.warning(
                    f"构建订单失败: {op.side} @ {op.price} x {op.quantity}, 错误: {e}"
                )

        if not all_orders:
            return {"succeeded": succeeded, "failed": failed}

        # ✅ 分批处理：XT 交易所批量下单限制
        MAX_BATCH_SIZE = MAX_BATCH_SIZE_SEND
        total_batches = (len(all_orders) + MAX_BATCH_SIZE - 1) // MAX_BATCH_SIZE
        
        self.logger.info(
            f"批量下单: 共 {len(all_orders)} 个订单，分 {total_batches} 批处理"
        )

        for batch_idx in range(0, len(all_orders), MAX_BATCH_SIZE):
            batch_orders = all_orders[batch_idx:batch_idx + MAX_BATCH_SIZE]
            batch_mappings = all_mappings[batch_idx:batch_idx + MAX_BATCH_SIZE]
            batch_num = batch_idx // MAX_BATCH_SIZE + 1

            # 执行批量下单
            try:
                response = self.order_manager.add_orders_batch(
                    batch_orders,
                    order_purpose="market_making",
                )

                if response and response.get("items"):
                    # 处理响应
                    for i, item in enumerate(response["items"]):
                        if i >= len(batch_mappings):
                            break

                        mapping = batch_mappings[i]
                        op = mapping["op"]

                        if item.get("rejected"):
                            failed.append((op, f"被交易所拒绝: {item.get('reason')}"))
                            self.logger.warning(
                                f"订单被拒绝: {op.side} @ {mapping['price']}, "
                                f"原因: {item.get('reason')}"
                            )
                        else:
                            succeeded.append({
                                "order_id": item.get("orderId"),
                                "client_order_id": item.get("clientOrderId") or mapping["client_order_id"],
                                "side": op.side,
                                "price": mapping["price"],
                                "quantity": mapping["quantity"],
                                "reason": op.reason,
                            })

                    batch_success = sum(1 for item in response["items"] if not item.get("rejected"))
                    self.logger.debug(
                        f"批次 {batch_num}/{total_batches} 完成: "
                        f"{batch_success}/{len(batch_orders)} 成功"
                    )
                else:
                    # 批量下单失败，全部标记为失败
                    for mapping in batch_mappings:
                        failed.append((mapping["op"], "批量下单返回空响应"))
                    self.logger.error(f"批次 {batch_num}/{total_batches} 返回空响应")

            except Exception as e:
                # 批量下单异常，当前批次全部标记为失败
                for mapping in batch_mappings:
                    failed.append((mapping["op"], str(e)))
                self.logger.error(f"批次 {batch_num}/{total_batches} 异常: {e}")

        # 最终统计
        self.logger.info(
            f"批量下单完成: {len(succeeded)}/{len(all_orders)} 成功, "
            f"{len(failed)} 失败"
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
