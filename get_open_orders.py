from etf.risk import RiskController
from etf.washing import WashController
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.xt import Spot
from hedging import Hedge
import json
import time
import logging
import threading
import atexit
import pandas as pd

logging.shutdown()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class EtfStrategy:
    def __init__(self, client, order_manager):
        self.client = client
        self.order_manager = order_manager

    @staticmethod
    def run(config, risk_controller, wash_controller, market_maker, nv, depth=None):
        try:
            depth = risk_controller.get_depth_data(config["symbol"])
        except Exception as e:
            logging.error(e)
            logging.info("error with getting new depth, using history depth")
            depth = risk_controller.depth
            pass  # using history depth

        if config["cancel_all_open_orders"]:
            logging.info("cancel_all_open_orders")
            if len(depth["asks"]) != 0 or len(depth["bids"]) != 0:
                try:
                    order_manager.cancel_all_open_orders(config["symbol"])
                    time.sleep(10)
                except Exception as e:
                    pass
                columns = [
                    "price",
                    "quantity",
                    "orderId",
                    "time",
                    "UTC_PLUS_8",
                    "symbol",
                    "side",
                    "state",
                ]
                df = pd.DataFrame(columns=columns)
                df.to_csv(
                    market_maker.order_manager.open_orders_csv_file,
                    mode="w",
                    index=False,
                    header=True,
                )
                market_maker.make_orders(config["symbol"])
        else:
            logging.info("skip cancel_all_open_orders")

        if config["pre_make_orders"]:
            logging.info("pre_make_orders")
            if len(depth["asks"]) == 0 or len(depth["bids"]) == 0:
                market_maker.make_orders()
        else:
            logging.info("skip pre_make_orders")
        """
        last_mid_price = risk_controller.get_mid_price(depth)
        last_amount = int(float(depth["bids"][0][1]) + float(depth["asks"][0][1]) / 2)
        # logging.info(f"Initial amount {last_amount} and price {last_mid_price}")
        """
        try:
            while True:
                time.sleep(1)
                """
                # wash trading
                if config["Enable_wash_trading"]:
                    time.sleep(10)
                    try:
                        depth = risk_controller.get_depth_data(config["symbol"])
                        mid_price = risk_controller.get_mid_price(depth)
                    except Exception as e:
                        logging.error(e)
                        continue

                    last_mid_price, last_amount = wash_controller.run(
                        config["symbol"],
                        last_mid_price,
                        last_amount,
                        mid_price,
                        config["precision"],
                        config["kline_continuity_interval"])
                else:
                    logging.info("skip wash trading")
                """
                market_maker.place_orders(
                    nv=nv,
                    symbol=config["symbol"],
                    env=config["env"],
                    currencies=config["currencies"],
                    prec=config["precision"],
                )

                # logging.info("replace")
                # after reset open orders, self.open_orders should NOT contain
                # canceled orders
                market_maker.order_manager.reset_open_orders(config["symbol"])

                # logging.info("writing orders")
                # market_maker.order_manager.write_history_orders()
                # market_maker.order_manager.write_trading_history()
                # atexit.register(market_maker.order_manager.write_orders)
                # atexit.register(market_maker.order_manager.write_trading_history)
                # logging.info("run etf computing postion")
                # market_maker.order_manager.get_position(config["symbol"])
        except Exception as e:
            if not config["Exit_with_cancel_all_open_orders"]:
                logging.info(e)
                return
            else:
                try:
                    order_manager.cancel_all_open_orders(config["symbol"])
                except Exception as e:
                    return


if __name__ == "__main__":
    config = {
        # "env": "qa",
        "env": "prod",
        "clientOrderId": "1655",
        "symbol": "stg5l_usdt",
        # "symbol": "btc5l_usdt",
        # "bnsymbol": "BTCUSDT",
        "bnsymbol": "STGUSDT",
        "currencies": ["btc5l"],
        "precision": 6,
        "Hedging_interval": 20,  # seconds
        "washing_interval": 1,  # seconds
        "kline_continuity_interval": 60,  # seconds
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": False,
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 4,
        "precision_price": 4,
        "Enable_hedging": True,
        "Exit_with_cancel_all_open_orders": True,
    }
    if config["env"] == "qa":
        spot = Spot(
            host="https://sapi.xt-qa.com",
            access_key="be3466e5-365c-4471-a368-7c425fd5dd61",
            secret_key="9ca42e6db6c35f0ca5f3541737b044c4e3d5abb2",
        )

    elif config["env"] == "prod":
        with open("APIKey_stg3s.json", "r", encoding="utf8") as input:
            apikey = json.load(input)
            print(apikey["xt"]["access_key"])
            spot = Spot(
                host="https://sapi.xt.com",
                access_key=apikey["xt"]["access_key"],
                secret_key=apikey["xt"]["secret_key"],
            )

    order_manager = OrderManager(spot)

    info = order_manager.client.balances([
        "USDT",
        "STG5L",
        "BTC5L",
        "BTC",
        "STG5S",
        "STG3S",
        "STG3L",
    ])
    logging.info(info)
    """
    {'totalUsdtAmount': '19341.6281', 'totalBtcAmount': '0.22708371', 'assets': [{'currency': 'stg5l', 'currencyId': 4135, 'frozenAmount': '8681.39000000', 'freeze': '0.00000000', 'lock': '0.00000000', 'copyTrade': '0.00000000', 'trade': '8681.39000000', 'withdraw': '0.00000000', 'availableAmount': '1237.44000000', 'totalAmount': '9918.83000000', 'convertBtcAmount': '0.10949282', 'convertUsdtAmount': '9325.94185558'}, {'currency': 'usdt', 'currencyId': 11, 'frozenAmount': '5290.44588993', 'freeze': '0.00000000', 'lock': '0.00000000', 'copyTrade': '0.00000000', 'trade': '5290.44588993', 'withdraw': '0.00000000', 'availableAmount': '4725.24006132', 'totalAmount': '10015.68595125', 'convertBtcAmount': '0.11759088', 'convertUsdtAmount': '10015.68595125'}, {'currency': 'btc5l', 'currencyId': 3535, 'frozenAmount': '0.00000000', 'freeze': '0.00000000', 'lock': '0.00000000', 'copyTrade': '0.00000000', 'trade': '0.00000000', 'withdraw': '0.00000000', 'availableAmount': '0.00184000', 'totalAmount': '0.00184000', 'convertBtcAmount': '0', 'convertUsdtAmount': '0.00029864'}]}

    """

    # logging.info()
    import time
    from datetime import datetime

    # 获取今天的日期
    now = datetime.now()
    today_10am = datetime(now.year, now.month, now.day - 1, 10, 0, 0)  # 10:00:00
    # logging.info(today_10am)
    timestamp_10am = int(time.mktime(today_10am.timetuple()) * 1000)  # local time
    # logging.info(timestamp_10am)

    end_time = datetime(now.year, now.month, now.day - 1, 10, 1, 0)
    end_time = int(time.mktime(end_time.timetuple()) * 1000)
    # logging.info(end_time)
    # res = order_manager.client.get_history_orders(symbol=config["symbol"], limit=20, start_time=timestamp_10am, end_time=end_time, hidden_canceled=True)
    # res = order_manager.client.get_trade(symbol=config["symbol"], side="SELL", start_time=timestamp_10am, end_time=None)
    # logging.info(res["items"][0])
    # for item in res["items"]:
    #    logging.info(item)
    #    if item['side'] == "SELL" and item['state'] != 'CANCELED':
    #        logging.info(item)
    # logging.info(res)
    # res = order_manager.client.get_account()
    # logging.info(res)
    # logging.info(res)
    # 1. get depth correct?
    # 2.
    #
    # for order in res:
    # for order in res["items"]:
    #     logging.info(order["state"])

    #     #assert order["state"] == "CANCELED"
    #     if order["state"] != "CANCELED":
    #     #if float(order["price"]) > 1 and order["side"] == "BUY":
    #         logging.info(order)
    # if order["side"] == "BUY":

    #    logging.info(order)
