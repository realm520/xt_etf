from typing import Dict, List, Any, Optional, Union, Tuple
import time
import logging
import redis
import numpy as np

from etf.orderbook import get_orderbook
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
    
    def __init__(self, order_manager: Any) -> None:
        """
        初始化做市商

        Args:
            order_manager: 订单管理器实例，用于执行订单操作
        """
        self.order_manager = order_manager
        self.best_sell: float = 0.0
        self.best_buy: float = 0.0
        self.r: redis.Redis = redis.Redis(
            host=DEFAULT_REDIS_HOST,
            port=DEFAULT_REDIS_PORT,
            db=DEFAULT_REDIS_DB
        )
        # 记录当前周期新增的反针对订单ID，用于避免误删
        self.current_anti_pin_order_ids: List[str] = []

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

    def make_orders(
        self,
        symbol: Optional[str] = None,
        clientOrderId: str = DEFAULT_CLIENT_ORDER_ID,
        netvalue: float = 1.0,
        env: str = "qa",
        ordermanager: Optional[Any] = None,
    ) -> None:
        """
        创建模拟做市订单（主要用于测试环境）
        
        在QA环境中生成假订单用于测试做市逻辑，不实际提交到交易所
        
        Args:
            symbol: 交易对符号，如'btc5l_usdt'
            clientOrderId: 客户端订单ID
            netvalue: 净值价格，用作订单簿中间价
            env: 环境标识，目前只支持'qa'测试环境
            ordermanager: 订单管理器（已弃用参数）
            
        Note:
            该方法只在qa环境下生效，用于测试做市策略
        """
        if env == "qa":
            # make fake orders first
            fake_batch_order_bid, fake_batch_order_ask = get_orderbook(
                mid_price=netvalue
            )

            fake_data = []
            for fake_order in fake_batch_order_bid + fake_batch_order_ask:
                order_data = {
                    "symbol": symbol,
                    "clientOrderId": self.order_manager.create_temp_id(),
                    "side": SIDE_SELL if fake_order["direction"] == "ask" else SIDE_BUY,
                    "type": ORDER_TYPE_LIMIT,
                    "timeInForce": TIME_IN_FORCE_GTC,
                    "bizType": BIZ_TYPE_SPOT,
                    "price": fake_order["price"],
                    "quantity": fake_order["amount"],
                    "quoteQty": None,
                }
                fake_data.append(order_data)

            res = self.order_manager.add_orders_batch(fake_data, batch_id=DEFAULT_BATCH_ID)


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
        执行智能做市订单放置策略
        
        这是核心做市方法，执行以下操作：
        1. 从Redis或文件获取实时净值
        2. 生成基于净值的订单簿
        3. 使用优化算法匹配当前订单
        4. 批量执行订单添加和取消
        5. 添加反针对保护订单
        
        Args:
            config: 策略配置字典，包含净值键、价差、精度等参数
            symbol: 交易对符号
            clientOrderId: 客户端订单ID（已弃用）
            env: 环境标识
            ordermanager: 订单管理器（已弃用参数）
            currencies: 货币列表（已弃用参数）
            prec: 价格精度位数
            
        Note:
            该方法使用O(n log n)优化算法进行订单匹配，
            显著提升大量订单场景下的性能
        """
        # 尝试从 Redis 获取净值，如果失败则尝试从文件读取
        try:
            redis_value = self.r.get(config["netvalue"])
            if redis_value is not None:
                netvalue = float(redis_value.decode())
            else:
                # Redis 中没有值，尝试从文件读取
                logging.warning(
                    f"Redis key {config['netvalue']} not found, trying to read from file"
                )
                try:
                    file_path = config["netvalue"].replace("netvalue_", "net_value_")
                    with open(file_path, "r", encoding="utf8") as f:
                        netvalue = float(f.read().strip())
                    # 将值写入 Redis 以供后续使用
                    self.r.set(config["netvalue"], str(netvalue))
                    logging.info(
                        f"Loaded netvalue from file and saved to Redis: {netvalue}"
                    )
                except FileNotFoundError:
                    # 如果文件也不存在，使用默认值
                    netvalue = 1.0
                    self.r.set(config["netvalue"], str(netvalue))
                    logging.warning(
                        f"Neither Redis nor file found, using default netvalue: {netvalue}"
                    )
        except Exception as e:
            logging.error(f"Error getting netvalue: {e}")
            netvalue = 1.0
            logging.warning(f"Using default netvalue due to error: {netvalue}")

        logging.info(f"{symbol}, {netvalue}")
        self.order_manager.netvalue = netvalue
        try:
            current_orders = self.order_manager.client.get_open_orders(symbol=symbol)
        except Exception as e:
            logging.info(e)
            while True:
                time.sleep(1)
                try:
                    current_orders = self.order_manager.client.get_open_orders(
                        symbol=symbol
                    )
                    break
                except Exception as e:
                    logging.info("try again")
                    continue
            pass

        if netvalue:
            cancel_orders = []
            add_orders = []

            batch_order_bid, batch_order_ask = get_orderbook(
                mid_price=netvalue, bid_ask_spread=config["bid_ask_spread"]
            )

            goal_orders = batch_order_ask + batch_order_bid
            self.best_sell = batch_order_ask[0]["price"]
            self.best_buy = batch_order_bid[0]["price"]
            logging.info(
                f"goal ask1: {batch_order_ask[0]} goal bid1: {batch_order_bid[0]}"
            )
            logging.info(
                f"goal ask-1: {batch_order_ask[-1]} goal bid-1: {batch_order_bid[-1]}"
            )

            # 使用优化的订单匹配算法，从O(n²)降低到O(n log n)
            @performance_monitor.time_function("order_matching")
            def perform_order_matching():
                # 为goal_orders添加symbol信息
                for goal in goal_orders:
                    goal["symbol"] = symbol
                
                return optimize_order_matching(current_orders, goal_orders)
            
            optimized_add_orders, optimized_cancel_orders = perform_order_matching()
            
            # 为每个新订单设置clientOrderId
            for order_data in optimized_add_orders:
                order_data["clientOrderId"] = self.order_manager.create_temp_id()
            
            add_orders.extend(optimized_add_orders)
            cancel_orders.extend(optimized_cancel_orders)

            # cancle orders which price exceed the limitation
            goal_price_ranges = [
                (goal["min_price"], goal["max_price"]) for goal in goal_orders
            ]
            for market_order in current_orders:
                # if ((float(market_order["price"]) < batch_order_ask[0]["price"] and market_order["side"] == "SELL") or (float(market_order["price"]) > batch_order_bid[0]["price"] and market_order["side"] == "BUY")) and market_order["state"] != "PARTIALLY_FILLED":
                if (
                    float(market_order["price"]) < batch_order_ask[0]["price"]
                    and market_order["side"] == "SELL"
                ) or (
                    float(market_order["price"]) > batch_order_bid[0]["price"]
                    and market_order["side"] == "BUY"
                ):
                    logging.info(market_order["price"])
                    cancel_orders.append(market_order)

            logging.info(
                f"[{time.strftime('%H:%M:%S')}] Placing orders based on net value: {netvalue}"
            )
            logging.info(f"[{time.strftime('%H:%M:%S')}] add_orders: {len(add_orders)}")
            logging.info(
                f"[{time.strftime('%H:%M:%S')}] cancel_orders: {len(cancel_orders)}"
            )

            anti_pin_price_sell = round(
                self.best_sell * (1 + config["anti_pin_rate"]), config["precision"]
            )
            anti_pin_price_buy = round(
                self.best_buy * (1 - config["anti_pin_rate"]), config["precision"]
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

            # 创建反针对卖单
            sell_client_order_id = self.order_manager.create_temp_id()
            sell_order_data = {
                "symbol": symbol,
                "clientOrderId": sell_client_order_id,
                "side": SIDE_SELL,
                "type": ORDER_TYPE_LIMIT,
                "timeInForce": TIME_IN_FORCE_GTC,
                "bizType": BIZ_TYPE_SPOT,
                "price": anti_pin_price_sell,
                "quantity": anti_pin_amount_sell,
                "quoteQty": None,
            }
            add_orders.append(sell_order_data)
            self.current_anti_pin_order_ids.append(sell_client_order_id)

            # 创建反针对买单
            buy_client_order_id = self.order_manager.create_temp_id()
            buy_order_data = {
                "symbol": symbol,
                "clientOrderId": buy_client_order_id,
                "side": SIDE_BUY,
                "type": ORDER_TYPE_LIMIT,
                "timeInForce": TIME_IN_FORCE_GTC,
                "bizType": BIZ_TYPE_SPOT,
                "price": anti_pin_price_buy,
                "quantity": anti_pin_amount_buy,
                "quoteQty": None,
            }
            add_orders.append(buy_order_data)
            self.current_anti_pin_order_ids.append(buy_client_order_id)

            logging.info(
                f"anti_pin_price_sell {anti_pin_price_sell} anti_pin_price_buy {anti_pin_price_buy} "
            )
            logging.info(
                f"anti_pin_amount_sell {anti_pin_amount_sell} anti_pin_amount_buy {anti_pin_amount_buy} "
            )

            # 使用优化的批量操作处理
            max_batch_size = DEFAULT_BATCH_SIZE
            
            # 优化添加和取消订单的分批策略
            chunked_add_orders = optimize_batch_operations(
                add_orders, max_batch_size, "add"
            ) if add_orders else []
            
            chunked_cancel_orders = optimize_batch_operations(
                cancel_orders, max_batch_size, "cancel"
            ) if cancel_orders else []
            
            # 构建操作队列，优化执行顺序
            operate_orders = []
            max_len = max(len(chunked_add_orders), len(chunked_cancel_orders))
            
            for i in range(max_len):
                # 交替执行添加和取消操作以避免冲突
                if i < len(chunked_cancel_orders):
                    operate_orders.append((chunked_cancel_orders[i], "cancel"))
                if i < len(chunked_add_orders):
                    operate_orders.append((chunked_add_orders[i], "add"))

            # 批量处理订单并监控性能
            @performance_monitor.time_function("batch_order_processing")
            def execute_order_batches():
                for orders in operate_orders:
                    if orders[1] == "add":
                        try:
                            res = self.order_manager.add_orders_batch(
                                orders[0], batch_id=DEFAULT_BATCH_ID
                            )
                            logging.debug(f"成功添加 {len(orders[0])} 个订单")
                        except Exception as e:
                            logging.error(f"批量添加订单失败: {e}")
                            pass

                    elif orders[1] == "cancel":
                        try:
                            res = self.order_manager.cancel_orders_batch(orders=orders[0])
                            logging.debug(f"成功取消 {len(orders[0])} 个订单")
                        except Exception as e:
                            logging.error(f"批量取消订单失败: {e}")
                            pass

            execute_order_batches()

            # 在新反针对订单添加完成后，取消旧的反针对订单
            # 这样可以避免保护空窗期，确保始终有反针对订单保护
            self._cancel_old_anti_pin_orders(
                symbol=symbol,
                anti_pin_price_sell=anti_pin_price_sell,
                anti_pin_price_buy=anti_pin_price_buy,
                exclude_order_ids=self.current_anti_pin_order_ids
            )
        else:
            logging.info(f"[{time.strftime('%H:%M:%S')}] Waiting for net value..")
    
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
