import time
import random
import logging
import numpy as np
import redis
from etf.utils.optimization import performance_monitor
from etf.utils.constants import (
    DEFAULT_REDIS_HOST, DEFAULT_REDIS_PORT, DEFAULT_REDIS_DB,
    DEFAULT_MAX_TRADE_AMOUNT, DEFAULT_MIN_TRADE_VALUE,
    DEFAULT_CLIENT_ORDER_ID, DEFAULT_BATCH_ID, SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, BIZ_TYPE_SPOT
)


class WashController:
    def __init__(self, order_manager, market_maker):
        self.order_manager = order_manager
        self.market_maker = market_maker
        self.returns = []

        self.max_trade_amount = DEFAULT_MAX_TRADE_AMOUNT
        self.total_spent = 0
        self.r = redis.Redis(host=DEFAULT_REDIS_HOST, port=DEFAULT_REDIS_PORT, db=DEFAULT_REDIS_DB)

    @performance_monitor.time_function("wash_trading")
    def wash(
        self, symbol, last_mid_price, mid_price, prec=4, prec_amount=2, interval=60
    ):
        self.returns.append((mid_price - last_mid_price) / last_mid_price)
        tick = float(f"1e-{prec}")

        # 1min k-line
        if len(self.returns) > interval:
            new_mid_price = last_mid_price + random.randint(1, 2) * tick
            logging.info(
                f"[{time.strftime('%H:%M:%S')}] last {interval / 60} min closing price {last_mid_price}, closing prices from {mid_price} to {new_mid_price}"
            )
            mid_price = new_mid_price
            self.returns = [(mid_price - last_mid_price) / last_mid_price]

        price_change = mid_price - last_mid_price
        amount = (
            np.random.randint(1, self.max_trade_amount)
            if price_change > 0
            else np.random.randint(1, self.max_trade_amount // 3)
        )

        volatility = self.returns[-1]
        if volatility > 0.01:
            logging.info(f"volatility {volatility} too high, skipping order")
            return mid_price

        # 确保最小交易价值
        if mid_price * amount < DEFAULT_MIN_TRADE_VALUE:
            amount = DEFAULT_MIN_TRADE_VALUE / mid_price

        amount = round(amount + random.uniform(0, 1), prec_amount)
        logging.info(f"price change {price_change}, by tick {price_change / tick}")
        logging.info(
            f"sending orders with amount {amount}, volatility {volatility}, and price {mid_price}"
        )

        last_mid_price = mid_price

        rd = random.randint(0, 1)
        try:
            buy_data = [
                {
                    "symbol": symbol,
                    "clientOrderId": self.order_manager.create_temp_id(),
                    "side": SIDE_BUY if rd == 0 else SIDE_SELL,
                    "type": ORDER_TYPE_LIMIT,
                    "timeInForce": TIME_IN_FORCE_GTC,
                    "bizType": BIZ_TYPE_SPOT,
                    "price": round(mid_price, prec),
                    "quantity": amount,
                    "quoteQty": None,
                }
            ]
            res1 = self.order_manager.add_orders_batch(
                buy_data, batch_id=DEFAULT_BATCH_ID, is_wash_trading=True
            )
            logging.info(res1)
            sell_data = [
                {
                    "symbol": symbol,
                    "clientOrderId": self.order_manager.create_temp_id(),
                    "side": SIDE_SELL if rd == 0 else SIDE_BUY,
                    "type": ORDER_TYPE_LIMIT,
                    "timeInForce": TIME_IN_FORCE_GTC,
                    "bizType": BIZ_TYPE_SPOT,
                    "price": round(mid_price, prec),
                    "quantity": amount,
                    "quoteQty": None,
                }
            ]
            res2 = self.order_manager.add_orders_batch(
                sell_data, batch_id=DEFAULT_BATCH_ID, is_wash_trading=True
            )
            logging.info(res2)

        except Exception as e:
            logging.info(e)

        return last_mid_price

    def get_washing_price(self, config):
        if self.market_maker.best_sell == 0:
            # 尝试从 Redis 获取净值，如果失败则使用默认值
            try:
                redis_value = self.r.get(config["netvalue"])
                if redis_value is not None:
                    mid_price = float(redis_value.decode())
                else:
                    # Redis 中没有值，尝试从文件读取
                    logging.warning(
                        f"Redis key {config['netvalue']} not found in wash controller, trying to read from file"
                    )
                    try:
                        file_path = config["netvalue"].replace(
                            "netvalue_", "net_value_"
                        )
                        with open(file_path, "r", encoding="utf8") as f:
                            mid_price = float(f.read().strip())
                        # 将值写入 Redis 以供后续使用
                        self.r.set(config["netvalue"], str(mid_price))
                        logging.info(
                            f"Wash controller loaded netvalue from file and saved to Redis: {mid_price}"
                        )
                    except FileNotFoundError:
                        # 如果文件也不存在，使用默认值
                        mid_price = 1.0
                        self.r.set(config["netvalue"], str(mid_price))
                        logging.warning(
                            f"Wash controller using default netvalue: {mid_price}"
                        )
            except Exception as e:
                logging.error(f"Wash controller error getting netvalue: {e}")
                mid_price = 1.0

            bid_ask_spread = config.get("bid_ask_spread", 0.05)

            best_sell = mid_price - ((mid_price * bid_ask_spread) / 2)
            best_buy = mid_price + ((mid_price * bid_ask_spread) / 2)
        else:
            best_sell = self.market_maker.best_sell
            best_buy = self.market_maker.best_buy

        # washing price with respect to best_sell or mid_price
        wash_method = config.get("wash", "mid_price")  # 默认使用 mid_price
        precision = config.get("precision", 6)  # 默认精度

        if wash_method == "best_sell":
            washing_price = float(best_sell) - float(
                f"1e-{precision}"
            ) * random.randint(5, 10)
        else:  # 默认使用 mid_price
            washing_price = (float(best_sell) + float(best_buy)) / 2

        return washing_price

    def run(self, risk_controller, config):
        time.sleep(random.randint(1, 5))

        # For initialization
        last_mid_price = self.get_washing_price(config)

        while True:
            time.sleep(random.randint(5, 10))

            # For each washing trade
            mid_price = self.get_washing_price(config)

            last_mid_price = self.wash(
                config["symbol"],
                last_mid_price,
                mid_price,
                config["precision"],
                config["prec_amount"],
                config["kline_continuity_interval"],
            )
    
    def get_performance_stats(self):
        """获取wash trading性能统计信息"""
        wash_stats = performance_monitor.get_statistics("wash_trading")
        
        stats = {
            "wash_trading": wash_stats,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "total_spent": self.total_spent,
            "max_trade_amount": self.max_trade_amount
        }
        
        if wash_stats:
            logging.info(f"Wash trading平均耗时: {wash_stats['avg_time']:.4f}s")
            logging.info(f"Wash trading执行次数: {wash_stats['count']}")
            
        return stats
