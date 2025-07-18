from etf.xt import Spot
import logging

logging.shutdown()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
)
data = []
pnl = []
trade = []
stg5l_coin = []
stg5s_coin = []
stg3l_coin = []
stg3s_coin = []
#with open('/root/.pm2/logs/etf-stats-aggregation-error.log', 'r') as input:
with open('/root/.pm2/logs/etf-stats-aggregation-error__2025-05-07_00-00-00.log', 'r') as input:
    for line in input:
        #etf-stats-aggregation-error__2025-04-19_00-00-00.log
        if "etf_stats.py:187" in line or "INFO" not in line:
            continue
        #print(line)
        date = line.strip().split(' - ')[0]
        line = line.strip().split(' - ')[-1]
# 2025-04-21 23:02:15,003 - INFO - etf_stats_aggregation.py:139 - xt_coin_reduce (stg5l_usdt: 45.83) (stg5s_usdt: 0.02) (stg3l_usdt: 8.39) (stg3s_usdt: 0.0) xt_usdt_remain_sum 69963.27 xt_coin_reduce_sum 54.24 xt_coin_reduce_convertusdt_sum 70.8 bn_unRealizedProfit 1.31896336 bn_usdt_remain 2530.15
        #print(line)
        line_1 = line.split(' ')
        #print(line_1)
        #xt_coin_stg5l = float(line_1[2][:-1])
        #xt_coin_stg5s = float(line_1[4][:-1])
        #xt_coin_stg3l = float(line_1[6][:-1])
        #xt_coin_stg3s = float(line_1[8][:-1])

        line_2 = line.split(') ')[-1]
        #xt_coin_reduce = 
        xt_usdt_remain = float(line_2.split(' ')[1])
        bn_usdt_remain = float(line_2.split(' ')[-1])
        xt_coin_reduce_sum = float(line_2.split(' ')[3])
        xt_xt_coin_reduce_convertusdt_sum = float(line_2.split(' ')[5])
        bn_unRealizedProfit = float(line_2.split(' ')[7])
        if len(data) > 0:
            xt_pnl = xt_usdt_remain + xt_xt_coin_reduce_convertusdt_sum - data[-1][1] - data[-1][2]
            bn_pnl = bn_usdt_remain - data[-1][-1]
            #print(xt_pnl, bn_pnl)
            pnl.append(xt_pnl + bn_pnl)
        if len(trade) == 0 or xt_coin_reduce_sum != trade[-1][-1]:                    
            trade.append([date, xt_coin_reduce_sum])    
       # if len(stg5l_coin) == 0 or xt_coin_stg5l != stg5l_coin[-1][-1]:
       #     stg5l_coin.append([date, xt_coin_stg5l])
       # if len(stg5s_coin) == 0 or xt_coin_stg5s != stg5s_coin[-1][-1]:
       #     stg5s_coin.append([date, xt_coin_stg5s])
       # if len(stg3l_coin) == 0 or xt_coin_stg3l != stg3l_coin[-1][-1]:
       #     stg3l_coin.append([date, xt_coin_stg3l])
       # if len(stg3s_coin) == 0 or xt_coin_stg3s != stg3s_coin[-1][-1]:
       #     stg3s_coin.append([date, xt_coin_stg3s])

        data.append([date, xt_usdt_remain, xt_xt_coin_reduce_convertusdt_sum, bn_unRealizedProfit, bn_usdt_remain])
print(sum(pnl), len(trade), trade, data[-1][0], data[-1][1], data[-1][2], data[-1][3], data[-1][-1])
print("stg5l_coin:", stg5l_coin)
print("stg5s_coin:", stg5s_coin)
print("stg3l_coin:", stg3l_coin)
print("stg3s_coin:", stg3s_coin)

class Etf_stats():
    def __init__(self, apikey, symbols):
        self.apikey = apikey
        self.symbols = self.init_symbols(symbols)
        
    def init_symbols(self, symbols):
        symbols_info = {}
        for symbol in symbols:
            prefix = symbol.split("_")[0]
            symbols_info[symbol] = {
                "currency": [prefix.upper(), "usdt"],
                "client": Spot(host="https://sapi.xt.com", access_key=self.apikey["xt_" + prefix]["access_key"], secret_key=self.apikey["xt_" + prefix]["secret_key"]),
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
        #logging.info(f"depth {depth}")
        return depth
        
    def get_mid_price(self, depth) -> float:
        """Calculates the mid price from the order book."""
    
        best_bid = float(depth['bids'][0][0])
        best_ask = float(depth['asks'][0][0])
    
        return (best_bid + best_ask) / 2
    
    def get_liquidity(self):
        for symbol, value in self.symbols.items():
            try:
                depth = self.get_depth_data(symbol)
                mid_price = self.get_mid_price(depth)
            except Exception as e:
                mid_price = float(open("net_value_" + symbol.split("_")[0], 'r', encoding='utf8').read().strip())
            #self.symbols[symbol]["mid_price"] = mid_price
            
            #range = 0.02
            bids_usdt_002 = 0
            asks_usdt_002 = 0
            for bid in depth['bids']:
                #print("bid", bid, mid_price * 0.98)
                if float(bid[0]) >= mid_price * (1 - 0.1):
                    bids_usdt_002 += float(bid[0]) * float(bid[1])
            for ask in depth['asks']:
                #print("ask", ask, mid_price * 1.02)
                if float(ask[0]) <= mid_price * (1 + 0.1):
                    asks_usdt_002 += float(ask[0]) * float(ask[1])
            
            print(symbol, mid_price, bids_usdt_002, asks_usdt_002)

config = {
    "stats_interval": 5,
    "leverage": 1,
    "symbols": ["stg5l_usdt", "stg5s_usdt", "stg3l_usdt", "stg3s_usdt"],
}

import json
with open('APIKey.json', 'r', encoding='utf8') as input:
    apikey = json.load(input)

etf_stats = Etf_stats(apikey=apikey, symbols=config["symbols"])

#depth = etf_stats.get_depth_data(config["symbols"][0])
etf_stats.get_liquidity()
