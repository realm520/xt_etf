from binance import Client

import time
import math
import logging
import pandas as pd


def _load_binance_keys():
    """
    加载 Binance API 密钥（使用统一配置加载器）
    
    加载优先级：
    1. 环境变量 BN_ACCESS_KEY / BN_SECRET_KEY
    2. .env 文件中的 bn_access_key / bn_secret_key
    3. APIKey.json 文件
    """
    try:
        from etf.config import load_binance_api_keys
        keys = load_binance_api_keys()
        return keys["access_key"], keys["secret_key"]
    except ValueError as e:
        logging.warning(f"未找到 Binance API 密钥: {e}")
        logging.warning("对冲功能将不可用")
        return None, None
    except Exception as e:
        logging.error(f"加载 Binance API 密钥失败: {e}")
        return None, None


def round_down(value, precision):
    factor = 10 ** precision
    return math.floor(value * factor) / factor


class Hedge():
    def __init__(self):
        api_key, api_secret = _load_binance_keys()
        if api_key and api_secret:
            self.client = Client(api_key, api_secret)
        else:
            self.client = None
            logging.warning("Hedge 初始化时未找到 API 密钥，对冲功能禁用")
        self.init_position = None
        self.position = 0
        self.sent_order = False
        self.remain_amount = 0
        self.remain_value = 0

        # orders
        self.orders = []
        self.failed_orders = []

    def get_position(self, config, result, side, hedging_delta, xt_position, amount, amount_orig, price):
        '''
        result: True - No API bugs, False: API bugs. Remain all amount_orig 

        '''
        info = self.client.futures_position_information()
        logging.info(info)
        if not result: # 1. API bugs 2. less than 0.0001
            if len(info) == 0:
                crossUnPnl = 0
            else:
                crossUnPnl = float(info[0]["unRealizedProfit"])
            logging.info("less then 0.0001")
            self.hedging_value = 0
            self.remain_value = -1 * (abs(hedging_delta) - self.hedging_value) if side == "BUY" else abs(hedging_delta) - self.hedging_value
            logging.info(f"{side} remain value: {self.remain_value}, hedging_delta {hedging_delta}")
            self.remain_amount = -1 * amount_orig if side == "BUY" else amount_orig
        else:
            if len(info) == 0 or float(info[0]["entryPrice"]) == 0: # 1. 2-direction hedged, 2. open order Status NEW
                crossUnPnl = 0
                self.hedging_value = price * amount
                self.remain_value = -1 * (abs(hedging_delta) - self.hedging_value) if side == "BUY" else abs(hedging_delta) - self.hedging_value
                self.remain_amount = -1 * (amount_orig - amount) if side == "BUY" else amount_orig - amount
                self.create_order(config["bnsymbol"], "SELL" if side == "BUY" else "BUY", price, amount)
            else:
                crossUnPnl = float(info[0]["unRealizedProfit"])
                self.hedging_value = float(info[0]["entryPrice"]) * amount
                self.remain_value = -1 * (abs(hedging_delta) - self.hedging_value) if side == "BUY" else abs(hedging_delta) - self.hedging_value
                self.remain_amount = self.remain_value / float(info[0]["entryPrice"])

        self.hedging_data[0].update({"hedging_value": self.hedging_value, "remain_value": self.remain_value, "remain_amount": self.remain_amount, "crossUnPnl": crossUnPnl})
        logging.info(self.hedging_data[0])
        # check position
        self.position += -1 * self.hedging_value if side == "SELL" else self.hedging_value
        self.position += -1 * crossUnPnl if side == "SELL" else crossUnPnl
        bn_position = self.position - self.remain_value if side == "BUY" else self.position + self.remain_value

        if xt_position + bn_position == 0:
            logging.info(f"PRICE IS OK - xt_position: {xt_position} bn_position: {bn_position}")
            result = True
        else:
            if abs(xt_position) > abs(bn_position):
                logging.info(f"PRICE IS NOT OK - xt_position: {xt_position} bn_position: {bn_position}")
                result = False
            else:
                logging.info(f"PRICE IS OK - xt_position: {xt_position} bn_position: {bn_position}")
                result = True

        self.hedging_data[0].update({"position": bn_position, "result": result})
        df = pd.DataFrame(self.hedging_data)
        df.to_csv("hedging_test.csv", mode='a', index=False, header=True)
    
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
            
    def run(self, xt_client, config):
        
        while True:
            time.sleep(config["Hedging_interval"])
            res = self.client.futures_change_leverage(symbol=config["bnsymbol"], leverage=config["leverage"])
            logging.info(res)
            
            xt_delta_position, xt_position, position_price, xt_amount = xt_client.get_position3(config["symbol"], config["currencies"])
            
            # check open orders
            open_value = self.check_open_orders()
                
            if xt_delta_position == 0 and self.remain_amount == 0 and open_value == 0:
                logging.info("xt_delta_position == 0 and self.remain_amount == 0 and open_value == 0")
                continue

            price = round(float(self.client.get_symbol_ticker(
                symbol=config["bnsymbol"]
            )['price']), config["precision_price"])
            
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
                "xt_position": xt_position,
                "xt_price": position_price,
                "xt_amount": xt_amount,
                }]        
            
            amount_orig = abs(amount_orig)
            amount = round_down(amount_orig, config["precision_amount"])

            self.hedging_data[0].update({
                "hedging_amount_round": amount,
                })
            
            logging.info(f"Hedging: {self.hedging_data}")
            
            if amount >= 0.001:            
                result = self.create_order(config["bnsymbol"], side, price, amount)
            else:
                logging.info("amount < 0.001, skip creat order")
                result = False
                
            # check whether successful and the entry price
            self.get_position(config, result, side, hedging_delta, xt_position, amount, amount_orig, price)            
           
