from etf.orderbook import get_orderbook
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
        self.r = redis.Redis(host="localhost", port=6379, db=0)

    def make_orders(
        self,
        symbol=None,
        clientOrderId="16559590087220001",
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
                    "side": "SELL" if fake_order["direction"] == "ask" else "BUY",
                    "type": "LIMIT",
                    "timeInForce": "GTC",
                    "bizType": "SPOT",
                    "price": fake_order["price"],
                    "quantity": fake_order["amount"],
                    "quoteQty": None,
                }
                fake_data.append(order_data)

            res = self.order_manager.add_orders_batch(fake_data, batch_id=51232)

            # logging.info(f"make orders {res}")         #self.order_manager.write_orders()

    def place_orders(
        self,
        config,
        symbol="btc5l_usdt",
        clientOrderId="16559590087220001",
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

            for goal in goal_orders:
                goal_min_price = goal["min_price"]
                goal_max_price = goal["max_price"]
                goal_amount = goal["amount"]

                valid_market_orders = [
                    # order for order in current_orders if (goal_min_price <= float(order["price"]) <= goal_max_price) and order["state"] != "PARTIALLY_FILLED"
                    order
                    for order in current_orders
                    if (goal_min_price <= float(order["price"]) <= goal_max_price)
                ]

                total_market_amount = sum(
                    round(float(order["origQty"])) for order in valid_market_orders
                )

                # add orders
                if total_market_amount < goal_amount:
                    # logging.info("add order in {goal_min_price} ~ {goal_max_price} qty: {goal_amount - total_market_amount}")
                    order_data = {
                        "symbol": symbol,
                        "clientOrderId": self.order_manager.create_temp_id(),
                        "side": "SELL" if goal["direction"] == "ask" else "BUY",
                        "type": "LIMIT",
                        "timeInForce": "GTC",
                        "bizType": "SPOT",
                        "price": goal["price"],
                        "quantity": goal_amount - total_market_amount,
                        "quoteQty": None,
                    }
                    add_orders.append(order_data)

                # cancle orders
                elif total_market_amount > goal_amount:
                    # logging.info("cancel order in {goal_min_price} ~ {goal_max_price}")
                    excess_amount = total_market_amount - goal_amount
                    for order in valid_market_orders:
                        if excess_amount <= 0:
                            break
                        cancel_amount = min(
                            round(float(order["origQty"])), excess_amount
                        )
                        if order["state"] != "PARTIALLY_FILLED":
                            cancel_orders.append(order)
                        # logging.info(order["price"])
                        order_data = {
                            "symbol": symbol,
                            "clientOrderId": self.order_manager.create_temp_id(),
                            "side": "SELL" if goal["direction"] == "ask" else "BUY",
                            "type": "LIMIT",
                            "timeInForce": "GTC",
                            "bizType": "SPOT",
                            "price": goal["price"],
                            "quantity": goal_amount,
                            "quoteQty": None,
                        }
                        add_orders.append(order_data)

                        excess_amount += goal_amount
                        excess_amount -= cancel_amount

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
            # logging.info()

            order_data = {
                "symbol": symbol,
                "clientOrderId": self.order_manager.create_temp_id(),
                "side": "SELL",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "bizType": "SPOT",
                "price": anti_pin_price_sell,
                "quantity": anti_pin_amount_sell,
                "quoteQty": None,
            }
            add_orders.append(order_data)
            order_data = {
                "symbol": symbol,
                "clientOrderId": self.order_manager.create_temp_id(),
                "side": "BUY",
                "type": "LIMIT",
                "timeInForce": "GTC",
                "bizType": "SPOT",
                "price": anti_pin_price_buy,
                "quantity": anti_pin_amount_buy,
                "quoteQty": None,
            }
            add_orders.append(order_data)

            logging.info(
                f"anti_pin_price_sell {anti_pin_price_sell} anti_pin_price_buy {anti_pin_price_buy} "
            )
            logging.info(
                f"anti_pin_amount_sell {anti_pin_amount_sell} anti_pin_amount_buy {anti_pin_amount_buy} "
            )

            # add orders
            operate_orders = []
            max_batch_size_cancel = 100  # max 300
            max_batch_size_send = 100  # max 100
            chunked_add_orders = []
            chunked_cancel_orders = []
            if len(add_orders) > 0:
                chunked_add_orders = [
                    add_orders[t : t + max_batch_size_send]
                    for t in range(0, len(add_orders), max_batch_size_send)
                ]
            if len(cancel_orders) > 0:
                # chunked_cancel_orders = []
                for t in range(0, len(cancel_orders), max_batch_size_cancel):
                    chunked_cancel_orders.append([
                        order for order in cancel_orders[t : t + max_batch_size_cancel]
                    ])
            if len(chunked_add_orders) > 0 and len(chunked_cancel_orders) > 0:
                for add_order, cancel_order in zip(
                    chunked_add_orders, chunked_cancel_orders
                ):
                    operate_orders.append((add_order, "add"))
                    operate_orders.append((cancel_order, "cancel"))
            elif len(chunked_add_orders) == 0:
                operate_orders = [(item, "cancel") for item in chunked_cancel_orders]
            elif len(chunked_cancel_orders) == 0:
                operate_orders = [(item, "add") for item in chunked_add_orders]

            operate_orders.extend(
                (add_order, "add")
                for add_order in chunked_add_orders[len(chunked_cancel_orders) :]
            )
            operate_orders.extend(
                (cancel_order, "cancel")
                for cancel_order in chunked_cancel_orders[len(chunked_add_orders) :]
            )

            for orders in operate_orders:
                if orders[1] == "add":
                    try:
                        res = self.order_manager.add_orders_batch(
                            orders[0], batch_id=51232
                        )
                    except Exception as e:
                        logging.info(e)
                        pass

                elif orders[1] == "cancel":
                    try:
                        res = self.order_manager.cancel_orders_batch(orders=orders[0])
                    except Exception as e:
                        pass
            """
            anti_pin_price_sell = round(self.best_sell * (1 + config["anti_pin_rate"]), config["precision"])
            anti_pin_price_buy = round(self.best_buy * (1 - config["anti_pin_rate"]), config["precision"])

            anti_pin_amount_sell = round((config["anti_pin_usdt"] / 2) / anti_pin_price_sell, config["prec_amount"])
            anti_pin_amount_buy = round((config["anti_pin_usdt"] / 2) / anti_pin_price_buy, config["prec_amount"])

            logging.info(f"anti_pin_price_sell {anti_pin_price_sell} anti_pin_price_buy {anti_pin_price_buy} ")
            self.order_manager.add_order(symbol, side="SELL", type="LIMIT", price=anti_pin_price_sell, quantity=anti_pin_amount_sell)
            self.order_manager.add_order(symbol, side="BUY", type="LIMIT", price=anti_pin_price_buy, quantity=anti_pin_amount_buy)
            """
        else:
            logging.info(f"[{time.strftime('%H:%M:%S')}] Waiting for net value..")
