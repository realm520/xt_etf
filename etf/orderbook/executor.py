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
# LayerBalanceChecker 已移至 market_making.py 调用层


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
        logger: Optional[logging.Logger] = None,
        stats_print_interval: float = 10.0,  # 统计打印间隔（秒）
        # layer_balance_config 已移至 market_making.py
    ):
        self.order_manager = order_manager
        self.symbol = symbol
        self.strategy_name = strategy_name
        self.max_layer = max_layer  # 保存最大档位数
        self.logger = logger or logging.getLogger(strategy_name)

        # 记录当前周期的反针对订单ID
        self.current_anti_pin_order_ids: List[str] = []

        # 订单统计打印控制（基于时间）
        self.stats_print_interval = stats_print_interval  # 打印间隔（秒）
        self._last_stats_print_time: float = 0.0  # 上次打印时间

        # 分层平衡检查已移至 market_making.py 调用层

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
        order_overflow = False  # 标记是否订单超标
        
        # 按订单类型统计
        order_stats = self._count_orders_by_type(current_orders)
        
        if self.max_layer is not None:
            # 计算告警阈值
            warning_threshold = self.max_layer * 1.2   # 120% 警告
            critical_threshold = self.max_layer * 1.5  # 150% 危急
            
            if current_order_count > critical_threshold:
                self.logger.error(
                    f"🚨 订单数量严重超标: {current_order_count} > {critical_threshold:.0f} "
                    f"(配置: {self.max_layer}档, 危急阈值: 150%) - 暂停添加新订单，优先清理"
                )
                self.logger.error(
                    f"📊 订单类型分布: 做市={order_stats['market_making']}, "
                    f"反针对={order_stats['anti_pin']}, 洗盘={order_stats['wash_trading']}, "
                    f"对冲={order_stats['hedging']}, 未知={order_stats['unknown']}"
                )
                order_overflow = True
            elif current_order_count > warning_threshold:
                self.logger.warning(
                    f"⚠️ 订单数量超标: {current_order_count} > {warning_threshold:.0f} "
                    f"(配置: {self.max_layer}档, 警告阈值: 120%)"
                )
                self.logger.warning(
                    f"📊 订单类型分布: 做市={order_stats['market_making']}, "
                    f"反针对={order_stats['anti_pin']}, 洗盘={order_stats['wash_trading']}, "
                    f"对冲={order_stats['hedging']}, 未知={order_stats['unknown']}"
                )
            else:
                self.logger.debug(
                    f"📊 订单数量正常: {current_order_count}/{self.max_layer} "
                    f"({current_order_count/self.max_layer:.1%}) | "
                    f"做市={order_stats['market_making']}, 反针对={order_stats['anti_pin']}, "
                    f"洗盘={order_stats['wash_trading']}, 对冲={order_stats['hedging']}, 未知={order_stats['unknown']}"
                )

        # === 0.5 定期打印订单详细统计 ===
        self.print_order_stats(current_orders)

        # === 0.55 清理残留洗盘订单 ===
        # 洗盘订单应该立即成交，如果还挂在盘口说明有问题，必须清理
        wash_orders_to_cancel = [
            order for order in current_orders
            if (order.get("clientOrderId") or "").startswith("wash_")
        ]
        if wash_orders_to_cancel:
            self.logger.warning(
                f"🧹 发现 {len(wash_orders_to_cancel)} 个残留洗盘订单，立即清理"
            )
            for order in wash_orders_to_cancel:
                try:
                    self.order_manager.cancel_order(order)
                    self.logger.info(
                        f"✅ 已撤销洗盘订单: {order.get('orderId')} | "
                        f"{order.get('side')} {order.get('origQty')}@{order.get('price')}"
                    )
                except Exception as e:
                    self.logger.error(f"❌ 撤销洗盘订单失败: {order.get('orderId')} - {e}")
            
            # 更新订单统计（排除已撤销的洗盘订单）
            current_orders = [
                o for o in current_orders 
                if not (o.get("clientOrderId") or "").startswith("wash_")
            ]
            order_stats = self._count_orders_by_type(current_orders)

        # === 0.6 买卖平衡检查和修正 ===
        detailed_stats = self._count_orders_by_type_and_side(current_orders)
        current_buy = sum(stats["BUY"] for stats in detailed_stats.values())
        current_sell = sum(stats["SELL"] for stats in detailed_stats.values())
        current_total = current_buy + current_sell
        
        # 🔄 再平衡机制（严重不平衡时自动修复）
        rebalance_add = []
        rebalance_cancel = []
        
        if current_total > 0:
            imbalance = abs(current_buy - current_sell) / current_total
            if imbalance > 0.2:  # 不平衡度超过20%
                self.logger.warning(
                    f"⚠️ 买卖订单不平衡: BUY={current_buy}, SELL={current_sell}, "
                    f"不平衡度={imbalance:.1%}"
                )
                
                # 统计目标订单的买卖分布
                target_buy = sum(1 for o in target_orders if o.get("direction") == "bid")
                target_sell = sum(1 for o in target_orders if o.get("direction") == "ask")
                self.logger.info(
                    f"📊 目标订单分布: BUY={target_buy}, SELL={target_sell}"
                )
                
                # 🔄 触发再平衡（不平衡度>30%时）
                if imbalance > 0.3:
                    rebalance_add, rebalance_cancel = self.rebalance_orders(
                        current_orders=current_orders,
                        target_orders=target_orders,
                        imbalance_threshold=0.3,
                        target_ratio=0.5,
                    )
                    self.logger.info(
                        f"🔄 再平衡计划: 添加 {len(rebalance_add)}, 取消 {len(rebalance_cancel)}"
                    )

        # === 0.7 分层平衡检查已移至 market_making.py ===
        # 检查器在调用 execute_orderbook_update 之前运行，
        # 调整订单已合并到 target_orders 中传入

        # === 1. 订单匹配分析 ===
        optimized_add_orders, optimized_cancel_orders = self._match_orders(
            current_orders, target_orders
        )

        # === 1.5 硬性订单上限保护（修复版：计算所有订单总数）===
        # XT交易所 ORDER_006: 每个交易对最多200个挂单（所有类型订单的总和）
        # 必须计算所有订单类型，不能只计算做市订单
        
        # 初始化变量（用于后续反针对订单保护）
        effective_mm_count = order_stats['market_making']  # 做市订单数（用于反针对保护）
        effective_total_count = sum(order_stats.values())  # 所有订单总数（默认值）
        
        if self.max_layer is not None:
            anti_pin_reserve = 5  # 预留5个槽位给反针对订单
            
            # 统计待取消订单数量（所有类型）
            cancel_stats = self._count_orders_by_type(optimized_cancel_orders)
            total_cancel_count = sum(cancel_stats.values())
            
            # 当前所有订单总数（包括做市、洗盘、对冲等所有类型）
            total_current_count = sum(order_stats.values())
            
            # 净订单数 = 当前总订单 - 待取消订单
            effective_total_count = total_current_count - total_cancel_count
            available_slots = max(0, self.max_layer - effective_total_count - anti_pin_reserve)
            
            # 用于反针对订单保护的做市订单统计
            cancel_mm_count = cancel_stats['market_making']
            effective_mm_count = order_stats['market_making'] - cancel_mm_count
            
            if len(optimized_add_orders) > available_slots:
                original_count = len(optimized_add_orders)
                optimized_add_orders = optimized_add_orders[:available_slots]
                self.logger.warning(
                    f"🔒 硬性上限保护: 截断做市订单 {original_count} → {len(optimized_add_orders)} "
                    f"(总订单={total_current_count}, 待取消={total_cancel_count}, "
                    f"净订单={effective_total_count}, 上限={self.max_layer}, 可用槽位={available_slots}, "
                    f"订单分布: 做市={order_stats['market_making']}, 洗盘={order_stats['wash_trading']}, "
                    f"反针对={order_stats['anti_pin']}, 对冲={order_stats['hedging']})"
                )
            else:
                self.logger.debug(
                    f"📊 订单槽位充足: 总订单={total_current_count}, 待取消={total_cancel_count}, "
                    f"净订单={effective_total_count}, 可用={available_slots}, 需添加={len(optimized_add_orders)}"
                )

        # === 1.6 合并再平衡订单 ===
        if rebalance_add:
            self.logger.info(f"🔄 合并再平衡添加订单: {len(rebalance_add)}")
            optimized_add_orders.extend(rebalance_add)
        if rebalance_cancel:
            # 避免重复取消
            existing_cancel_ids = {o.get("orderId") for o in optimized_cancel_orders}
            new_cancel = [o for o in rebalance_cancel if o.get("orderId") not in existing_cancel_ids]
            self.logger.info(f"🔄 合并再平衡取消订单: {len(new_cancel)}")
            optimized_cancel_orders.extend(new_cancel)

        # 为每个新订单设置clientOrderId和order_purpose
        for order_data in optimized_add_orders:
            # 根据订单类型设置带前缀的clientOrderId
            base_id = self.order_manager.create_temp_id()
            if "order_purpose" not in order_data:
                order_data["order_purpose"] = "market_making"
            
            # 根据order_purpose设置clientOrderId前缀
            purpose = order_data["order_purpose"]
            if purpose == "market_making":
                order_data["clientOrderId"] = f"mm_{base_id}"
            elif purpose == "anti_pin":
                order_data["clientOrderId"] = f"antipin_{base_id}"
            elif purpose == "wash_trading":
                order_data["clientOrderId"] = f"wash_{base_id}"
            elif purpose == "rebalance":
                order_data["clientOrderId"] = f"rebal_{base_id}"
            else:
                order_data["clientOrderId"] = base_id

        # === 2. 识别超范围订单 ===
        out_of_range_orders = self._find_out_of_range_orders(
            current_orders, best_sell, best_buy
        )
        optimized_cancel_orders.extend(out_of_range_orders)

        self.logger.info(
            f"订单操作计划 - 新增: {len(optimized_add_orders)}, "
            f"取消: {len(optimized_cancel_orders)}"
        )

        # === 3. 添加反针对订单（受上限保护）===
        if anti_pin_config:
            anti_pin_orders = self._create_anti_pin_orders(
                best_sell, best_buy, anti_pin_config
            )
            
            # 检查是否有足够槽位添加反针对订单（基于总订单数）
            if self.max_layer is not None:
                # 净总订单数 + 待添加做市订单 + 反针对订单
                total_after_add = effective_total_count + len(optimized_add_orders) + len(anti_pin_orders)
                if total_after_add > self.max_layer:
                    # 计算可用槽位（基于总订单数）
                    remaining_slots = max(0, self.max_layer - effective_total_count - len(optimized_add_orders))
                    if remaining_slots < len(anti_pin_orders):
                        original_antipin_count = len(anti_pin_orders)
                        anti_pin_orders = anti_pin_orders[:remaining_slots]
                        self.logger.warning(
                            f"🔒 反针对订单截断: {original_antipin_count} → {len(anti_pin_orders)} "
                            f"(净订单={effective_total_count}, 待添加做市={len(optimized_add_orders)}, "
                            f"总计将达到: {effective_total_count + len(optimized_add_orders) + len(anti_pin_orders)}/{self.max_layer})"
                        )
            
            optimized_add_orders.extend(anti_pin_orders)

        # === 4. 执行订单操作 ===
        successful_add = 0
        failed_add = 0
        successful_cancel = 0
        failed_cancel = 0
        
        # 保存原始数量用于统计
        total_add_planned = len(optimized_add_orders)
        total_cancel_planned = len(optimized_cancel_orders)

        # 订单超标时：改为先删后加，且限制新增数量
        if order_overflow:
            self.logger.warning(
                f"🛑 订单超标保护启动: 先清理 {len(optimized_cancel_orders)} 个订单，"
                f"暂停添加 {len(optimized_add_orders)} 个新订单"
            )
            
            # 步骤1: 先批量取消旧订单（清理超量）
            if optimized_cancel_orders:
                cancel_result = self._execute_cancel_orders(optimized_cancel_orders)
                successful_cancel = cancel_result.order_count if cancel_result.success else 0
                failed_cancel = len(optimized_cancel_orders) - successful_cancel
            
            # 步骤2: 等待取消生效
            if optimized_cancel_orders:
                time.sleep(0.2)
            
            # 步骤3: 跳过添加新订单（等下一轮再添加）
            failed_add = len(optimized_add_orders)
            optimized_add_orders = []  # 清空，跳过添加
            
        else:
            # 正常模式：先加后删
            # 步骤1: 批量添加新订单
            if optimized_add_orders:
                add_result = self._execute_add_orders(optimized_add_orders)
                successful_add = add_result.order_count if add_result.success else 0
                failed_add = len(optimized_add_orders) - successful_add

            # 步骤2: 等待新订单上盘
            if optimized_add_orders:
                time.sleep(0.1)

            # 步骤3: 批量取消旧订单（正常模式下，order_overflow时已在前面执行）
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

        # === 5.5 买卖差价验证和修复 ===
        spread_verify_result = None
        if best_sell > 0 and best_buy > 0:
            # 等待订单上盘后再验证
            time.sleep(0.2)
            
            spread_verify_result = self.verify_and_repair_spread(
                target_best_buy=best_buy,
                target_best_sell=best_sell,
            )
            
            if not spread_verify_result.get("spread_ok"):
                self.logger.warning(
                    f"⚠️ 差价验证: {spread_verify_result.get('message')} | "
                    f"修复: {'成功' if spread_verify_result.get('repaired') else '失败'}"
                )

        # === 6. 生成执行总结 ===
        execution_time = time.time() - start_time

        summary = ExecutionSummary(
            total_add=total_add_planned,
            total_cancel=total_cancel_planned,
            successful_add=successful_add,
            successful_cancel=successful_cancel,
            failed_add=failed_add,
            failed_cancel=failed_cancel,
            execution_time=execution_time,
        )

        self.logger.info(summary.summary_text())

        return summary

    def _count_orders_by_type(
        self, orders: List[Dict[str, Any]]
    ) -> Dict[str, int]:
        """按订单类型统计订单数量
        
        根据 clientOrderId 前缀判断订单类型：
        - mm_: market_making (做市订单)
        - antipin_: anti_pin (反针对订单)
        - wash_: wash_trading (洗盘订单)
        - 其他: unknown (未知类型，可能是旧版纯数字ID)
        
        Returns:
            Dict: 各类型订单数量统计
        """
        stats = {
            "market_making": 0,
            "anti_pin": 0,
            "wash_trading": 0,
            "hedging": 0,
            "rebalance": 0,
            "unknown": 0,
        }
        
        for order in orders:
            client_order_id = order.get("clientOrderId", "") or ""
            
            if client_order_id.startswith("mm_"):
                stats["market_making"] += 1
            elif client_order_id.startswith("antipin_"):
                stats["anti_pin"] += 1
            elif client_order_id.startswith("wash_"):
                stats["wash_trading"] += 1
            elif client_order_id.startswith("hedge_"):
                stats["hedging"] += 1
            elif client_order_id.startswith("rebal_"):
                stats["rebalance"] += 1
            else:
                stats["unknown"] += 1
        
        return stats

    def _count_orders_by_type_and_side(
        self, orders: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, int]]:
        """按订单类型和方向统计订单数量

        根据 clientOrderId 前缀判断订单类型，并按 side 分类：
        - mm_: market_making (做市订单)
        - antipin_: anti_pin (反针对订单)
        - wash_: wash_trading (洗盘订单)
        - hedge_: hedging (对冲订单)
        - 其他: unknown (未知类型，可能是旧版纯数字ID)

        Returns:
            Dict: 嵌套结构 {type: {side: count, 'total': count}}
            示例: {
                'market_making': {'BUY': 10, 'SELL': 8, 'total': 18},
                'anti_pin': {'BUY': 2, 'SELL': 2, 'total': 4},
                ...
            }
        """
        order_types = ["market_making", "anti_pin", "wash_trading", "hedging", "rebalance", "unknown"]
        stats = {
            order_type: {"BUY": 0, "SELL": 0, "total": 0}
            for order_type in order_types
        }

        for order in orders:
            client_order_id = order.get("clientOrderId", "") or ""
            side = order.get("side", "UNKNOWN")

            # 确定订单类型
            if client_order_id.startswith("mm_"):
                order_type = "market_making"
            elif client_order_id.startswith("antipin_"):
                order_type = "anti_pin"
            elif client_order_id.startswith("wash_"):
                order_type = "wash_trading"
            elif client_order_id.startswith("hedge_"):
                order_type = "hedging"
            elif client_order_id.startswith("rebal_"):
                order_type = "rebalance"
            else:
                order_type = "unknown"

            # 统计
            if side in ["BUY", "SELL"]:
                stats[order_type][side] += 1
            stats[order_type]["total"] += 1

        return stats

    def print_order_stats(
        self,
        current_orders: List[Dict[str, Any]],
        force: bool = False
    ) -> None:
        """定期打印未结束订单的统计信息（基于时间间隔）

        Args:
            current_orders: 当前挂单列表
            force: 是否强制打印（忽略时间间隔）
        """
        import time as time_module

        current_time = time_module.time()

        # 检查是否应该打印（达到时间间隔或强制）
        if not force and (current_time - self._last_stats_print_time) < self.stats_print_interval:
            return

        # 更新上次打印时间
        self._last_stats_print_time = current_time

        # 获取详细统计
        detailed_stats = self._count_orders_by_type_and_side(current_orders)

        # 计算本地订单总数
        local_total = sum(stats["total"] for stats in detailed_stats.values())
        local_buy = sum(stats["BUY"] for stats in detailed_stats.values())
        local_sell = sum(stats["SELL"] for stats in detailed_stats.values())

        # 查询交易所实际订单数
        exchange_total = 0
        exchange_buy = 0
        exchange_sell = 0
        exchange_status = "OK"

        try:
            exchange_orders = self.order_manager.client.get_open_orders(symbol=self.symbol)
            exchange_total = len(exchange_orders)
            for order in exchange_orders:
                if order.get("side") == "BUY":
                    exchange_buy += 1
                else:
                    exchange_sell += 1
        except Exception as e:
            exchange_status = f"查询失败: {str(e)[:30]}"

        # 计算本地与交易所差异
        diff_total = local_total - exchange_total
        diff_indicator = ""
        if diff_total > 0:
            diff_indicator = f" ⚠️+{diff_total}"
        elif diff_total < 0:
            diff_indicator = f" ⚠️{diff_total}"

        # 计算买卖不平衡度
        buy_sell_diff = abs(local_buy - local_sell)
        imbalance_ratio = buy_sell_diff / max(local_total, 1) * 100
        imbalance_indicator = ""
        if imbalance_ratio > 20:  # 不平衡度超过20%
            imbalance_indicator = f" ⚠️不平衡{imbalance_ratio:.0f}%"
        elif imbalance_ratio > 10:  # 不平衡度超过10%
            imbalance_indicator = f" 📊偏差{imbalance_ratio:.0f}%"

        # 构建打印内容
        logging.info(
            f"📊 ============ 未结束订单统计 ============"
        )
        logging.info(
            f"📊 本地订单: {local_total} (BUY={local_buy}, SELL={local_sell}){imbalance_indicator}"
        )

        if exchange_status == "OK":
            # 交易所买卖不平衡检查
            ex_diff = abs(exchange_buy - exchange_sell)
            ex_imbalance = ex_diff / max(exchange_total, 1) * 100
            ex_imbalance_ind = ""
            if ex_imbalance > 20:
                ex_imbalance_ind = f" ⚠️不平衡{ex_imbalance:.0f}%"
            elif ex_imbalance > 10:
                ex_imbalance_ind = f" 📊偏差{ex_imbalance:.0f}%"
            
            logging.info(
                f"📊 交易所订单: {exchange_total} (BUY={exchange_buy}, SELL={exchange_sell}){diff_indicator}{ex_imbalance_ind}"
            )
        else:
            logging.info(
                f"📊 交易所订单: {exchange_status}"
            )

        # 按类型打印（只打印有订单的类型）
        type_names = {
            "market_making": "做市",
            "anti_pin": "反针对",
            "wash_trading": "洗盘",
            "hedging": "对冲",
            "rebalance": "再平衡",
            "unknown": "未知"
        }

        for order_type, stats in detailed_stats.items():
            if stats["total"] > 0:
                type_name = type_names.get(order_type, order_type)
                logging.info(
                    f"📊   {type_name}: {stats['total']:3d} "
                    f"(BUY={stats['BUY']:3d}, SELL={stats['SELL']:3d})"
                )

        logging.info(
            f"📊 =========================================="
        )

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

        # 创建反针对卖单（使用 antipin_ 前缀）
        sell_base_id = self.order_manager.create_temp_id()
        sell_client_order_id = f"antipin_{sell_base_id}"
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

        # 创建反针对买单（使用 antipin_ 前缀）
        buy_base_id = self.order_manager.create_temp_id()
        buy_client_order_id = f"antipin_{buy_base_id}"
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
                else:
                    self.logger.warning(f"⚠️ 添加订单被跳过: {len(batch)} 个 (熔断器或其他原因)")
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
                else:
                    self.logger.warning(f"⚠️ 取消订单失败: {len(batch)} 个, API返回: {res}")
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

    def rebalance_orders(
        self,
        current_orders: List[Dict[str, Any]],
        target_orders: List[Dict[str, Any]],
        imbalance_threshold: float = 0.3,
        target_ratio: float = 0.5,
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """订单再平衡机制
        
        当检测到买卖订单严重不平衡时，自动调整订单分布。
        同时处理买卖两个方向的平衡问题。
        
        策略：
        1. 计算当前买卖比例和目标买卖比例
        2. 如果不平衡超过阈值，同时调整两侧订单
        3. 多的一侧：清理远离净值的订单
        4. 少的一侧：从目标订单中补充靠近净值的订单
        
        Args:
            current_orders: 当前订单列表（来自交易所）
            target_orders: 目标订单列表（算法生成）
            imbalance_threshold: 不平衡触发阈值（默认30%）
            target_ratio: 目标买卖比例（默认0.5，即50%买50%卖）
            
        Returns:
            Tuple[需要添加的订单, 需要取消的订单]
        """
        # 1. 统计当前买卖订单
        current_buy = [o for o in current_orders if o.get("side") == "BUY"]
        current_sell = [o for o in current_orders if o.get("side") == "SELL"]
        total_current = len(current_orders)
        
        if total_current == 0:
            self.logger.debug("当前无订单，跳过再平衡")
            return [], []
        
        buy_ratio = len(current_buy) / total_current
        sell_ratio = len(current_sell) / total_current
        imbalance = abs(buy_ratio - target_ratio)
        
        self.logger.debug(
            f"📊 买卖平衡检查: BUY={len(current_buy)} ({buy_ratio:.1%}), "
            f"SELL={len(current_sell)} ({sell_ratio:.1%}), 不平衡度={imbalance:.1%}"
        )
        
        # 2. 检查是否需要再平衡
        if imbalance < imbalance_threshold:
            self.logger.debug(f"买卖平衡正常（不平衡度 {imbalance:.1%} < 阈值 {imbalance_threshold:.1%}）")
            return [], []
        
        self.logger.warning(
            f"⚠️ 买卖订单严重不平衡！BUY={len(current_buy)}, SELL={len(current_sell)}, "
            f"不平衡度={imbalance:.1%}（阈值: {imbalance_threshold:.1%}）"
        )
        
        # 3. 计算目标订单数量（维持总量不变，调整比例）
        target_buy_count = int(total_current * target_ratio)
        target_sell_count = total_current - target_buy_count
        
        add_orders = []
        cancel_orders = []
        
        # 4. 获取目标订单
        target_buy_orders = [o for o in target_orders if o.get("direction") == "bid"]
        target_sell_orders = [o for o in target_orders if o.get("direction") == "ask"]
        
        # 按价格排序（买单降序，卖单升序 - 优先处理靠近净值的订单）
        target_buy_orders.sort(key=lambda o: float(o.get("price", 0)), reverse=True)
        target_sell_orders.sort(key=lambda o: float(o.get("price", 0)))
        
        # 5. 处理买单
        buy_diff = target_buy_count - len(current_buy)
        if buy_diff > 0:
            # 买单不足，需要补充
            for order in target_buy_orders[:buy_diff]:
                price = float(order["price"])
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": price,
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "rebalance",
                    # 添加optimize_order_matching所需的字段
                    "amount": order.get("amount", order.get("quantity")),
                    "direction": "bid",
                    "min_price": order.get("min_price", price * 0.9999),
                    "max_price": order.get("max_price", price * 1.0001),
                })
            self.logger.info(f"🔄 再平衡: 补充 {buy_diff} 个买单")
        elif buy_diff < 0:
            # 买单过多，清理远端买单
            need_cancel = abs(buy_diff)
            mm_buy = [
                o for o in current_buy 
                if (o.get("clientOrderId", "") or "").startswith("mm_")
            ]
            # 按价格升序（先清理最低价的买单，即离净值最远的）
            mm_buy.sort(key=lambda o: float(o.get("price", 0)))
            cancel_orders.extend(mm_buy[:need_cancel])
            self.logger.info(f"🔄 再平衡: 清理 {min(need_cancel, len(mm_buy))} 个多余买单")
        
        # 6. 处理卖单
        sell_diff = target_sell_count - len(current_sell)
        if sell_diff > 0:
            # 卖单不足，需要补充
            for order in target_sell_orders[:sell_diff]:
                price = float(order["price"])
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "SELL",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": price,
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "rebalance",
                    # 添加optimize_order_matching所需的字段
                    "amount": order.get("amount", order.get("quantity")),
                    "direction": "ask",
                    "min_price": order.get("min_price", price * 0.9999),
                    "max_price": order.get("max_price", price * 1.0001),
                })
            self.logger.info(f"🔄 再平衡: 补充 {sell_diff} 个卖单")
        elif sell_diff < 0:
            # 卖单过多，清理远端卖单
            need_cancel = abs(sell_diff)
            mm_sell = [
                o for o in current_sell 
                if (o.get("clientOrderId", "") or "").startswith("mm_")
            ]
            # 按价格降序（先清理最高价的卖单，即离净值最远的）
            mm_sell.sort(key=lambda o: float(o.get("price", 0)), reverse=True)
            cancel_orders.extend(mm_sell[:need_cancel])
            self.logger.info(f"🔄 再平衡: 清理 {min(need_cancel, len(mm_sell))} 个多余卖单")
        
        # 7. 汇总日志
        if add_orders or cancel_orders:
            self.logger.info(
                f"🔄 再平衡结果: "
                f"添加 {len([o for o in add_orders if o['side']=='BUY'])} 买单 + "
                f"{len([o for o in add_orders if o['side']=='SELL'])} 卖单, "
                f"取消 {len([o for o in cancel_orders if o.get('side')=='BUY'])} 买单 + "
                f"{len([o for o in cancel_orders if o.get('side')=='SELL'])} 卖单"
            )
        
        return add_orders, cancel_orders

    # ==================== 买卖差价验证和修复 ====================
    
    def _get_actual_spread_from_orders(
        self, orders: List[Dict[str, Any]]
    ) -> Tuple[Optional[float], Optional[float], Optional[float]]:
        """从订单列表计算实际买卖一和差价
        
        Args:
            orders: 当前订单列表
            
        Returns:
            Tuple[best_bid, best_ask, spread_ratio]:
            - best_bid: 买一价格（最高买价），无买单时为None
            - best_ask: 卖一价格（最低卖价），无卖单时为None
            - spread_ratio: 差价比例 = (best_ask - best_bid) / best_bid，
                           买卖一有任一缺失时为None
        """
        buy_prices = []
        sell_prices = []
        
        for order in orders:
            price = float(order.get("price", 0))
            side = order.get("side", "")
            
            if price <= 0:
                continue
                
            if side == "BUY":
                buy_prices.append(price)
            elif side == "SELL":
                sell_prices.append(price)
        
        # 计算买一（最高买价）
        best_bid = max(buy_prices) if buy_prices else None
        # 计算卖一（最低卖价）
        best_ask = min(sell_prices) if sell_prices else None
        
        # 计算差价比例（需要买卖双方都有订单）
        spread_ratio = None
        if best_bid is not None and best_ask is not None and best_bid > 0:
            spread_ratio = (best_ask - best_bid) / best_bid
        
        return best_bid, best_ask, spread_ratio
    
    def verify_and_repair_spread(
        self,
        target_best_buy: float,
        target_best_sell: float,
    ) -> Dict[str, Any]:
        """验证并修复买卖差价（严格模式：差价只能≤目标）
        
        规则：实际差价必须≤目标差价，否则立即修复
        
        执行流程：
        1. 获取当前市场订单
        2. 计算实际买卖一和差价
        3. 检查：实际买一>=目标买一 且 实际卖一<=目标卖一
        4. 不满足条件则立即补单修复
        
        Args:
            target_best_buy: 目标买一价格
            target_best_sell: 目标卖一价格
            
        Returns:
            Dict: 验证和修复结果
        """
        result = {
            "checked": False,
            "spread_ok": True,
            "actual_best_bid": None,
            "actual_best_ask": None,
            "actual_spread_ratio": None,
            "target_spread_ratio": None,
            "repaired": False,
            "repair_orders": 0,
            "message": "",
        }
        
        # 1. 获取当前市场订单
        try:
            current_orders = self.order_manager.client.get_open_orders(
                symbol=self.symbol
            )
        except Exception as e:
            self.logger.error(f"获取订单失败，无法验证差价: {e}")
            result["message"] = f"获取订单失败: {e}"
            return result
        
        result["checked"] = True
        
        # 2. 计算实际买卖差价
        actual_bid, actual_ask, actual_spread = self._get_actual_spread_from_orders(
            current_orders
        )
        
        result["actual_best_bid"] = actual_bid
        result["actual_best_ask"] = actual_ask
        result["actual_spread_ratio"] = actual_spread
        
        # 3. 计算目标差价
        target_spread_ratio = (target_best_sell - target_best_buy) / target_best_buy if target_best_buy > 0 else 0
        result["target_spread_ratio"] = target_spread_ratio
        
        # 4. 检查订单完整性
        if actual_bid is None or actual_ask is None:
            buy_count = len([o for o in current_orders if o.get('side') == 'BUY'])
            sell_count = len([o for o in current_orders if o.get('side') == 'SELL'])
            self.logger.warning(
                f"⚠️ 订单簿不完整: 买单={buy_count}, 卖单={sell_count}，需要修复"
            )
            result["spread_ok"] = False
            
            # 立即修复
            repair_result = self._repair_spread(
                current_orders=current_orders,
                actual_bid=actual_bid or 0,
                actual_ask=actual_ask or float('inf'),
                target_best_buy=target_best_buy,
                target_best_sell=target_best_sell,
            )
            result["repaired"] = repair_result["success"]
            result["repair_orders"] = repair_result["orders_added"]
            result["message"] = f"订单不完整，已修复: {repair_result['message']}"
            return result
        
        # 5. 严格检查：实际差价必须<=目标差价
        # 即：实际买一>=目标买一 且 实际卖一<=目标卖一
        bid_ok = actual_bid >= target_best_buy
        ask_ok = actual_ask <= target_best_sell
        
        self.logger.info(
            f"📊 差价验证: 实际买1={actual_bid:.6f}{'✓' if bid_ok else '✗'}, "
            f"卖1={actual_ask:.6f}{'✓' if ask_ok else '✗'} | "
            f"目标买1={target_best_buy:.6f}, 卖1={target_best_sell:.6f} | "
            f"实际差价={actual_spread*100:.4f}%, 目标差价={target_spread_ratio*100:.4f}%"
        )
        
        # 6. 判断是否需要修复
        if not bid_ok or not ask_ok:
            result["spread_ok"] = False
            issues = []
            if not bid_ok:
                issues.append(f"买一偏低({actual_bid:.6f}<{target_best_buy:.6f})")
            if not ask_ok:
                issues.append(f"卖一偏高({actual_ask:.6f}>{target_best_sell:.6f})")
            
            self.logger.warning(f"🚨 差价异常: {', '.join(issues)}，立即修复")
            
            # 立即修复
            repair_result = self._repair_spread(
                current_orders=current_orders,
                actual_bid=actual_bid,
                actual_ask=actual_ask,
                target_best_buy=target_best_buy,
                target_best_sell=target_best_sell,
            )
            result["repaired"] = repair_result["success"]
            result["repair_orders"] = repair_result["orders_added"]
            result["message"] = repair_result["message"]
        else:
            result["message"] = "差价正常"
        
        return result
    
    def _repair_spread(
        self,
        current_orders: List[Dict[str, Any]],
        actual_bid: float,
        actual_ask: float,
        target_best_buy: float,
        target_best_sell: float,
    ) -> Dict[str, Any]:
        """修复买卖差价（增强版：强制清理偏差订单 + 补充目标价位订单）
        
        修复策略：
        1. 如果实际买一 < 目标买一：补充买单到目标价位
        2. 如果实际卖一 > 目标卖一：
           a. 撤销所有高于目标卖一的卖单（强制清理）
           b. 补充卖单到目标价位
        
        Args:
            current_orders: 当前订单列表
            actual_bid: 实际买一
            actual_ask: 实际卖一
            target_best_buy: 目标买一
            target_best_sell: 目标卖一
            
        Returns:
            Dict: 修复结果
        """
        result = {
            "success": False,
            "orders_added": 0,
            "orders_cancelled": 0,
            "message": "",
        }
        
        repair_orders = []
        cancel_orders = []
        
        # 获取精度配置
        price_precision = 6  # 默认值
        quantity_precision = 4  # 默认值
        
        if hasattr(self.order_manager, 'symbol_config_manager') and self.order_manager.symbol_config_manager:
            price_precision = self.order_manager.symbol_config_manager.get_price_precision(self.symbol) or 6
            quantity_precision = self.order_manager.symbol_config_manager.get_quantity_precision(self.symbol) or 4
        
        # 计算修复数量（使用最小有效数量）
        min_quantity = 10 ** (-quantity_precision) * 10  # 最小数量的10倍，确保有效
        
        # === 修复买单：实际买一 < 目标买一 ===
        if actual_bid < target_best_buy:
            repair_price = round(target_best_buy, price_precision)
            repair_qty = round(min_quantity, quantity_precision)
            
            repair_orders.append({
                "symbol": self.symbol,
                "side": "BUY",
                "type": "LIMIT",
                "price": str(repair_price),
                "quantity": str(repair_qty),
                "timeInForce": "GTC",
                "clientOrderId": f"repair_bid_{self.order_manager.create_temp_id()}",
            })
            self.logger.info(
                f"🔧 补充买单: 价格={repair_price}, 数量={repair_qty} "
                f"(实际买1={actual_bid:.6f} → 目标={target_best_buy:.6f})"
            )
        
        # === 修复卖单：实际卖一 > 目标卖一（增强版） ===
        if actual_ask > target_best_sell:
            # 计算偏差程度
            deviation = (actual_ask - target_best_sell) / target_best_sell
            self.logger.warning(
                f"🚨 卖一偏高: 实际={actual_ask:.6f}, 目标={target_best_sell:.6f}, "
                f"偏差={deviation*100:.2f}%"
            )
            
            # 策略1：找出并撤销所有高于目标卖一的卖单（强制清理）
            max_allowed_ask = target_best_sell * 1.002  # 允许0.2%容差
            high_sell_orders = [
                o for o in current_orders 
                if o.get("side") == "SELL" 
                and float(o.get("price", 0)) > max_allowed_ask
                and o.get("state") != "PARTIALLY_FILLED"  # 不撤销部分成交的订单
            ]
            
            if high_sell_orders:
                # 按价格降序排序，优先撤销价格最高的
                high_sell_orders.sort(key=lambda o: float(o.get("price", 0)), reverse=True)
                
                # 撤销偏高的卖单（最多撤销10个，避免一次撤销太多）
                orders_to_cancel = high_sell_orders[:10]
                cancel_orders.extend(orders_to_cancel)
                
                self.logger.info(
                    f"🧹 识别到 {len(high_sell_orders)} 个偏高卖单，将撤销 {len(orders_to_cancel)} 个 "
                    f"(价格 > {max_allowed_ask:.6f})"
                )
                
                for order in orders_to_cancel[:3]:  # 只打印前3个
                    self.logger.debug(
                        f"   - 撤销: {order.get('orderId')} @ {order.get('price')} "
                        f"数量={order.get('origQty')}"
                    )
            
            # 策略2：补充卖单到目标价位
            repair_price = round(target_best_sell, price_precision)
            repair_qty = round(min_quantity, quantity_precision)
            
            repair_orders.append({
                "symbol": self.symbol,
                "side": "SELL",
                "type": "LIMIT",
                "price": str(repair_price),
                "quantity": str(repair_qty),
                "timeInForce": "GTC",
                "clientOrderId": f"repair_ask_{self.order_manager.create_temp_id()}",
            })
            self.logger.info(
                f"🔧 补充卖单: 价格={repair_price}, 数量={repair_qty} "
                f"(实际卖1={actual_ask:.6f} → 目标={target_best_sell:.6f})"
            )
        
        # === 执行撤销订单 ===
        if cancel_orders:
            try:
                cancelled_count = 0
                for order in cancel_orders:
                    try:
                        self.order_manager.cancel_order(order)
                        cancelled_count += 1
                    except Exception as e:
                        self.logger.error(f"撤销订单失败: {order.get('orderId')} - {e}")
                
                result["orders_cancelled"] = cancelled_count
                self.logger.info(f"✅ 成功撤销 {cancelled_count}/{len(cancel_orders)} 个偏高订单")
                
            except Exception as e:
                self.logger.error(f"批量撤销异常: {e}")
        
        # === 执行修复订单 ===
        if not repair_orders:
            if cancel_orders:
                result["message"] = f"已撤销 {result['orders_cancelled']} 个偏高订单"
                result["success"] = True
            else:
                result["message"] = "无需修复"
                result["success"] = True
            return result
        
        try:
            # 批量下单
            res = self.order_manager.client.batch_order(repair_orders)
            
            if res:
                # batch_order 返回格式: {'batchId': '...', 'items': [{'orderId': '...', 'rejected': False}, ...]}
                items = res.get("items", []) if isinstance(res, dict) else res
                
                # 统计成功订单数量
                success_count = 0
                for item in items:
                    if isinstance(item, dict):
                        # 标准格式: {'orderId': '...', 'rejected': False}
                        if item.get("orderId") and not item.get("rejected", False):
                            success_count += 1
                    elif isinstance(item, str) and item.isdigit():
                        # 兼容旧格式：订单ID字符串
                        success_count += 1
                
                result["success"] = success_count > 0
                result["orders_added"] = success_count
                result["message"] = (
                    f"修复完成: 添加 {success_count}/{len(repair_orders)} 单, "
                    f"撤销 {result['orders_cancelled']} 单"
                )
                self.logger.info(f"✅ {result['message']}")
                
                # 调试日志：记录返回格式
                if success_count != len(repair_orders):
                    self.logger.debug(f"修复订单返回详情: {res}")
            else:
                result["message"] = "修复下单失败"
                self.logger.error(f"❌ {result['message']}")
                
        except Exception as e:
            result["message"] = f"修复异常: {e}"
            self.logger.error(f"❌ {result['message']}")
        
        return result

    # ==================== 分层订单检查与调整 ====================

    def _analyze_layer_orders(
        self, orders: List[Dict[str, Any]], nav: float
    ) -> Dict[str, Dict[str, Any]]:
        """分析各层订单情况
        
        将订单按距离NAV的百分比分为三层:
        - near: 近盘口 (0-0.5%)
        - mid: 中盘口 (0.5%-2%)
        - far: 远盘口 (2%-10%)
        
        Args:
            orders: 当前订单列表
            nav: 当前净值
            
        Returns:
            Dict: 各层统计数据
        """
        layers = {
            "near": {"range": (0, 0.005), "orders": [], "buy": [], "sell": []},
            "mid": {"range": (0.005, 0.02), "orders": [], "buy": [], "sell": []},
            "far": {"range": (0.02, 0.10), "orders": [], "buy": [], "sell": []},
        }

        for order in orders:
            price = float(order.get("price", 0))
            if price <= 0 or nav <= 0:
                continue
            
            distance = abs(price - nav) / nav
            side = order.get("side", "")

            for layer_name, layer_data in layers.items():
                min_d, max_d = layer_data["range"]
                if min_d <= distance < max_d:
                    layer_data["orders"].append(order)
                    if side == "BUY":
                        layer_data["buy"].append(order)
                    elif side == "SELL":
                        layer_data["sell"].append(order)
                    break

        # 计算统计数据
        for layer_name, data in layers.items():
            data["buy_count"] = len(data["buy"])
            data["sell_count"] = len(data["sell"])
            data["buy_depth"] = sum(
                float(o.get("price", 0)) * float(o.get("quantity", 0)) 
                for o in data["buy"]
            )
            data["sell_depth"] = sum(
                float(o.get("price", 0)) * float(o.get("quantity", 0)) 
                for o in data["sell"]
            )
            data["imbalance"] = self._calc_layer_imbalance(
                data["buy_count"], data["sell_count"]
            )

            # 计算档位密度（平均价格间隔比例）
            if len(data["buy"]) > 1:
                buy_prices = sorted(
                    [float(o.get("price", 0)) for o in data["buy"]], 
                    reverse=True
                )
                data["buy_density"] = self._calc_price_density(buy_prices, nav)
            else:
                data["buy_density"] = 0
                
            if len(data["sell"]) > 1:
                sell_prices = sorted(
                    [float(o.get("price", 0)) for o in data["sell"]]
                )
                data["sell_density"] = self._calc_price_density(sell_prices, nav)
            else:
                data["sell_density"] = 0

        return layers

    def _calc_layer_imbalance(self, buy_count: int, sell_count: int) -> float:
        """计算买卖不平衡度"""
        total = buy_count + sell_count
        if total == 0:
            return 0
        return abs(buy_count - sell_count) / total

    def _calc_price_density(self, prices: List[float], nav: float) -> float:
        """计算平均档位密度（相邻价格间隔占NAV的比例）
        
        返回值越小表示档位越紧密，越大表示档位越稀疏
        """
        if len(prices) < 2 or nav <= 0:
            return 0
        
        total_gap = 0
        for i in range(1, len(prices)):
            gap = abs(prices[i] - prices[i-1]) / nav
            total_gap += gap
        
        return total_gap / (len(prices) - 1)

    def _print_layer_stats(self, layer_analysis: Dict[str, Dict[str, Any]]) -> None:
        """打印分层订单统计"""
        self.logger.info("📊 ============ 分层订单统计 ============")

        layer_names = {"near": "近盘口", "mid": "中盘口", "far": "远盘口"}
        
        for layer_name in ["near", "mid", "far"]:
            data = layer_analysis[layer_name]
            total = data["buy_count"] + data["sell_count"]
            
            if total == 0:
                status = "❌ 无订单"
            elif data["imbalance"] > 0.4:
                status = f"🚨 严重不平衡{data['imbalance']:.0%}"
            elif data["imbalance"] > 0.3:
                status = f"⚠️ 不平衡{data['imbalance']:.0%}"
            else:
                status = "✅"

            layer_cn = layer_names[layer_name]
            self.logger.info(
                f"📊 {layer_cn}: {status} "
                f"BUY={data['buy_count']}({data['buy_depth']:.0f}U) "
                f"SELL={data['sell_count']}({data['sell_depth']:.0f}U)"
            )

        self.logger.info("📊 ==========================================")

    def _filter_target_by_layer(
        self, 
        target_orders: List[Dict[str, Any]], 
        layer_name: str, 
        nav: float
    ) -> List[Dict[str, Any]]:
        """筛选属于指定层级的目标订单"""
        layer_ranges = {
            "near": (0, 0.005),
            "mid": (0.005, 0.02),
            "far": (0.02, 0.10),
        }
        
        min_d, max_d = layer_ranges.get(layer_name, (0, 1))
        filtered = []
        
        for order in target_orders:
            price = float(order.get("price", 0))
            if price <= 0 or nav <= 0:
                continue
            distance = abs(price - nav) / nav
            if min_d <= distance < max_d:
                filtered.append(order)
        
        return filtered

    def _adjust_layer(
        self,
        layer_name: str,
        layer_data: Dict[str, Any],
        target_orders: List[Dict[str, Any]],
        nav: float,
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """调整单层订单，确保符合该层目标
        
        Args:
            layer_name: 层级名称 (near/mid/far)
            layer_data: 该层当前订单统计
            target_orders: 该层目标订单
            nav: 当前净值
            config: 配置参数
            
        Returns:
            Tuple[需要添加的订单, 需要取消的订单]
        """
        if layer_name == "near":
            return self._adjust_near_book(layer_data, target_orders, nav, config)
        elif layer_name == "mid":
            return self._adjust_mid_book(layer_data, target_orders, nav, config)
        elif layer_name == "far":
            return self._adjust_far_book(layer_data, target_orders, nav, config)
        else:
            return [], []

    def _adjust_near_book(
        self,
        layer_data: Dict[str, Any],
        target_orders: List[Dict[str, Any]],
        nav: float,
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """近盘口调整：买卖一 + 紧密档位 + 合理深度
        
        近盘口是最重要的区域，需要确保：
        1. 买卖一存在且价格合理
        2. 价差在配置范围内
        3. 档位紧密（间隔小）
        4. 深度足够
        5. 买卖平衡
        """
        add_orders = []
        cancel_orders = []
        
        bid_ask_spread = config.get("bid_ask_spread", 0.008)
        near_min_depth = config.get("near_min_depth", 100)
        max_imbalance = config.get("near_max_imbalance", 0.3)
        max_density = config.get("near_max_density", 0.002)  # 最大间隔0.2%

        # 1. 检查买卖一
        best_buy = max(
            [float(o.get("price", 0)) for o in layer_data["buy"]], 
            default=0
        )
        best_sell = min(
            [float(o.get("price", float('inf'))) for o in layer_data["sell"]], 
            default=float('inf')
        )

        target_buy1 = nav * (1 - bid_ask_spread / 2)
        target_sell1 = nav * (1 + bid_ask_spread / 2)

        # 买一检查
        if not best_buy or abs(best_buy - target_buy1) / nav > bid_ask_spread:
            self.logger.warning(
                f"🔧 近盘口: 买一异常 实际={best_buy:.6f} 目标={target_buy1:.6f}"
            )
            add_orders.append(self._create_layer_order("BUY", target_buy1, nav, config))

        # 卖一检查
        if best_sell == float('inf') or abs(best_sell - target_sell1) / nav > bid_ask_spread:
            self.logger.warning(
                f"🔧 近盘口: 卖一异常 实际={best_sell:.6f} 目标={target_sell1:.6f}"
            )
            add_orders.append(self._create_layer_order("SELL", target_sell1, nav, config))

        # 2. 检查价差
        if best_buy > 0 and best_sell < float('inf'):
            spread = (best_sell - best_buy) / nav
            if spread > bid_ask_spread * 1.5:
                self.logger.warning(
                    f"🔧 近盘口: 价差过大 {spread:.2%} > 目标{bid_ask_spread:.2%}"
                )
                # 补充中间价格订单收窄价差
                mid_price = (best_buy + best_sell) / 2
                add_orders.append(self._create_layer_order("BUY", mid_price * 0.999, nav, config))
                add_orders.append(self._create_layer_order("SELL", mid_price * 1.001, nav, config))

        # 3. 检查档位密度（近盘口要求紧密）
        if layer_data.get("buy_density", 0) > max_density and layer_data["buy_count"] < 10:
            self.logger.info("📊 近盘口: 买盘档位稀疏，补充订单")
            near_buy_targets = [
                o for o in target_orders 
                if o.get("direction") == "bid"
            ]
            for order in near_buy_targets[:3]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        if layer_data.get("sell_density", 0) > max_density and layer_data["sell_count"] < 10:
            self.logger.info("📊 近盘口: 卖盘档位稀疏，补充订单")
            near_sell_targets = [
                o for o in target_orders 
                if o.get("direction") == "ask"
            ]
            for order in near_sell_targets[:3]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "SELL",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        # 4. 检查深度
        if layer_data["buy_depth"] < near_min_depth:
            self.logger.warning(
                f"🔧 近盘口: 买盘深度不足 {layer_data['buy_depth']:.0f}U < {near_min_depth}U"
            )
            # 从目标订单补充
            for order in [o for o in target_orders if o.get("direction") == "bid"][:2]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        if layer_data["sell_depth"] < near_min_depth:
            self.logger.warning(
                f"🔧 近盘口: 卖盘深度不足 {layer_data['sell_depth']:.0f}U < {near_min_depth}U"
            )
            for order in [o for o in target_orders if o.get("direction") == "ask"][:2]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "SELL",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        # 5. 检查买卖平衡
        if layer_data["imbalance"] > max_imbalance:
            self.logger.warning(
                f"🔧 近盘口: 不平衡 BUY={layer_data['buy_count']} SELL={layer_data['sell_count']}"
            )
            # 补充少的一方
            if layer_data["buy_count"] < layer_data["sell_count"]:
                deficit = (layer_data["sell_count"] - layer_data["buy_count"]) // 2
                for i in range(min(deficit, 5)):
                    price = target_buy1 * (1 - 0.001 * (i + 1))
                    add_orders.append(self._create_layer_order("BUY", price, nav, config))
            else:
                deficit = (layer_data["buy_count"] - layer_data["sell_count"]) // 2
                for i in range(min(deficit, 5)):
                    price = target_sell1 * (1 + 0.001 * (i + 1))
                    add_orders.append(self._create_layer_order("SELL", price, nav, config))

        return add_orders, cancel_orders

    def _adjust_mid_book(
        self,
        layer_data: Dict[str, Any],
        target_orders: List[Dict[str, Any]],
        nav: float,
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """中盘口调整：合理深度 + 分散档位"""
        add_orders = []
        cancel_orders = []

        mid_min_depth = config.get("mid_min_depth", 200)
        max_imbalance = config.get("mid_max_imbalance", 0.4)

        # 1. 检查深度是否合理
        if layer_data["buy_depth"] < mid_min_depth:
            self.logger.info("📊 中盘口: 买盘深度不足，补充订单")
            mid_buy_targets = [
                o for o in target_orders 
                if o.get("direction") == "bid"
            ]
            for order in mid_buy_targets[:5]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        if layer_data["sell_depth"] < mid_min_depth:
            self.logger.info("📊 中盘口: 卖盘深度不足，补充订单")
            mid_sell_targets = [
                o for o in target_orders 
                if o.get("direction") == "ask"
            ]
            for order in mid_sell_targets[:5]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "SELL",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        # 2. 检查买卖平衡（中盘口容忍度更高）
        if layer_data["imbalance"] > max_imbalance:
            self.logger.warning(
                f"🔧 中盘口: 不平衡 BUY={layer_data['buy_count']} SELL={layer_data['sell_count']}"
            )
            # 中盘口只记录告警，不主动补单（避免订单过多）

        return add_orders, cancel_orders

    def _adjust_far_book(
        self,
        layer_data: Dict[str, Any],
        target_orders: List[Dict[str, Any]],
        nav: float,
        config: Dict[str, Any],
    ) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
        """远盘口调整：数量和深度合理"""
        add_orders = []
        cancel_orders = []

        far_min_count = config.get("far_min_count", 25)  # 每方向至少25单
        max_imbalance = config.get("far_max_imbalance", 0.5)

        # 1. 检查数量是否合理
        if layer_data["buy_count"] < far_min_count:
            self.logger.info(
                f"📊 远盘口: 买单数量不足 {layer_data['buy_count']} < {far_min_count}"
            )
            far_buy_targets = [
                o for o in target_orders 
                if o.get("direction") == "bid"
            ]
            for order in far_buy_targets[:10]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        if layer_data["sell_count"] < far_min_count:
            self.logger.info(
                f"📊 远盘口: 卖单数量不足 {layer_data['sell_count']} < {far_min_count}"
            )
            far_sell_targets = [
                o for o in target_orders 
                if o.get("direction") == "ask"
            ]
            for order in far_sell_targets[:10]:
                add_orders.append({
                    "symbol": self.symbol,
                    "side": "SELL",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": order.get("price"),
                    "quantity": order.get("quantity", order.get("amount")),
                    "quoteQty": None,
                    "order_purpose": "layer_adjust",
                })

        # 2. 检查买卖平衡（远盘口容忍度最高）
        if layer_data["imbalance"] > max_imbalance:
            self.logger.warning(
                f"🔧 远盘口: 严重不平衡 BUY={layer_data['buy_count']} SELL={layer_data['sell_count']}"
            )

        return add_orders, cancel_orders

    def _create_layer_order(
        self, 
        side: str, 
        price: float, 
        nav: float,
        config: Dict[str, Any],
    ) -> Dict[str, Any]:
        """创建分层调整订单"""
        # 获取精度配置
        price_precision = config.get("precision", 6)
        quantity_precision = config.get("prec_amount", 4)
        min_order_amount = config.get("min_order_amount", 10)  # 最小订单金额(USDT)
        
        # 计算数量
        quantity = round(min_order_amount / price, quantity_precision)
        
        return {
            "symbol": self.symbol,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "bizType": "SPOT",
            "price": round(price, price_precision),
            "quantity": quantity,
            "quoteQty": None,
            "order_purpose": "layer_adjust",
        }

    def _dedupe_orders(self, orders: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """订单去重（基于价格和方向）"""
        seen = set()
        result = []
        
        for order in orders:
            price = order.get("price")
            side = order.get("side")
            key = (price, side)
            
            if key not in seen:
                seen.add(key)
                result.append(order)
        
        return result
