# -*- coding:utf-8 -*-

"""
Author: AllenBrother
Date:   2024/11/28
Email:  huangyongjie088@gmail.com
"""

from etf.exchange.xt import Spot
from etf.utils.ds import Queue
from loguru import logger
import time
import redis
import argparse


class NetValue:
    def __init__(
        self,
        symbol,
        m_lever,
        init_net_value=1.0,
        daily_fee=0.001,
        time_gap_second=10,
        rebalance=0.05,
        long=True,
    ):
        self.symbol = symbol
        self.time_gap_fee = (
            daily_fee / (24 * 60 * 60) * time_gap_second
        )  # time_gap 管理费率
        self.time_gap_second = time_gap_second
        self.underlying_mid_price = 0
        self.underlying_mid_price_queue = Queue(2)
        self.rebalance = rebalance
        self.m_lever = m_lever
        self.long = long

        self.r = redis.Redis(host="localhost", port=6379, db=0)
        self.redis_key = (
            "netvalue_" + self.symbol.split("_")[0] + str(self.m_lever) + "l"
            if self.long
            else "netvalue_" + self.symbol.split("_")[0] + str(self.m_lever) + "s"
        )
        if self.r.exists(self.redis_key):
            print("Key 'netvalue' exists in redis.")
            init_net_value = float(self.r.get(self.redis_key).decode())
        else:
            print("Key 'netvalue' does not exist in redis. Using default value 1.0")
            init_net_value = 1.0

        self.net_value = {
            "net_value": init_net_value,
            "create_ts": int(time.time() * 1000),
            "update_ts": 0,
        }
        self.m_lever = m_lever

    def update_mid_price(self):
        depth = Spot(
            host="https://sapi.xt.com", access_key="", secret_key=""
        ).get_depth(symbol=self.symbol, limit=5)
        if depth:
            bid_0_price = float(depth["bids"][0][0])
            ask_0_price = float(depth["asks"][0][0])
            mid_price = (bid_0_price + ask_0_price) / 2
            logger.debug(f"{self.symbol} mid_price:{mid_price}")
            return mid_price
        else:
            logger.error(f"获取{self.symbol}市场深度失败")
            return

    def cal_net_value(self):
        if len(self.underlying_mid_price_queue) == 2:
            p0 = self.underlying_mid_price_queue.get(0)
            p1 = self.underlying_mid_price_queue.get(1)
            side = 1 if p1 > p0 else -1
            net_value = self.net_value["net_value"]
            while True:
                v = (p1 - p0) / p0
                if abs(v) > self.rebalance:
                    p0 = p0 * (1 + side * self.rebalance)
                    net_value = net_value * (1 - self.m_lever * side * self.rebalance)
                    logger.debug(
                        f"{self.symbol} 底层资产价格剧烈变化({v}):{(p0, p1)} rebalancing "
                    )
                    continue
                else:
                    x = abs(v)
                    net_value = net_value * (1 - self.m_lever * side * x)
                    logger.debug(f"{self.symbol} 底层资产价格变化({v}):{(p0, p1)}")
                    break

            return net_value
        else:
            logger.debug(
                f"underlying_mid_price_queue:{self.underlying_mid_price_queue} length != 2"
            )
            return None

    def cal_fee(self, net_value):
        net_value_dec_fee = net_value * (1 - self.time_gap_fee)
        return net_value_dec_fee

    def run(self):
        while True:
            try:
                mid_price = self.update_mid_price()
            except Exception as e:
                logger.debug(e)
                time.sleep(1)
                continue

            if not mid_price:
                continue  # 没有获取到最新的数据，直接返回
            self.underlying_mid_price_queue.put(mid_price)
            net_value = self.cal_net_value()
            if not net_value:
                continue
            # 调整管理费用
            net_value_dec_fee = self.cal_fee(net_value)
            self.net_value["net_value"] = net_value_dec_fee
            self.net_value["update_ts"] = int(time.time() * 1000)
            logger.debug(
                f"{self.symbol} net_value:{net_value},net_value_dec_fee:{self.net_value}"
            )

            self.r.set(self.redis_key, str(self.net_value["net_value"]))

            time.sleep(self.time_gap_second)


def str2bool(v):
    if isinstance(v, bool):
        return v
    if v.lower() in ("yes", "true", "t", "1"):
        return True
    elif v.lower() in ("no", "false", "f", "0"):
        return False
    else:
        raise argparse.ArgumentTypeError("Boolean value expected.")


def get_parser():
    parser = argparse.ArgumentParser(
        description="ETF hedging or rebalancing strategy",
        formatter_class=argparse.ArgumentDefaultsHelpFormatter,
    )

    parser.add_argument("--symbol", type=str, default="stg_usdt", help="Spot symbol.")
    parser.add_argument(
        "--rebalance", type=float, default=0.05, help="Rebalance threshold ratio."
    )
    parser.add_argument("--m-lever", type=int, default=5, help="Leverage multiplier.")
    parser.add_argument(
        "--interval", type=int, default=1, help="Loop interval in seconds."
    )
    parser.add_argument(
        "--long",
        type=str2bool,
        default=False,
        help="Operate in long mode (True/False).",
    )

    return parser


if __name__ == "__main__":
    parser = get_parser()
    args = parser.parse_args()

    config = {
        "symbol": args.symbol,
        "rebalance": args.rebalance,
        "m_lever": args.m_lever,
        "interval": args.interval,
        "long": args.long,
    }
    NetValue(
        symbol=config["symbol"],
        m_lever=config["m_lever"],
        time_gap_second=config["interval"],
        rebalance=config["rebalance"],
        long=config["long"],
    ).run()
