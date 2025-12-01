from typing import Dict, List, Any, Optional, Union, Tuple
import time
import logging
import redis
import numpy as np

# 订单簿相关导入
from etf.orderbook.base import OrderbookConfig, OrderbookFactory
from etf.orderbook.executor import OrderExecutor
from etf.orderbook.layer_balance import LayerBalanceChecker, LayerBalanceConfig
from etf.utils.optimization import (
    optimize_order_matching, 
    performance_monitor, 
    async_order_processor,
    optimize_batch_operations
)
from etf.utils.constants import (
    DEFAULT_REDIS_HOST, DEFAULT_REDIS_PORT, DEFAULT_REDIS_DB,
    DEFAULT_BATCH_SIZE, DEFAULT_BATCH_ID, DEFAULT_CLIENT_ORDER_ID,
    SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, BIZ_TYPE_SPOT
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class MarketMaker:
    """
    ETF做市商核心类，负责自动化的市场做市和流动性提供
    
    该类实现了高级做市策略，包括：
    - 动态订单簿生成和管理
    - 基于净值的智能定价
    - 优化的批量订单处理
    - 反针对订单保护
    - 实时性能监控
    
    Attributes:
        order_manager: 订单管理器实例
        best_sell (float): 当前最优卖价
        best_buy (float): 当前最优买价
        r (redis.Redis): Redis连接实例，用于数据缓存和通信
    """
    
    def __init__(self, order_manager: Any, symbol_config_manager: Any = None) -> None:
        """
        初始化做市商

        Args:
            order_manager: 订单管理器实例，用于执行订单操作
            symbol_config_manager: Symbol配置管理器，用于动态获取交易对精度
        """
        self.order_manager = order_manager
        self.symbol_config_manager = symbol_config_manager
        self.best_sell: float = 0.0
        self.best_buy: float = 0.0
        self.r: redis.Redis = redis.Redis(
            host=DEFAULT_REDIS_HOST,
            port=DEFAULT_REDIS_PORT,
            db=DEFAULT_REDIS_DB
        )
        
        # 价格变化追踪（避免频繁更新订单）
        self.last_netvalue: Optional[float] = None  # 上次净值
        self.last_best_sell: float = 0.0  # 上次最优卖价
        self.last_best_buy: float = 0.0  # 上次最优买价
        self.price_change_threshold: float = 0.003  # 价格变化阈值（0.3%） - 减少不必要的订单更新
        self.last_update_time: float = 0.0  # 上次更新时间（时间戳）
        self.min_update_interval: float = 30.0  # 最小更新间隔（秒）
        
        # ✅ 订单执行器（每个交易对创建一个独立实例）
        self.executor: Optional[OrderExecutor] = None
        
        # ✅ 分层平衡检查器
        self.layer_balance_checker: Optional[LayerBalanceChecker] = None

    def _check_near_book_alignment(
        self,
        symbol: str,
        target_best_buy: float,
        target_best_sell: float,
        max_deviation: float = 0.002,
    ) -> Tuple[bool, Dict[str, Any]]:
        """检查近盘口订单是否对齐目标价格（强制对齐机制）
        
        即使价格变化未达到阈值，也需要检查买一卖一是否严重偏离目标。
        这是防止卖一偏高问题的关键保护机制。
        
        Args:
            symbol: 交易对符号
            target_best_buy: 目标买一价格
            target_best_sell: 目标卖一价格
            max_deviation: 最大允许偏差（默认0.2%）
            
        Returns:
            Tuple[需要修复, 偏差详情]
        """
        result = {
            "needs_repair": False,
            "actual_bid": None,
            "actual_ask": None,
            "bid_deviation": 0.0,
            "ask_deviation": 0.0,
            "message": "",
        }
        
        try:
            # 获取当前订单
            current_orders = self.order_manager.client.get_open_orders(symbol=symbol)
            
            if not current_orders:
                result["message"] = "无当前订单"
                return False, result
            
            # 计算实际买一和卖一
            buy_orders = [o for o in current_orders if o.get("side") == "BUY"]
            sell_orders = [o for o in current_orders if o.get("side") == "SELL"]
            
            if not buy_orders or not sell_orders:
                result["message"] = "买卖订单不完整"
                result["needs_repair"] = True
                return True, result
            
            # 找出最高买价和最低卖价
            actual_bid = max(float(o.get("price", 0)) for o in buy_orders)
            actual_ask = min(float(o.get("price", 0)) for o in sell_orders)
            
            result["actual_bid"] = actual_bid
            result["actual_ask"] = actual_ask
            
            # 计算偏差
            bid_deviation = (actual_bid - target_best_buy) / target_best_buy if target_best_buy > 0 else 0
            ask_deviation = (actual_ask - target_best_sell) / target_best_sell if target_best_sell > 0 else 0
            
            result["bid_deviation"] = bid_deviation
            result["ask_deviation"] = ask_deviation
            
            # 检查是否需要修复
            bid_ok = abs(bid_deviation) <= max_deviation
            ask_ok = ask_deviation <= max_deviation  # 卖一允许略低但不允许偏高
            
            if not bid_ok or not ask_ok:
                result["needs_repair"] = True
                issues = []
                if not bid_ok:
                    issues.append(f"买一偏差{bid_deviation*100:.2f}%")
                if not ask_ok:
                    issues.append(f"卖一偏高{ask_deviation*100:.2f}%")
                result["message"] = f"近盘口偏差超限: {', '.join(issues)}"
                
                logging.warning(
                    f"🚨 近盘口对齐检查: 实际买1={actual_bid:.6f}, 卖1={actual_ask:.6f} | "
                    f"目标买1={target_best_buy:.6f}, 卖1={target_best_sell:.6f} | "
                    f"偏差: 买1={bid_deviation*100:.2f}%, 卖1={ask_deviation*100:.2f}% | "
                    f"{'需要修复' if result['needs_repair'] else '正常'}"
                )
                return True, result
            else:
                result["message"] = "近盘口对齐正常"
                return False, result
                
        except Exception as e:
            logging.error(f"近盘口对齐检查失败: {e}")
            result["message"] = f"检查异常: {e}"
            return False, result

    def _cancel_old_anti_pin_orders(
        self,
        symbol: str,
        anti_pin_price_sell: float,
        anti_pin_price_buy: float,
        exclude_order_ids: List[str]
    ) -> None:
        """
        取消旧的反针对订单（排除新添加的订单）

        通过价格特征识别反针对订单，排除新添加的订单ID，批量取消旧的反针对订单

        Args:
            symbol: 交易对符号
            anti_pin_price_sell: 反针对卖单价格
            anti_pin_price_buy: 反针对买单价格
            exclude_order_ids: 需要排除的订单ID列表（新添加的订单）
        """
        try:
            # 获取当前所有活跃订单
            current_orders = self.order_manager.client.get_open_orders(symbol=symbol)

            old_anti_pin_orders = []
            price_tolerance = 0.0001  # 价格容差，用于浮点数比较

            for order in current_orders:
                order_price = float(order["price"])
                client_order_id = order.get("clientOrderId", "")

                # 跳过新添加的订单
                if client_order_id in exclude_order_ids:
                    continue

                # 通过价格特征识别反针对订单
                is_anti_pin_sell = (
                    order["side"] == "SELL" and
                    abs(order_price - anti_pin_price_sell) < price_tolerance
                )
                is_anti_pin_buy = (
                    order["side"] == "BUY" and
                    abs(order_price - anti_pin_price_buy) < price_tolerance
                )

                if is_anti_pin_sell or is_anti_pin_buy:
                    old_anti_pin_orders.append(order)

            # 批量取消旧的反针对订单
            if old_anti_pin_orders:
                logging.info(
                    f"发现 {len(old_anti_pin_orders)} 个旧的反针对订单，准备取消"
                )
                try:
                    self.order_manager.cancel_orders_batch(orders=old_anti_pin_orders)
                    logging.info(f"成功取消 {len(old_anti_pin_orders)} 个旧的反针对订单")
                except Exception as e:
                    logging.error(f"取消旧反针对订单失败: {e}")
            else:
                logging.debug("没有发现需要取消的旧反针对订单")

        except Exception as e:
            logging.error(f"查询或取消旧反针对订单时出错: {e}")


    def place_orders(
        self,
        config: Dict[str, Any],
        symbol: str = "btc5l_usdt",
        clientOrderId: str = DEFAULT_CLIENT_ORDER_ID,
        env: str = "qa",
        ordermanager: Optional[Any] = None,
        currencies: Optional[List[str]] = None,
        prec: int = 4,
    ) -> None:
        """
        执行智能做市订单放置策略（重构版：使用OrderExecutor统一执行）
        
        架构改进：
        1. 算法层：OrderbookFactory生成目标订单簿
        2. 执行层：OrderExecutor统一处理订单匹配和执行
        3. 保持原有功能：价格变化检测、反针对订单、先加后删等
        
        Args:
            config: 策略配置字典，包含净值键、价差、精度等参数
            symbol: 交易对符号
            clientOrderId: 客户端订单ID（已弃用）
            env: 环境标识
            ordermanager: 订单管理器（已弃用参数）
            currencies: 货币列表（已弃用参数）
            prec: 价格精度位数
        """
        logging.info(f"📥 place_orders 开始: symbol={symbol}")
        
        # === 1. 获取净值 ===
        try:
            redis_value = self.r.get(config["netvalue"])
            if redis_value is not None:
                netvalue = float(redis_value.decode())
            else:
                logging.warning(
                    f"Redis key {config['netvalue']} not found, trying to read from file"
                )
                try:
                    file_path = config["netvalue"].replace("netvalue_", "net_value_")
                    with open(file_path, "r", encoding="utf8") as f:
                        netvalue = float(f.read().strip())
                    self.r.set(config["netvalue"], str(netvalue))
                    logging.info(
                        f"Loaded netvalue from file and saved to Redis: {netvalue}"
                    )
                except FileNotFoundError:
                    netvalue = 1.0
                    self.r.set(config["netvalue"], str(netvalue))
                    logging.warning(
                        f"Neither Redis nor file found, using default netvalue: {netvalue}"
                    )
        except Exception as e:
            logging.error(f"Error getting netvalue: {e}")
            netvalue = 1.0
            logging.warning(f"Using default netvalue due to error: {netvalue}")

        if not netvalue:
            logging.info(f"[{time.strftime('%H:%M:%S')}] Waiting for net value..")
            return

        # === 2. 检测价格变化（避免频繁更新）===
        import time as time_module
        current_time = time_module.time()
        price_changed = False
        
        # 检查是否首次运行
        if self.last_netvalue is None:
            price_changed = True
            logging.info(f"首次运行，初始化净值: {netvalue}")
        else:
            # 计算价格变化率
            change_rate = abs(netvalue - self.last_netvalue) / self.last_netvalue
            
            # 检查时间间隔（防止过于频繁更新）
            time_since_last_update = current_time - self.last_update_time
            
            if change_rate >= self.price_change_threshold:
                # 价格变化超过阈值，但需要检查时间间隔
                if time_since_last_update >= self.min_update_interval:
                    price_changed = True
                    logging.info(
                        f"价格变化 {change_rate:.4%} 超过阈值 {self.price_change_threshold:.4%}，"
                        f"且距上次更新 {time_since_last_update:.1f}秒 >= {self.min_update_interval}秒，"
                        f"更新订单簿 (旧: {self.last_netvalue:.6f} → 新: {netvalue:.6f})"
                    )
                else:
                    logging.debug(
                        f"价格变化 {change_rate:.4%} 超过阈值，但距上次更新仅 {time_since_last_update:.1f}秒 "
                        f"< {self.min_update_interval}秒，跳过订单更新（冷却期保护）"
                    )
                    # 更新净值但不重新下单
                    self.order_manager.netvalue = netvalue
                    return
            else:
                # === 价格变化不大，但需要检查近盘口是否严重偏离 ===
                # 读取近盘口对齐配置
                near_book_config = config.get("near_book_alignment", {})
                if near_book_config.get("enabled", True) and near_book_config.get("check_on_every_update", True):
                    # 计算目标买一卖一
                    bid_ask_spread = config.get("bid_ask_spread", 0.008)
                    target_best_buy = netvalue * (1 - bid_ask_spread / 2)
                    target_best_sell = netvalue * (1 + bid_ask_spread / 2)
                    max_deviation = near_book_config.get("max_deviation", 0.002)
                    
                    needs_repair, alignment_info = self._check_near_book_alignment(
                        symbol=symbol,
                        target_best_buy=target_best_buy,
                        target_best_sell=target_best_sell,
                        max_deviation=max_deviation,
                    )
                    
                    if needs_repair and near_book_config.get("force_repair", True):
                        logging.warning(
                            f"🚨 近盘口强制对齐触发: {alignment_info['message']} | "
                            f"价格变化仅 {change_rate:.4%}，但近盘口偏差超限，强制更新订单簿"
                        )
                        price_changed = True  # 强制触发订单簿更新
                    else:
                        logging.debug(
                            f"价格变化 {change_rate:.4%} 小于阈值 {self.price_change_threshold:.4%}，"
                            f"近盘口对齐正常，跳过订单更新 "
                            f"(当前: {netvalue:.6f}, 上次: {self.last_netvalue:.6f})"
                        )
                        # 价格变化不大且近盘口正常，仅更新净值但不重新下单
                        self.order_manager.netvalue = netvalue
                        return
                else:
                    logging.debug(
                        f"价格变化 {change_rate:.4%} 小于阈值 {self.price_change_threshold:.4%}，跳过订单更新 "
                        f"(当前: {netvalue:.6f}, 上次: {self.last_netvalue:.6f})"
                    )
                    # 价格变化不大，仅更新净值但不重新下单
                    self.order_manager.netvalue = netvalue
                    return

        # 记录新净值和更新时间
        self.last_netvalue = netvalue
        self.last_update_time = current_time
        self.order_manager.netvalue = netvalue
        logging.info(f"{symbol}, netvalue={netvalue}")

        # === 3. 获取当前订单 ===
        try:
            current_orders = self.order_manager.client.get_open_orders(symbol=symbol)
        except Exception as e:
            logging.error(f"获取当前订单失败: {e}")
            while True:
                time.sleep(1)
                try:
                    current_orders = self.order_manager.client.get_open_orders(
                        symbol=symbol
                    )
                    break
                except Exception as e:
                    logging.info("重试获取订单...")
                    continue

        # === 4. 生成目标订单簿（使用新算法）===
        orderbook_algorithm = config.get("orderbook_algorithm")
        if not orderbook_algorithm:
            raise ValueError(f"策略 {symbol} 缺少 orderbook_algorithm 配置！请在 config/strategies.yaml 中添加")

        logging.info(f"📊 使用订单簿算法: {orderbook_algorithm}")

        # 从配置读取参数
        orderbook_config_dict = config.get("orderbook_config", {})

        # 获取动态精度配置
        price_precision = None
        quantity_precision = None
        
        if self.symbol_config_manager:
            price_precision = self.symbol_config_manager.get_price_precision(symbol)
            quantity_precision = self.symbol_config_manager.get_quantity_precision(symbol)
        
        if price_precision is None or quantity_precision is None:
            raise RuntimeError(
                f"无法获取 {symbol} 的精度配置！请检查：\n"
                f"1. symbol_config_manager 是否正确初始化\n"
                f"2. 交易所 API 是否可访问\n"
                f"3. 交易对名称是否正确"
            )
        
        logging.info(f"📐 使用动态精度: 价格={price_precision}, 数量={quantity_precision}")
        
        # 创建订单簿配置（根据算法类型选择配置类）
        base_config_params = {
            "total_budget": orderbook_config_dict.get("total_budget", 10000.0),
            "layer": orderbook_config_dict.get("layer", 500),
            "mid_price": netvalue,
            "bid_ask_spread": config["bid_ask_spread"],
            "symbol": symbol,
            "price_precision": price_precision,
            "quantity_precision": quantity_precision,
        }

        if orderbook_algorithm == "layered":
            # 使用分层订单簿配置
            from etf.orderbook.layered import LayeredOrderbookConfig, LayerConfig

            def parse_layer_config(layer_dict: dict) -> LayerConfig:
                """解析单层配置"""
                return LayerConfig(
                    distance_threshold=layer_dict.get("distance_threshold"),
                    distance_range=tuple(layer_dict["distance_range"]) if "distance_range" in layer_dict else None,
                    layer_count=layer_dict.get("layer_count", 50),
                    price_tolerance=layer_dict.get("price_tolerance", 0.001),
                    update_interval=layer_dict.get("update_interval", 30),
                    price_change_trigger=layer_dict.get("price_change_trigger", 0.002),
                    budget_ratio=layer_dict.get("budget_ratio", 0.3),
                )

            # 解析3层配置（如果YAML中有配置则使用，否则使用默认值）
            layer_configs = {}
            if "near_book" in orderbook_config_dict:
                layer_configs["near_book"] = parse_layer_config(orderbook_config_dict["near_book"])
            if "transition_zone" in orderbook_config_dict:
                layer_configs["transition_zone"] = parse_layer_config(orderbook_config_dict["transition_zone"])
            if "far_book" in orderbook_config_dict:
                layer_configs["far_book"] = parse_layer_config(orderbook_config_dict["far_book"])

            orderbook_cfg = LayeredOrderbookConfig(**base_config_params, **layer_configs)
        else:
            # 使用基础配置（natural 等其他算法）
            orderbook_cfg = OrderbookConfig(
                **base_config_params,
                extra_params=orderbook_config_dict.get("extra_params", {}),
            )

        # 创建算法实例并生成订单簿
        algorithm = OrderbookFactory.create(orderbook_algorithm, orderbook_cfg)
        snapshot = algorithm.generate_snapshot()

        # 转换为兼容格式（包含optimize_order_matching所需的所有字段）
        # 计算价格容差（用于min_price和max_price）
        price_tolerance = 10 ** (-orderbook_cfg.price_precision)

        batch_order_bid = [
            {
                "price": float(level.price),
                "quantity": float(level.quantity),
                "amount": float(level.quantity),  # optimize_order_matching需要
                "direction": "bid",               # optimize_order_matching需要
                "min_price": float(level.price) - price_tolerance,  # 价格范围下界
                "max_price": float(level.price) + price_tolerance,  # 价格范围上界
            }
            for level in snapshot.bids
        ]
        batch_order_ask = [
            {
                "price": float(level.price),
                "quantity": float(level.quantity),
                "amount": float(level.quantity),  # optimize_order_matching需要
                "direction": "ask",               # optimize_order_matching需要
                "min_price": float(level.price) - price_tolerance,  # 价格范围下界
                "max_price": float(level.price) + price_tolerance,  # 价格范围上界
            }
            for level in snapshot.asks
        ]

        logging.info(
            f"📊 订单簿生成完成: {len(batch_order_bid)}档买盘 + {len(batch_order_ask)}档卖盘, "
            f"耗时 {snapshot.generation_time*1000:.2f}ms, "
            f"总金额 {float(snapshot.total_value):.2f} USDT"
        )

        goal_orders = batch_order_ask + batch_order_bid
        self.best_sell = batch_order_ask[0]["price"]
        self.best_buy = batch_order_bid[0]["price"]
        
        logging.info(
            f"目标盘口 - 卖1: {batch_order_ask[0]}, 买1: {batch_order_bid[0]}"
        )
        logging.info(
            f"目标盘口 - 卖N: {batch_order_ask[-1]}, 买N: {batch_order_bid[-1]}"
        )

        # === 5. 初始化或获取订单执行器 ===
        if self.executor is None:
            # 首次运行，创建执行器
            self.executor = OrderExecutor(
                order_manager=self.order_manager,
                symbol=symbol,
                strategy_name=config.get("strategy_name", "unknown"),
                max_layer=orderbook_cfg.layer,  # 传递最大档位数（用于订单数量保护）
            )
            logging.info(f"✅ 创建订单执行器: {symbol}, 最大档位: {orderbook_cfg.layer}")

        # === 6. 准备反针对订单配置 ===
        anti_pin_config = {
            "anti_pin_rate": config["anti_pin_rate"],
            "anti_pin_usdt": config["anti_pin_usdt"],
            "precision": price_precision,
            "prec_amount": quantity_precision,
        }

        # === 6.5 分层平衡检查（检查器负责决定调整，执行器负责执行）===
        nav = netvalue  # 净值作为NAV
        if nav > 0 and len(current_orders) > 0:
            # 初始化检查器（首次运行时）
            if self.layer_balance_checker is None:
                # 从配置读取分层平衡参数
                balance_config = config.get("balance_manager", {})
                if balance_config.get("enabled", True):
                    self.layer_balance_checker = LayerBalanceChecker(
                        config=None,  # 使用默认配置，后续可从YAML加载
                        logger=logging.getLogger(config.get("strategy_name", "mm")),
                    )
                    logging.info("✅ 初始化分层平衡检查器")
            
            # 执行分层平衡检查
            if self.layer_balance_checker is not None:
                # 筛选做市订单
                mm_orders = [
                    o for o in current_orders 
                    if str(o.get("clientOrderId", "")).startswith("mm_")
                ]
                
                # 调用检查器获取调整动作
                spread = config.get("bid_ask_spread", 0.008)
                balance_add, balance_cancel = self.layer_balance_checker.check_and_adjust(
                    current_orders=mm_orders,
                    target_orders=goal_orders,
                    nav=nav,
                    spread=spread,
                )
                
                # 将调整订单合并到目标订单
                if balance_add:
                    logging.info(f"🔧 分层平衡: 需补充 {len(balance_add)} 个订单")
                    goal_orders.extend(balance_add)
                
                # 取消订单通过执行器的 rebalance 机制处理
                if balance_cancel:
                    logging.info(f"🔧 分层平衡: 需取消 {len(balance_cancel)} 个订单")
                    # 将取消订单信息传递给执行器（通过标记）
                    for order in balance_cancel:
                        order["_balance_cancel"] = True

        # === 7. 使用OrderExecutor执行订单簿更新 ===
        summary = self.executor.execute_orderbook_update(
            current_orders=current_orders,
            target_orders=goal_orders,
            best_sell=self.best_sell,
            best_buy=self.best_buy,
            anti_pin_config=anti_pin_config,
        )

        # === 8. 更新价格记录 ===
        self.last_best_sell = self.best_sell
        self.last_best_buy = self.best_buy

        logging.info(f"📊 {summary.summary_text()}")
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        获取做市商性能统计信息
        
        收集并返回订单匹配和批量处理的详细性能指标，
        用于监控系统性能和优化策略参数
        
        Returns:
            Dict[str, Any]: 包含以下键的性能统计字典：
                - order_matching: 订单匹配算法性能指标
                - batch_processing: 批量订单处理性能指标  
                - timestamp: 统计时间戳
                
        Example:
            >>> stats = market_maker.get_performance_stats()
            >>> print(f"Average matching time: {stats['order_matching']['avg_time']:.4f}s")
        """
        order_matching_stats = performance_monitor.get_statistics("order_matching")
        batch_processing_stats = performance_monitor.get_statistics("batch_order_processing")
        
        stats = {
            "order_matching": order_matching_stats,
            "batch_processing": batch_processing_stats,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S')
        }
        
        if order_matching_stats:
            logging.info(f"订单匹配平均耗时: {order_matching_stats['avg_time']:.4f}s")
        if batch_processing_stats:
            logging.info(f"批量处理平均耗时: {batch_processing_stats['avg_time']:.4f}s")
            
        return stats
