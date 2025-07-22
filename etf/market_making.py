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
import time
import numpy as np
import logging
import redis

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class MarketMaker:
    def __init__(self, order_manager):
        self.order_manager = order_manager
        self.best_sell = 0
        self.best_buy = 0
        self.r = redis.Redis(host=DEFAULT_REDIS_HOST, port=DEFAULT_REDIS_PORT, db=DEFAULT_REDIS_DB)

    def make_orders(
        self,
        symbol=None,
        clientOrderId=DEFAULT_CLIENT_ORDER_ID,
        netvalue=1.0,
        env="qa",
        ordermanager=None,
    ):
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
        config,
        symbol="btc5l_usdt",
        clientOrderId=DEFAULT_CLIENT_ORDER_ID,
        env="qa",
        ordermanager=None,
        currencies=None,
        prec=4,
    ):
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

            # 创建反针对卖单
            sell_order_data = {
                "symbol": symbol,
                "clientOrderId": self.order_manager.create_temp_id(),
                "side": SIDE_SELL,
                "type": ORDER_TYPE_LIMIT,
                "timeInForce": TIME_IN_FORCE_GTC,
                "bizType": BIZ_TYPE_SPOT,
                "price": anti_pin_price_sell,
                "quantity": anti_pin_amount_sell,
                "quoteQty": None,
            }
            add_orders.append(sell_order_data)
            
            # 创建反针对买单
            buy_order_data = {
                "symbol": symbol,
                "clientOrderId": self.order_manager.create_temp_id(),
                "side": SIDE_BUY,
                "type": ORDER_TYPE_LIMIT,
                "timeInForce": TIME_IN_FORCE_GTC,
                "bizType": BIZ_TYPE_SPOT,
                "price": anti_pin_price_buy,
                "quantity": anti_pin_amount_buy,
                "quoteQty": None,
            }
            add_orders.append(buy_order_data)

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
        else:
            logging.info(f"[{time.strftime('%H:%M:%S')}] Waiting for net value..")
    
    def get_performance_stats(self):
        """获取性能统计信息"""
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
