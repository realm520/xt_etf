from binance import Client
# from pyxt import Spot
api_key = 'lDHuIavZpEErNyC27HGnJSMOb0ArGR0lBBNJGEWU56NnxjxUwljgnBn97RFScuZN'
api_secret = 'zlo0LVMVqNTDJRCby7QZMYuPRSY8QMLOokK6UnmqtUZ5YDP9GIqsvqCnXh7bAPSV'
import time
# from copy import deepcopy
import logging
logging.shutdown()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
)
class BinanceClient():
    def __init__(self):
        # self.last_position = None
        self.init_position = None
        self.position = None
        self.sent_order = False
        self.orders = []

class Hedge():
    def __init__(self):
        self.client = Client(api_key, api_secret)
        self.init_position = None
        self.position = None
        self.sent_order = False
        
        # orders
        self.open_orders = {}
        self.pending_orders = []
    
    def create_order(self, symbol, side, amount, price):
        res = self.client.futures_create_order(
            symbol=symbol,
            side=side,
            type="MARKET",
            #price=price,
            quantity=amount,
            #timeInForce="GTC"
        )
        logging.info(res)
        order_id = 0
        return order_id
    
    def open_order(self, symbol, side, amount, price):
        order_id = self.create_order(symbol, side, amount, price)
        self.open_orders[order_id] = {
            "symbol": symbol,
            "side": side,
            "type": "MARKET",
            # "price": price,
            "quantity": amount,
        }
        
    def close_order(self, symbol, side, amount, price):
        order_id = self.create_order(symbol, side, amount, price)
        
        # del self.open_orders[order_id]
        
    def run(self, position, config):
        
        res = self.client.futures_change_leverage(symbol=config["symbol"], leverage=config["leverage"])
        logging.info(res)
        #res = self.client.futures_change_position_mode(dualSidePosition=False)
        #logging.info(res)

        if position != 0:
            side = "BUY" if position < 0 else "SELL"

            price = self.client.get_symbol_ticker(
                symbol=config["symbol"]
            )['price']
            logging.info(price)
            price = float(price)
            amount = round(abs(position) / price * config["leverage"], config["precision_amount"])
            #amount = position / price
            position = 7.48
            amount = round(position / price, 0)
            #amount=297
            side = "BUY"
            logging.info(f"Hedging: {config['symbol']}, {side}, {amount} {position / price} {position}u")
            self.close_order(config["symbol"], side, amount, price)
            #self.client.futures_cancel_order(symbol=config["symbol"], orderId=561397318668)
            #info = self.client.futures_account_balance()
            #for item in info:
            #    if item["asset"] == config["symbol"]:
            #        logging.info(info)
            
            '''
            list: [{'accountAlias': 'fWoCfWmYXqSgFzSg', 'asset': 'BTC', 'balance': '0.00000000', 'crossWalletBalance': '0.00000000', 'crossUnPnl': '0.00000000', 'availableBalance': '0.00000000', 'maxWithdrawAmount': '0.00000000', 'marginAvailable': True, 'updateTime': 0}]
            '''
            
            # res = client.get_account()
            # print(res)
                
if __name__ == "__main__":
    config = {
        "leverage": 5, 
        "symbol": "STGUSDT",
        "precision_amount": 3,
        "precision_price": 1
    }
    

    hedging = Hedge()
    position = 1
    info = hedging.client.get_exchange_info()
    for i in info["rateLimits"]:
        logging.info(i)
    #hedging.run(position, config)
    info = hedging.client.get_account()
    #logging.info(info)
    for asset in info["balances"]:
        if asset["asset"] == "USDT":
            logging.info(asset)
    info = hedging.client.futures_get_all_orders()
    #logging.info(info)
    info = hedging.client.futures_position_information()
    logging.info(info)

    info = hedging.client.futures_account()
    #logging.info(info)
    
    for item in info["assets"]:
        if item["asset"] == "USDT":
            logging.info(item)
        if item["asset"] == "STGUSDT":
            logging.info(item)
    #info = hedging.client.futures_cancel_order(symbol=config["symbol"], orderId=int(576540428374))    
    #logging.info(info)
    #info = hedging.client.make_universal_transfer(type="MAIN_UMFUTURE", asset="USDT", amount=2000)
    #https://developers.binance.com/docs/wallet/asset/user-universal-transfer
    #info = hedging.client.futures_get_all_orders()
    
    #logging.info(info)
    #price = hedging.client.get_symbol_ticker(                                                                                      symbol=config["symbol"]                                                                                             )['price']
    #logging.info(price)
