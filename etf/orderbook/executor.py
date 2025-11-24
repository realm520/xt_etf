"""
订单执行器 - 统一订单执行接口

职责：
1. 整合订单匹配和执行逻辑
2. 支持订单簿差异计算
3. 执行批量订单操作（下单、撤单）
4. 处理反针对订单
5. 提供执行结果统计
"""

import time
import logging
from typing import List, Dict, Optional, Any, Tuple
from dataclasses import dataclass

from ..utils.optimization import optimize_order_matching, optimize_batch_operations
from ..utils.constants import (
    SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT,
    TIME_IN_FORCE_GTC, BIZ_TYPE_SPOT, DEFAULT_BATCH_SIZE
)


@dataclass
class ExecutionResult:
    """单个订单操作的执行结果"""

    success: bool                  # 是否成功
    operation_type: str            # 操作类型: 'add' 或 'cancel'
    order_count: int               # 订单数量
    order_ids: List[str] = None    # 订单ID列表
    error: Optional[str] = None    # 错误信息（失败时）


@dataclass
class ExecutionSummary:
    """执行总结"""

    total_add: int                 # 新增订单数
    total_cancel: int              # 取消订单数
    successful_add: int            # 成功新增数
    successful_cancel: int         # 成功取消数
    failed_add: int                # 失败新增数
    failed_cancel: int             # 失败取消数
    execution_time: float          # 执行耗时（秒）

    def summary_text(self) -> str:
        """生成总结文本"""
        return (
            f"执行完成 - "
            f"新增: {self.successful_add}/{self.total_add}, "
            f"取消: {self.successful_cancel}/{self.total_cancel}, "
            f"耗时: {self.execution_time:.2f}s"
        )


class OrderExecutor:
    """订单执行器

    整合订单匹配、批量执行、反针对订单等完整流程

    示例用法:
        executor = OrderExecutor(order_manager, symbol, strategy_name)

        # 执行订单簿更新
        summary = executor.execute_orderbook_update(
            current_orders=current_orders,
            target_orders=target_orders,
            anti_pin_config=config
        )
    """

    def __init__(
        self,
        order_manager,              # OrderManager实例
        symbol: str,                # 交易对
        strategy_name: str,
        max_layer: Optional[int] = None,  # 新增：最大档位数（用于订单数量保护）
        logger: Optional[logging.Logger] = None
    ):
        self.order_manager = order_manager
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.max_layer = max_layer  # 保存最大档位数
        self.logger = logger or logging.getLogger(strategy_name)

        # 记录当前周期的反针对订单ID
        self.current_anti_pin_order_ids: List[str] = []

    def execute_orderbook_update(
        self,
        current_orders: List[Dict[str, Any]],
        target_orders: List[Dict[str, Any]],
        best_sell: float,
        best_buy: float,
        anti_pin_config: Optional[Dict[str, Any]] = None,
    ) -> ExecutionSummary:
        """执行订单簿更新（完整流程）

        Args:
            current_orders: 当前市场订单列表
            target_orders: 目标订单列表（算法生成）
            best_sell: 最优卖价
            best_buy: 最优买价
            anti_pin_config: 反针对订单配置

        Returns:
            ExecutionSummary: 执行总结
        """
        start_time = time.time()

        # === 0. 订单数量监控和告警 ===
        current_order_count = len(current_orders)
        
        if self.max_layer is not None:
            # 计算告警阈值
            warning_threshold = self.max_layer * 1.2   # 120% 警告
            critical_threshold = self.max_layer * 1.5  # 150% 危急
            
            if current_order_count > critical_threshold:
                self.logger.error(
                    f"🚨 订单数量严重超标: {current_order_count} > {critical_threshold:.0f} "
                    f"(配置: {self.max_layer}档, 危急阈值: 150%)"
                )
            elif current_order_count > warning_threshold:
                self.logger.warning(
                    f"⚠️ 订单数量超标: {current_order_count} > {warning_threshold:.0f} "
                    f"(配置: {self.max_layer}档, 警告阈值: 120%)"
                )
            else:
                self.logger.debug(
                    f"📊 订单数量正常: {current_order_count}/{self.max_layer} "
                    f"({current_order_count/self.max_layer:.1%})"
                )

        # === 1. 订单匹配分析 ===
        optimized_add_orders, optimized_cancel_orders = self._match_orders(
            current_orders, target_orders
        )

        # 为每个新订单设置clientOrderId和order_purpose
        for order_data in optimized_add_orders:
            order_data["clientOrderId"] = self.order_manager.create_temp_id()
            # 如果订单未指定用途，默认为做市订单
            if "order_purpose" not in order_data:
                order_data["order_purpose"] = "market_making"

        # === 2. 识别超范围订单 ===
        out_of_range_orders = self._find_out_of_range_orders(
            current_orders, best_sell, best_buy
        )
        optimized_cancel_orders.extend(out_of_range_orders)

        self.logger.info(
            f"订单操作计划 - 新增: {len(optimized_add_orders)}, "
            f"取消: {len(optimized_cancel_orders)}"
        )

        # === 3. 添加反针对订单 ===
        if anti_pin_config:
            anti_pin_orders = self._create_anti_pin_orders(
                best_sell, best_buy, anti_pin_config
            )
            optimized_add_orders.extend(anti_pin_orders)

        # === 4. 执行订单操作（先加后删）===
        successful_add = 0
        failed_add = 0
        successful_cancel = 0
        failed_cancel = 0

        # 步骤1: 批量添加新订单
        if optimized_add_orders:
            add_result = self._execute_add_orders(optimized_add_orders)
            successful_add = add_result.order_count if add_result.success else 0
            failed_add = len(optimized_add_orders) - successful_add

        # 步骤2: 等待新订单上盘
        if optimized_add_orders:
            time.sleep(0.1)

        # 步骤3: 批量取消旧订单
        if optimized_cancel_orders:
            cancel_result = self._execute_cancel_orders(optimized_cancel_orders)
            successful_cancel = cancel_result.order_count if cancel_result.success else 0
            failed_cancel = len(optimized_cancel_orders) - successful_cancel

        # === 5. 清理旧的反针对订单 ===
        if anti_pin_config:
            self._cancel_old_anti_pin_orders(
                anti_pin_config.get("anti_pin_price_sell"),
                anti_pin_config.get("anti_pin_price_buy"),
            )

        # === 6. 生成执行总结 ===
        execution_time = time.time() - start_time

        summary = ExecutionSummary(
            total_add=len(optimized_add_orders),
            total_cancel=len(optimized_cancel_orders),
            successful_add=successful_add,
            successful_cancel=successful_cancel,
            failed_add=failed_add,
            failed_cancel=failed_cancel,
            execution_time=execution_time,
        )

        self.logger.info(summary.summary_text())

        return summary

    def _match_orders(
        self,
        current_orders: List[Dict[str, Any]],
        target_orders: List[Dict[str, Any]],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """执行订单匹配分析

        使用优化的匹配算法，将O(n²)复杂度降低到O(n log n)
        现在包含超范围订单清理和数量保护

        Returns:
            Tuple: (需要添加的订单, 需要取消的订单)
        """
        # 为target_orders添加symbol信息
        for goal in target_orders:
            goal["symbol"] = self.symbol

        # 调用优化的匹配算法（现在支持max_layer参数）
        optimized_add, optimized_cancel = optimize_order_matching(
            current_orders, 
            target_orders,
            max_layer=self.max_layer,      # 传递最大档位数
            cleanup_threshold=1.5          # 150%清理阈值
        )

        return optimized_add, optimized_cancel

    def _find_out_of_range_orders(
        self,
        current_orders: List[Dict[str, Any]],
        best_sell: float,
        best_buy: float,
    ) -> List[Dict[str, Any]]:
        """识别超出范围的订单"""
        out_of_range = []

        for market_order in current_orders:
            price = float(market_order["price"])
            side = market_order["side"]

            # 卖单价格低于最优卖价 或 买单价格高于最优买价
            if (price < best_sell and side == "SELL") or (
                price > best_buy and side == "BUY"
            ):
                self.logger.debug(f"超范围订单需取消: {price} ({side})")
                out_of_range.append(market_order)

        return out_of_range

    def _create_anti_pin_orders(
        self,
        best_sell: float,
        best_buy: float,
        config: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """创建反针对订单

        Args:
            best_sell: 最优卖价
            best_buy: 最优买价
            config: 配置字典，包含:
                - anti_pin_rate: 反针对价格偏离率
                - anti_pin_usdt: 反针对订单总金额（USDT）
                - precision: 价格精度
                - prec_amount: 数量精度

        Returns:
            List: 反针对订单列表
        """
        anti_pin_price_sell = round(
            best_sell * (1 + config["anti_pin_rate"]), config["precision"]
        )
        anti_pin_price_buy = round(
            best_buy * (1 - config["anti_pin_rate"]), config["precision"]
        )

        anti_pin_amount_sell = round(
            (config["anti_pin_usdt"] / 2) / anti_pin_price_sell,
            config["prec_amount"],
        )
        anti_pin_amount_buy = round(
            (config["anti_pin_usdt"] / 2) / anti_pin_price_buy,
            config["prec_amount"],
        )

        # 清空上一周期的反针对订单ID记录
        self.current_anti_pin_order_ids = []

        anti_pin_orders = []

        # 创建反针对卖单
        sell_client_order_id = self.order_manager.create_temp_id()
        sell_order_data = {
            "symbol": self.symbol,
            "clientOrderId": sell_client_order_id,
            "side": SIDE_SELL,
            "type": ORDER_TYPE_LIMIT,
            "timeInForce": TIME_IN_FORCE_GTC,
            "bizType": BIZ_TYPE_SPOT,
            "price": anti_pin_price_sell,
            "quantity": anti_pin_amount_sell,
            "quoteQty": None,
            "order_purpose": "anti_pin",  # 标记为反针对订单
        }
        anti_pin_orders.append(sell_order_data)
        self.current_anti_pin_order_ids.append(sell_client_order_id)

        # 创建反针对买单
        buy_client_order_id = self.order_manager.create_temp_id()
        buy_order_data = {
            "symbol": self.symbol,
            "clientOrderId": buy_client_order_id,
            "side": SIDE_BUY,
            "type": ORDER_TYPE_LIMIT,
            "timeInForce": TIME_IN_FORCE_GTC,
            "bizType": BIZ_TYPE_SPOT,
            "price": anti_pin_price_buy,
            "quantity": anti_pin_amount_buy,
            "quoteQty": None,
            "order_purpose": "anti_pin",  # 标记为反针对订单
        }
        anti_pin_orders.append(buy_order_data)
        self.current_anti_pin_order_ids.append(buy_client_order_id)

        self.logger.info(
            f"反针对订单 - 卖价: {anti_pin_price_sell} (量: {anti_pin_amount_sell}), "
            f"买价: {anti_pin_price_buy} (量: {anti_pin_amount_buy})"
        )

        # 保存反针对价格到配置（供后续清理使用）
        config["anti_pin_price_sell"] = anti_pin_price_sell
        config["anti_pin_price_buy"] = anti_pin_price_buy

        return anti_pin_orders

    def _execute_add_orders(
        self, orders: List[Dict[str, Any]]
    ) -> ExecutionResult:
        """批量添加订单"""
        max_batch_size = DEFAULT_BATCH_SIZE

        # 分批执行
        chunked_orders = optimize_batch_operations(orders, max_batch_size, "add")

        total_success = 0

        for batch in chunked_orders:
            try:
                # 每个订单自带order_purpose字段，无需在这里统一指定
                res = self.order_manager.add_orders_batch(batch, batch_id=None)
                if res:
                    total_success += len(batch)
                self.logger.info(f"✅ 成功添加 {len(batch)} 个新订单")
            except Exception as e:
                self.logger.error(f"❌ 批量添加订单失败: {e}")

        return ExecutionResult(
            success=(total_success > 0),
            operation_type="add",
            order_count=total_success,
        )

    def _execute_cancel_orders(
        self, orders: List[Dict[str, Any]]
    ) -> ExecutionResult:
        """批量取消订单"""
        max_batch_size = DEFAULT_BATCH_SIZE

        # 分批执行
        chunked_orders = optimize_batch_operations(orders, max_batch_size, "cancel")

        total_success = 0

        for batch in chunked_orders:
            try:
                res = self.order_manager.cancel_orders_batch(orders=batch)
                if res:
                    total_success += len(batch)
                self.logger.info(f"✅ 成功取消 {len(batch)} 个旧订单")
            except Exception as e:
                self.logger.error(f"❌ 批量取消订单失败: {e}")

        return ExecutionResult(
            success=(total_success > 0),
            operation_type="cancel",
            order_count=total_success,
        )

    def _cancel_old_anti_pin_orders(
        self,
        anti_pin_price_sell: float,
        anti_pin_price_buy: float,
    ) -> None:
        """取消旧的反针对订单（排除新添加的订单）"""
        try:
            current_orders = self.order_manager.client.get_open_orders(
                symbol=self.symbol
            )

            old_anti_pin_orders = []
            price_tolerance = 0.0001

            for order in current_orders:
                order_price = float(order["price"])
                client_order_id = order.get("clientOrderId", "")

                # 跳过新添加的订单
                if client_order_id in self.current_anti_pin_order_ids:
                    continue

                # 通过价格特征识别反针对订单
                is_anti_pin_sell = order["side"] == "SELL" and abs(
                    order_price - anti_pin_price_sell
                ) < price_tolerance
                is_anti_pin_buy = order["side"] == "BUY" and abs(
                    order_price - anti_pin_price_buy
                ) < price_tolerance

                if is_anti_pin_sell or is_anti_pin_buy:
                    old_anti_pin_orders.append(order)

            # 批量取消旧的反针对订单
            if old_anti_pin_orders:
                self.logger.info(
                    f"发现 {len(old_anti_pin_orders)} 个旧的反针对订单，准备取消"
                )
                try:
                    self.order_manager.cancel_orders_batch(orders=old_anti_pin_orders)
                    self.logger.info(
                        f"成功取消 {len(old_anti_pin_orders)} 个旧的反针对订单"
                    )
                except Exception as e:
                    self.logger.error(f"取消旧反针对订单失败: {e}")
            else:
                self.logger.debug("没有发现需要取消的旧反针对订单")

        except Exception as e:
            self.logger.error(f"查询或取消旧反针对订单时出错: {e}")
