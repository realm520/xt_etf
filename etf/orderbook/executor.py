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
        logger: Optional[logging.Logger] = None,
        stats_print_interval: float = 10.0,  # 统计打印间隔（秒）
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

        # === 0.6 买卖平衡检查和修正 ===
        detailed_stats = self._count_orders_by_type_and_side(current_orders)
        current_buy = sum(stats["BUY"] for stats in detailed_stats.values())
        current_sell = sum(stats["SELL"] for stats in detailed_stats.values())
        current_total = current_buy + current_sell
        
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

        # === 1. 订单匹配分析 ===
        optimized_add_orders, optimized_cancel_orders = self._match_orders(
            current_orders, target_orders
        )

        # === 1.5 硬性订单上限保护（优化版：方案1+4）===
        # 方案1: 考虑待取消的订单数量
        # 方案4: 只计算做市订单数量，不把洗盘/对冲订单计入上限
        
        # 初始化变量（用于后续反针对订单保护）
        effective_mm_count = order_stats['market_making']  # 默认值
        
        if self.max_layer is not None:
            anti_pin_reserve = 5  # 预留5个槽位给反针对订单（从10减少到5）
            
            # 统计待取消订单中的做市订单数量
            cancel_stats = self._count_orders_by_type(optimized_cancel_orders)
            cancel_mm_count = cancel_stats['market_making']
            
            # 当前做市订单数量（只计算做市订单，不含洗盘/对冲等）
            current_mm_count = order_stats['market_making']
            
            # 优化计算：考虑待取消的做市订单
            # 净做市订单数 = 当前做市订单 - 待取消做市订单
            effective_mm_count = current_mm_count - cancel_mm_count
            available_slots = max(0, self.max_layer - effective_mm_count - anti_pin_reserve)
            
            if len(optimized_add_orders) > available_slots:
                original_count = len(optimized_add_orders)
                optimized_add_orders = optimized_add_orders[:available_slots]
                self.logger.warning(
                    f"🔒 硬性上限保护: 截断做市订单 {original_count} → {len(optimized_add_orders)} "
                    f"(做市订单={current_mm_count}, 待取消={cancel_mm_count}, "
                    f"净做市={effective_mm_count}, 上限={self.max_layer}, 可用槽位={available_slots})"
                )
            else:
                self.logger.debug(
                    f"📊 做市订单槽位充足: 当前做市={current_mm_count}, 待取消={cancel_mm_count}, "
                    f"净做市={effective_mm_count}, 可用={available_slots}, 需添加={len(optimized_add_orders)}"
                )

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
            
            # 检查是否有足够槽位添加反针对订单（优化版：只计算做市+反针对订单）
            if self.max_layer is not None:
                # 净做市订单数 + 待添加做市订单 + 反针对订单
                total_mm_after_add = effective_mm_count + len(optimized_add_orders) + len(anti_pin_orders)
                if total_mm_after_add > self.max_layer:
                    # 计算可用槽位（基于做市订单数）
                    remaining_slots = max(0, self.max_layer - effective_mm_count - len(optimized_add_orders))
                    if remaining_slots < len(anti_pin_orders):
                        original_antipin_count = len(anti_pin_orders)
                        anti_pin_orders = anti_pin_orders[:remaining_slots]
                        self.logger.warning(
                            f"🔒 反针对订单截断: {original_antipin_count} → {len(anti_pin_orders)} "
                            f"(做市订单={effective_mm_count}+{len(optimized_add_orders)}, "
                            f"总计将达到: {effective_mm_count + len(optimized_add_orders) + len(anti_pin_orders)}/{self.max_layer})"
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
        order_types = ["market_making", "anti_pin", "wash_trading", "hedging", "unknown"]
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
