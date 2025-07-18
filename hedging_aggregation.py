from binance import Client
from etf.xt import Spot
import time
import math
import logging
import json
import pandas as pd
from pnl_bot import LarkBot
from datetime import datetime
import redis

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
    )
    
def round_down(value, precision):
    factor = 10 ** precision
    return math.floor(value * factor) / factor

class XtClient():
    def __init__(self, apikey, symbols):
        self.apikey = apikey
        self.symbols = self.init_symbols(symbols)
        self.r = redis.Redis(host='localhost', port=6379, db=0) 
        
    def init_symbols(self, symbols):
        symbols_info = {}
        for symbol in symbols:
            prefix = symbol.split("_")[0]
            symbols_info[symbol] = {
                "currency": [prefix.upper()],
                "client": Spot(host="https://sapi.xt.com", access_key=self.apikey["xt_" + prefix]["access_key"], secret_key=self.apikey["xt_" + prefix]["secret_key"]),
                "mid_price": None,
                "last_amount": -1,
                "delta_position": None,
                "delta_amount": None,
            }

            if symbol == "stg5l_usdt":
                symbols_info[symbol]["init_amount"] = 10000
            else:
                symbols_info[symbol]["init_amount"] = 500000
        
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

    def get_position3(self):
        logging.info("get_position3")
        for symbol, value in self.symbols.items():
             
            try:
                mid_price = float(self.r.get('netvalue_' + symbol.split('_')[0]).decode())
                # mid_price = float(open('net_value_' + symbol.split('_')[0], 'r', encoding='utf8').read().strip())
                     
            except Exception as e1:
                logging.info('netvalue_' + symbol.split('_')[0])
                logging.info(e1)
                try: 
                    depth = self.get_depth_data(symbol)
                    mid_price = self.get_mid_price(depth)
                except Exception as e2:
                    logging.info(e2)        
                    return False

            self.symbols[symbol]["mid_price"] = mid_price
            info = value["client"].balances(value["currency"])
            for currency in info["assets"]:
                if currency["currency"] == symbol.split('_')[0]:
                    
                    if value["last_amount"] > 0:
                        delta_amount = float(currency["totalAmount"]) - value["last_amount"] # if < 0, user buy, > 0, user sell
                    else:
                        try:
                            value["last_amount"] = float(open('last_amount_' + symbol, 'r', encoding='utf8').read().strip())
                            delta_amount = float(currency["totalAmount"]) - value["last_amount"]
                        except Exception as e:
                            logging.info(e)
                            delta_amount = 0

                    delta_position = delta_amount * mid_price
                        
                    self.symbols[symbol]["last_amount"] = float(currency["totalAmount"])
                    self.symbols[symbol]["delta_position"] = delta_position
                    self.symbols[symbol]["delta_amount"] = delta_amount

                    with open("last_amount_" + symbol, "w") as f:
                        f.write(str(self.symbols[symbol]["last_amount"]) + '\n')
        return True
        
class Hedge():
    def __init__(self, apikey, config):
        self.client = Client(apikey["bn"]["access_key"], apikey["bn"]["secret_key"])
        self.init_position = None
        self.position = 0
        self.sent_order = False
        self.remain_amount = 0
        self.remain_value = 0
        self.xt_clients = XtClient(apikey, config["symbols"])
        self.config = config

        # orders
        self.orders = []
        self.failed_orders = []

        APP_ID = "cli_a888a93b54389029"
        APP_SECRET = "M44bRQxX9oJKFFP4USGaufyMKyA62hbw"
        # Etf Prod Alert
        
        # https://open.larksuite.com/open-apis/bot/v2/hook/
        # bfcc4b0a-15ce-4775-a958-24d4ad02ad3f
        self.bot = LarkBot(APP_ID, APP_SECRET)

    def create_order(self, symbol, side, price, amount):
        try:
            res = self.client.futures_create_order(
                symbol=symbol,
                side=side,
                type="LIMIT",
                price=price,
                quantity=amount,
                timeinforce="GTC"
            )
        except Exception as e:
            logging.info(e)
            return False

        return True
            
    def check_open_orders(self):
        res = self.client.futures_get_open_orders()
        logging.info(res)
        value = 0
        #if res:
            # TODO: get the negation operation data
        return value
    
    def get_position_bn(self):
        info = self.client.futures_position_information()
        for asset in info:
            if asset["symbol"] == self.config["bnsymbol"]:
                bn_coin_remain = float(asset["positionAmt"]) 
                #bn_coin_remain = -1 * bn_coin_remain if float(asset["positionAmt"]) < 10000 else bn_coin_remain
                bn_entry_price = float(asset["entryPrice"])
                bn_cost_usdt = round(bn_coin_remain * bn_entry_price, 2)
                bn_unRealizedProfit = float(asset["unRealizedProfit"])
        
        return bn_coin_remain, bn_entry_price, bn_unRealizedProfit
    
    def run(self):
        
        while True:
            time.sleep(self.config["Hedging_interval"]) # 20s
            res = self.client.futures_change_leverage(symbol=self.config["bnsymbol"], leverage=self.config["leverage"])
            logging.info(res)
            
            if not self.xt_clients.get_position3():
                continue
            
            bn_coin_remain, bn_entry_price, bn_unRealizedProfit = self.get_position_bn()
            # bn_position = bn_coin_remain * bn_entry_price + bn_unRealizedProfit

            xt_delta_position = 0
            xt_position = 0
            xt_delta_amount = 0
            symbol_amount = ''
            symbol_delta_amount = ''
            symbol_delta_amount_heding = ''
            symbol_price = ''
            symbol_delta_position = ''
            symbol_position = ''
            for symbol in self.xt_clients.symbols:
                # for incremental hedging
                delta_position = self.xt_clients.symbols[symbol]["delta_position"] * int(symbol.split("_")[0][-2])
                last_amount = self.xt_clients.symbols[symbol]["last_amount"]
                mid_price = self.xt_clients.symbols[symbol]["mid_price"]
                delta_amount = self.xt_clients.symbols[symbol]["delta_amount"] 
                delta_amount_heding = self.xt_clients.symbols[symbol]["delta_amount"] * int(symbol.split("_")[0][-2])
                
                symbol_amount += symbol + ' ' + str(last_amount) + ' '
                symbol_delta_amount += symbol + ' ' + str(delta_amount) + ' '
                symbol_delta_amount_heding += symbol + ' ' + str(delta_amount_heding) + ' '
                symbol_price += symbol + ' ' + str(round(mid_price, 6)) + ' '

                # for comparasion hedging
                amount = self.xt_clients.symbols[symbol]["last_amount"] - self.xt_clients.symbols[symbol]["init_amount"]
                mid_price = self.xt_clients.symbols[symbol]["mid_price"]
                position_hedging = amount * mid_price * int(symbol.split("_")[0][-2])
                
                if symbol.split("_")[0][-1] == "s" :
                    delta_position = -delta_position
                    position_hedging = -position_hedging

                symbol_delta_position += symbol + ' ' + str(delta_position) + ' '
                symbol_position += symbol + ' ' + str(round(position_hedging, 6)) + ' '
                # xt_delta_position += delta_position
                xt_position += position_hedging
                xt_delta_amount += delta_amount 

            logging.info(symbol_delta_position)
            # check open orders
            # TODO: 
            open_value = 0
            price = round(float(self.client.futures_symbol_ticker(
                symbol=config["bnsymbol"]
            )['price']), config["precision_price"])

            bn_position = price * bn_coin_remain

            if xt_delta_amount == 0 and abs(xt_position + bn_position) > 0.05 * abs(bn_position):
                logging.info("xt_delta_amount == 0 and xt_position + bn_posiiton > 0.01 * bn_posiiton")
                CHAT_ID = "bfcc4b0a-15ce-4775-a958-24d4ad02ad3f"
                message = '需要对冲(没有用户交易)\n'
                message += '【时间】' + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '\n'
                message += '【xt持仓价值(币对)】' + symbol_position + '\n'
                message += '【xt币对价格】' + symbol_price + '\n'
                message += '【xt持仓价值】' + str(xt_position) + '\n'
                message += '【bn持仓价值】' + str(bn_position) + '\n'
                message += '【bn合约价格】' + str(price) + '\n'
                message += '【bn持仓数量】' + str(bn_coin_remain) + '\n'
                message += '【bn持仓均价】' + str(bn_entry_price) + '\n'
                message += '【bn未实现盈亏】' + str(bn_unRealizedProfit) + '\n'
                message += '【净敞口】' + str(round(xt_position + bn_position, 2)) + '\n'
                #self.bot.send_text_message(CHAT_ID, message)

                continue                
            # xt_position < 0 user buy, we buy, bn_position > 0
            # xt_position > 0 user sell, we sell, bn_position < 0
            if abs(xt_position + bn_position) <= 0.05 * abs(bn_position):
                logging.info(f"abs({xt_position} + {bn_position}) <= 0.05 * abs({bn_position})")
                continue
            
            xt_delta_position = xt_position + bn_position

            if xt_delta_position == 0 and self.remain_amount == 0 and open_value == 0:
                logging.info("xt_delta_position == 0 and self.remain_amount == 0 and open_value == 0")
                continue

            # price = round(float(self.client.get_symbol_ticker(
            
            
            hedging_delta = xt_delta_position + open_value + self.remain_amount * price 
            amount_orig = hedging_delta / price
            side = "BUY" if amount_orig < 0 else "SELL"

            self.hedging_data = [{
                "xt_delta_position": xt_delta_position,
                "hedging_open_value": open_value,
                "hedging_price": price,
                "hedging_amount_remain": self.remain_amount,
                "hedging_delta": hedging_delta,
                "hedging_amount_new": abs(xt_delta_position + open_value) / price,
                "hedging_amount": amount_orig,
                "hedging_side": side,
                }]        
            
            amount_orig = abs(amount_orig)
            amount = round_down(amount_orig, self.config["precision_amount"])

            self.hedging_data[0].update({
                "hedging_amount_round": amount,
                })
            
            logging.info(f"Hedging: {self.hedging_data}")
            
            if config["Enable_hedging"]:
                if amount >= float(f"1e-{self.config['precision_amount']}"):            
                    result = self.create_order(self.config["bnsymbol"], side, price, amount)
                    CHAT_ID = "bfcc4b0a-15ce-4775-a958-24d4ad02ad3f"
                    message = '发生一次对冲\n'
                    message += '【时间】' + datetime.now().strftime("%Y-%m-%d %H:%M:%S") + '\n'
                    message += '【币对数量】' + symbol_amount + '\n'
                    message += '【币对数量变化】' + symbol_delta_amount + '\n'
                    message += '【币对应对冲数量】' + symbol_delta_amount_heding + '\n'
                    message += '【币对价格】' + symbol_price + '\n'
                    message += '【应对冲价值】' + str(xt_delta_position) + '\n'
                    message += '【方向】买入\n' if side == "BUY" else "【方向】卖出\n"
                    message += '【价格】' + str(price) + '\n'
                    message += '【数量】' + str(amount) + '\n'
                    # message += '【实际对冲价值】' + str(price * amount)
                    message += '【xt持仓价值】' + str(xt_position) + 'USDT\n'
                    message += '【bn持仓价值】' + str(bn_position) + 'USDT\n'
                    message += '【bn未实现盈亏】' + str(bn_unRealizedProfit) + '\n'
                    self.bot.send_text_message(CHAT_ID, message)
                else:
                    logging.info("amount < precision_amount, skip creat order")
                    result = False
                
             
config = {
    "bnsymbol": "STGUSDT",
    "Hedging_interval": 20,
    "leverage": 1,
    "symbols": ["stg5l_usdt", "stg5s_usdt", "stg3l_usdt", "stg3s_usdt"],
    "precision_amount": 0,
    "precision_price": 4,
    "Enable_hedging": True
}

with open('APIKey.json', 'r', encoding='utf8') as input:
    apikey = json.load(input)
     
hedge = Hedge(apikey, config)
hedge.run()

