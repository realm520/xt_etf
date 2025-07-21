from etf.risk import RiskController
from etf.washing import WashController
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.xt import Spot
from hedging import Hedge

import time
import logging
import json
import pandas as pd

logging.shutdown()
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class Etf_stats:
    def __init__(self, apikey, symbols):
        self.apikey = apikey
        self.symbols = self.init_symbols(symbols)

    def init_symbols(self, symbols):
        symbols_info = {}
        for symbol in symbols:
            prefix = symbol.split("_")[0]
            symbols_info[symbol] = {
                "currency": [prefix.upper(), "usdt"],
                "client": Spot(
                    host="https://sapi.xt.com",
                    access_key=self.apikey["xt_" + prefix]["access_key"],
                    secret_key=self.apikey["xt_" + prefix]["secret_key"],
                ),
                "mid_price": 0,
                "last_amount": -1,
                "delta_position": 0,
            }
            if symbol == "stg5l_usdt":
                symbols_info[symbol]["init_amount"] = 10000
                symbols_info[symbol]["init_usdt"] = 10000
            else:
                symbols_info[symbol]["init_amount"] = 500000
                symbols_info[symbol]["init_usdt"] = 20000

        return symbols_info

    def get_depth_data(self, symbol):
        depth = self.symbols[symbol]["client"].get_depth(symbol)
        logging.debug(f"depth {depth}")
        return depth

    def get_mid_price(self, depth) -> float:
        """Calculates the mid price from the order book."""

        best_bid = float(depth["bids"][0][0])
        best_ask = float(depth["asks"][0][0])

        return (best_bid + best_ask) / 2

    def get_position3_xt(self):
        for symbol, value in self.symbols.items():
            try:
                depth = self.get_depth_data(symbol)
                mid_price = self.get_mid_price(depth)
            except Exception as e:
                mid_price = float(
                    open("net_value_" + symbol.split("_")[0], "r", encoding="utf8")
                    .read()
                    .strip()
                )
            # self.symbols[symbol]["mid_price"] = mid_price

            info = value["client"].balances(value["currency"])
            # logging.info(info)
            for currency in info["assets"]:
                if currency["currency"] == symbol.split("_")[0]:
                    xt_coin_reduce = round(
                        value["init_amount"] - float(currency["totalAmount"]), 2
                    )
                    xt_coin_remain = float(currency["totalAmount"])
                    xt_coin_reduce_convertusdt = round(xt_coin_reduce * mid_price, 2)
                elif currency["currency"] == "usdt":
                    xt_usdt_remain = round(float(currency["convertUsdtAmount"]), 2)

            self.symbols[symbol]["xt_coin_reduce"] = xt_coin_reduce
            self.symbols[symbol]["xt_coin_reduce_convertusdt"] = (
                xt_coin_reduce_convertusdt
            )
            self.symbols[symbol]["xt_usdt_remain"] = xt_usdt_remain
            self.symbols[symbol]["xt_coin_remain"] = xt_coin_remain

    def get_position_bn(self):
        from binance import Client

        api_key = "lDHuIavZpEErNyC27HGnJSMOb0ArGR0lBBNJGEWU56NnxjxUwljgnBn97RFScuZN"
        api_secret = "zlo0LVMVqNTDJRCby7QZMYuPRSY8QMLOokK6UnmqtUZ5YDP9GIqsvqCnXh7bAPSV"
        bnclient = Client(api_key, api_secret)

        info = bnclient.futures_position_information()
        for asset in info:
            if asset["symbol"] == "STGUSDT":
                bn_coin_remain = float(asset["positionAmt"])
                bn_entry_price = float(asset["entryPrice"])
                bn_cost_usdt = round(bn_coin_remain * bn_entry_price, 2)
                bn_unRealizedProfit = float(asset["unRealizedProfit"])
        info = bnclient.futures_account()
        for asset in info["assets"]:
            if asset["asset"] == "USDT":
                bn_usdt_remain = round(float(asset["marginBalance"]), 2)

        return (
            bn_usdt_remain,
            bn_unRealizedProfit,
            bn_cost_usdt,
            bn_coin_remain,
            bn_entry_price,
        )

        # logging.info(f"xt_usdt_remain {xt_usdt_remain} xt_coin_remain {xt_coin_remain} xt_coin_remain_convertusdt {xt_coin_remain_convertusdt} xt_mid_price {mid_price} xt_average_price {xt_average_price} bn_coin_remain {bn_coin_remain} bn_entry_price {bn_entry_price} bn_cost_usdt {bn_cost_usdt} bn_unRealizedProfit {bn_unRealizedProfit} bn_usdt_remain {bn_usdt_remain}")
        # time.sleep(5)


config = {
    "stats_interval": 5,
    "leverage": 1,
    "symbols": ["stg5l_usdt", "stg5s_usdt", "stg3l_usdt", "stg3s_usdt"],
}


with open("APIKey.json", "r", encoding="utf8") as input:
    apikey = json.load(input)

etf_stats = Etf_stats(apikey=apikey, symbols=config["symbols"])

while True:
    etf_stats.get_position3_xt()
    (
        bn_usdt_remain,
        bn_unRealizedProfit,
        bn_cost_usdt,
        bn_coin_remain,
        bn_entry_price,
    ) = etf_stats.get_position_bn()

    xt_coin_reduce_sum = 0
    xt_coin_reduce_convertusdt_sum = 0
    xt_usdt_remain_sum = 0
    logging_info = f"xt_coin_reduce "
    for symbol, value in etf_stats.symbols.items():
        xt_coin_reduce_sum += value["xt_coin_reduce"]
        xt_coin_reduce_convertusdt_sum += value["xt_coin_reduce_convertusdt"]
        xt_usdt_remain_sum += value["xt_usdt_remain"]
        logging_info += (
            f"({symbol}: {value['xt_coin_reduce']} {value['xt_coin_remain']}) "
        )

    logging_info += f"xt_usdt_remain_sum {xt_usdt_remain_sum} xt_coin_reduce_sum {xt_coin_reduce_sum} xt_coin_reduce_convertusdt_sum {xt_coin_reduce_convertusdt_sum} bn_unRealizedProfit {bn_unRealizedProfit} bn_usdt_remain {bn_usdt_remain} bn_cost_usdt {bn_cost_usdt} bn_coin_remain {bn_coin_remain} bn_entry_price {bn_entry_price}"
    import time
    from datetime import datetime

    now = datetime.now()
    # print(now)
    logging.info(logging_info)

    time.sleep(config["stats_interval"])
