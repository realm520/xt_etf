# -*- coding:utf-8 -*-

"""
Author: AllenBrother
Date:   2022/12/26
Email:  huangyongjie088@gmail.com
"""

import numpy as np


class Orderbook:
    """
    create varied orderbook
    power : 幂函数
    linear : 线性函数
    """

    def __init__(self, bid_0: float = None, ask_0: float = None, layer: int = 0, prec_price: int = None,
                 prec_amount: int = None):
        self.bid_0 = bid_0
        self.ask_0 = ask_0
        self.layer = layer
        self.prec_price = prec_price
        self.prec_amount = prec_amount

        assert layer > 0, f"illegal layer <= 0"

    @classmethod
    def prec_to_tick(cls, prec_price):
        a = "0."
        for n in range(prec_price):
            a += "0"
        return float(a[:-1] + "1")

    @classmethod
    def num_step(cls, n, step):
        """
        @param n:
        @param step: 步进值 0.5 0.05等
        @return:
        """
        r = n % step
        q = n // step
        if r < step / 2:  # 四舍五入
            r = 0
        else:
            r = step
        return step * q + r

    def sparse(self, make_price_name, price, sparse):
        if make_price_name == "linear":
            min_price = round(price - float(sparse) * float(self.prec_to_tick(self.prec_price)), self.prec_price)
            max_price = round(price + float(sparse) * float(self.prec_to_tick(self.prec_price)), self.prec_price)
            return min_price, max_price
        elif make_price_name == "power":
            min_price = round(price * (1 - sparse), self.prec_price)
            max_price = round(price * (1 + sparse), self.prec_price)
            return min_price, max_price
        elif make_price_name == "power2":
            min_price = round(price * (1 - sparse), self.prec_price)
            max_price = round(price * (1 + sparse), self.prec_price)
            return min_price, max_price

    def power(self, direction, price_percent):
        if direction == "bid":
            f = lambda alpha, beta, x: round(alpha * (1 - beta) ** x, self.prec_price)
            init_price = self.bid_0
        elif direction == "ask":
            f = lambda alpha, beta, x: round(alpha * (1 + beta) ** x, self.prec_price)
            init_price = self.ask_0
        else:
            assert False, "'direction' not in [bid,ask]"

        return [f(init_price, price_percent, i + 1) for i in range(0, self.layer)]
    
    def power2(self, direction, price_percent):
        if direction == "bid":
            f = lambda alpha, beta, x: round(alpha * (np.e) ** (-beta * x), self.prec_price)
            init_price = self.bid_0
        elif direction == "ask":
            f = lambda alpha, beta, x: round(alpha * (np.e) ** (beta * x), self.prec_price)
            init_price = self.ask_0
        else:
            assert False, "'direction' not in [bid,ask]"
        # print("call power2")
        return [f(init_price, price_percent, i + 1) for i in range(0, self.layer)]

    def linear(self, direction, price_tick, price_step=None):
        if direction == "bid":
            f = lambda alpha, beta, x: round(alpha - beta * x, self.prec_price)
            init_price = self.bid_0
        elif direction == "ask":
            f = lambda alpha, beta, x: round(alpha + beta * x, self.prec_price)
            init_price = self.ask_0
        else:
            assert False, "'direction' not in [bid,ask]"
        # TODO：队列首项替换为初始值
        if price_step is None:
            return [f(init_price, price_tick, i + 1) for i in range(0, self.layer)]
        else:
            return [f(init_price, price_step, i + 1) for i in range(0, self.layer)]

    def normal(self, mean, scale, size):
        return np.random.normal(mean, scale, size)

    def uniform(self, min, max, size):
        return np.random.uniform(min, max, size)

    def powera(self, init_price, price_percent):
        f = lambda alpha, beta, x: int(alpha) * (np.e) ** (beta * x)
        return [f(init_price, price_percent, i + 1) for i in range(0, self.layer)]
        
    def make(self, direction, make_price, make_amount, *args, **kwargs):
        """
        @param direction: bid ask 买卖方向
        @param make_price: linear power 线性/幂函数
        @param make_amount: normal uniform 正态/均匀
        @param args:
        @param kwargs: price_percent：幂函数底数 price_tick：线性函数delta
                       mean：正态均值 scale：正态标准差 min：均匀最小值 max：均匀最大值 sparse:稀疏orderbook
        @return: orderbook
        """
        make_price_name = getattr(make_price, "__name__")
        make_amount_name = getattr(make_amount, "__name__")
        price = []
        amount = []
        if make_price_name == "linear":
            price = make_price(direction, kwargs["price_tick"], kwargs["price_step"])
        elif make_price_name == "power":
            price = make_price(direction, kwargs["price_percent"])
        elif make_price_name == "power2":
            price = make_price(direction, kwargs["price_percent"])
        if make_amount_name == "normal":
            amount = make_amount(kwargs["mean"], kwargs["scale"], self.layer)
        elif make_amount_name == "uniform":
            amount = make_amount(kwargs["min"], kwargs["max"], self.layer)
        elif make_amount_name == "powera":
            init_price = self.normal(kwargs["mean"], kwargs["scale"], 1)
            amount = make_amount(init_price, kwargs["price_percent"])


        # bid 处理价格小于0
        if direction == "bid":
            for i, p in enumerate(price):
                if p <= 0:
                    price[i] = self.prec_to_tick(self.prec_price)

        batch_order = []
        for i, p in enumerate(price):
            min_p, max_p = self.sparse(make_price_name, float(p), kwargs["sparse"])
            if direction == "bid":
                # TODO：bid订单 min——max 进行范围处理
                batch_order.append(
                    {"price": p,
                     "amount": round(amount[i], kwargs["prec_amount"]), "direction": "bid",
                     "min_price": round(min_p, self.prec_price),
                     "max_price": round(max_p, self.prec_price),
                     "order_id": []})
            elif direction == "ask":
                batch_order.append(
                    {"price": p,
                     "amount": round(amount[i], kwargs["prec_amount"]), "direction": "ask",
                     "min_price": round(min_p, self.prec_price),
                     "max_price": round(max_p, self.prec_price),
                     "order_id": []})
        return batch_order

def get_orderbook(mid_price=99999.99, bid_ask_spread=None):

    kwargs = {
        "price_tick": 100,
        "price_step": 10,
        "price_percent": 1e-2,
        "mean": 50,
        "scale": 1,
        "sparse": 1e-3,
        #"prec_price": 4, #
        "prec_price": 6,
        "prec_amount": 2,
        "bid_ask_spread": 0.01,
        "layer": 30
    }
    # mid_price = 99999.99 # netvalue replace
    if bid_ask_spread is not None:
        kwargs["bid_ask_spread"] = bid_ask_spread

    bid_0 = mid_price - ( (mid_price * kwargs["bid_ask_spread"])/2 )
    ask_0 = mid_price + ( (mid_price * kwargs["bid_ask_spread"])/2 )

    orderbook = Orderbook(bid_0=bid_0, ask_0=ask_0, layer=kwargs["layer"], prec_price=kwargs["prec_price"])

    make_price_fn_bid = orderbook.power2
    make_price_fn_ask = orderbook.power2

    make_amount_fn = orderbook.powera

    batch_order_bid = orderbook.make('bid', make_price_fn_bid, make_amount_fn, None, **kwargs) 
    batch_order_ask = orderbook.make('ask', make_price_fn_ask, make_amount_fn, None, **kwargs)  

    return batch_order_bid, batch_order_ask
