from etf.risk import RiskController
from etf.washing import WashController
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.xt import Spot
from net_value import NetValue
from hedging import Hedge

import time
import logging
import threading
import atexit
import pandas as pd

logging.shutdown()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
)


class EtfStrategy():
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
            pass # using history depth
        
        if config["cancel_all_open_orders"]:
            logging.info("cancel_all_open_orders")
            if len(depth["asks"]) != 0 or len(depth["bids"]) != 0:
                try:
                    order_manager.cancel_all_open_orders(config["symbol"])
                    time.sleep(10)
                except Exception as e:
                    pass
                columns = ['price','quantity','orderId','time','UTC_PLUS_8','symbol','side','state']
                df = pd.DataFrame(columns=columns)
                df.to_csv(market_maker.order_manager.open_orders_csv_file, mode='w', index=False, header=True)
                market_maker.make_orders(config["symbol"])
        else:
            logging.info("skip cancel_all_open_orders")

        
        if config["pre_make_orders"]:
            logging.info("pre_make_orders")
            if len(depth["asks"]) == 0 or len(depth["bids"]) == 0:
                market_maker.make_orders()
        else:
            logging.info("skip pre_make_orders")
        '''
        last_mid_price = risk_controller.get_mid_price(depth)
        last_amount = int(float(depth["bids"][0][1]) + float(depth["asks"][0][1]) / 2)
        # logging.info(f"Initial amount {last_amount} and price {last_mid_price}")
        '''
        try:
            
            while True:

                time.sleep(1)
                '''
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
                '''
                market_maker.place_orders(
                    nv=nv, 
                    symbol=config["symbol"], 
                    env=config["env"], 
                    currencies=config["currencies"], 
                    prec=config["precision"])
                
                # logging.info("replace")
                # after reset open orders, self.open_orders should NOT contain
                # canceled orders
                market_maker.order_manager.reset_open_orders(config["symbol"])
                
                #logging.info("writing orders")
                # market_maker.order_manager.write_history_orders()
                #market_maker.order_manager.write_trading_history()
                #atexit.register(market_maker.order_manager.write_orders)
                #atexit.register(market_maker.order_manager.write_trading_history)
                #logging.info("run etf computing postion")
                #market_maker.order_manager.get_position(config["symbol"])
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
    
    #spot = Spot(host="https://sapi.xt-qa.com", access_key="be3466e5-365c-4471-a368-7c425fd5dd61",
    #            secret_key="9ca42e6db6c35f0ca5f3541737b044c4e3d5abb2")
    #spot = Spot(host="https://sapi.xt.com", access_key="73d0d378-a7cd-4af9-9f96-3421a3049581",
    #        secret_key="0b4825b80f34595669f2e03beb20225fd702f270")
    
    config = {
        #"env": "qa",
        "env": "prod",
        "clientOrderId": "1655",
        "symbol": "stg5l_usdt",
        #"symbol": "btc5l_usdt",
        #"bnsymbol": "BTCUSDT",
        "bnsymbol": "STGUSDT",
        "currencies": ["btc5l"],
        "precision": 6,
        "Hedging_interval": 20, # seconds
        "washing_interval": 1, # seconds
        "kline_continuity_interval": 60, # seconds
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": False,
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 4,
        "precision_price": 4,
        "Enable_hedging": True,
        "Exit_with_cancel_all_open_orders": True
    }
    if config["env"] == "qa":
        spot = Spot(host="https://sapi.xt-qa.com", access_key="be3466e5-365c-4471-a368-7c425fd5dd61",
                secret_key="9ca42e6db6c35f0ca5f3541737b044c4e3d5abb2")
    elif config["env"] == "prod":
        spot = Spot(host="https://sapi.xt.com", access_key="73d0d378-a7cd-4af9-9f96-3421a3049581",
            secret_key="0b4825b80f34595669f2e03beb20225fd702f270")

    #logging.info("run netvalue")
    #nv = NetValue(symbol=config["symbol"], m_lever=3)

    # risk related
    '''
    risk_params = {
        "volatility_levels": 1,
        "price_deviation_threshold": [0.02, 0.05, 0.1],
        "base_ask_volume": 50,
        "base_bid_volume": 50,
        "orderbook_threshold": [0.8, 0.5, 0.2]
    }
    logging.info("run RiskController")
    risk_controller = RiskController(spot, risk_params)
    if config["Enable_risk_controller"]:
        risk_controller.risk_monitor(symbol=config["symbol"])
    '''
    # market maker related 
    order_manager = OrderManager(spot)
    
    #res = order_manager.client.get_open_orders(symbol="btc5l_usdt")
    #logging.info(res)
    #logging.info(res)
    #orderids = [order["orderId"] for order in res]
    #for order in res:
    #    logging.info(order)
    #res = order_manager.client.cancel_orders(orderids)
    #logging.info(res)
    info = order_manager.client.balances(["USDT","STG5L","BTC5L"])
    logging.info(info)
    '''
    {'totalUsdtAmount': '19341.6281', 'totalBtcAmount': '0.22708371', 'assets': [{'currency': 'stg5l', 'currencyId': 4135, 'frozenAmount': '8681.39000000', 'freeze': '0.00000000', 'lock': '0.00000000', 'copyTrade': '0.00000000', 'trade': '8681.39000000', 'withdraw': '0.00000000', 'availableAmount': '1237.44000000', 'totalAmount': '9918.83000000', 'convertBtcAmount': '0.10949282', 'convertUsdtAmount': '9325.94185558'}, {'currency': 'usdt', 'currencyId': 11, 'frozenAmount': '5290.44588993', 'freeze': '0.00000000', 'lock': '0.00000000', 'copyTrade': '0.00000000', 'trade': '5290.44588993', 'withdraw': '0.00000000', 'availableAmount': '4725.24006132', 'totalAmount': '10015.68595125', 'convertBtcAmount': '0.11759088', 'convertUsdtAmount': '10015.68595125'}, {'currency': 'btc5l', 'currencyId': 3535, 'frozenAmount': '0.00000000', 'freeze': '0.00000000', 'lock': '0.00000000', 'copyTrade': '0.00000000', 'trade': '0.00000000', 'withdraw': '0.00000000', 'availableAmount': '0.00184000', 'totalAmount': '0.00184000', 'convertBtcAmount': '0', 'convertUsdtAmount': '0.00029864'}]}

    '''
    from binance import Client        
    #from pyxt import Spot      
    api_key = 'lDHuIavZpEErNyC27HGnJSMOb0ArGR0lBBNJGEWU56NnxjxUwljgnBn97RFScuZN'       
    api_secret = 'zlo0LVMVqNTDJRCby7QZMYuPRSY8QMLOokK6UnmqtUZ5YDP9GIqsvqCnXh7bAPSV'
    bnclient = Client(api_key, api_secret)
    import time
    while True:
        mid_price = float(open('net_value', 'r', encoding='utf8').read().strip())

        info = order_manager.client.balances(["USDT","STG5L","BTC5L"])
        #logging.info(info)
        for asset in info['assets']:
            if asset["currency"] == "usdt":
                xt_usdt_remain = round(float(asset["convertUsdtAmount"]), 2)
            if asset["currency"] == "stg5l":
                xt_coin_remain = round(10000 - float(asset["totalAmount"]), 2)
                xt_coin_remain = -1 * xt_coin_remain if float(asset["totalAmount"]) < 10000 else xt_coin_remain
                xt_coin_remain_convertusdt = round(xt_coin_remain * mid_price, 2)
        
        xt_average_price = round((xt_usdt_remain - 10000) / xt_coin_remain, 6)
        #info = bnclient.futures_account_balance()
        info = bnclient.futures_position_information()
        for asset in info:
            if asset["symbol"] == "STGUSDT":
                bn_coin_remain = float(asset["positionAmt"]) 
                #bn_coin_remain = -1 * bn_coin_remain if float(asset["positionAmt"]) < 10000 else bn_coin_remain
                bn_entry_price = float(asset["entryPrice"])
                bn_cost_usdt = round(bn_coin_remain * bn_entry_price, 2)
                bn_unRealizedProfit = float(asset["unRealizedProfit"])
        info = bnclient.futures_account()
        for asset in info["assets"]:
            if asset["asset"] == "USDT":
                bn_usdt_remain = round(float(asset["marginBalance"]), 2) 
        logging.info(f"xt_usdt_remain {xt_usdt_remain} xt_coin_remain {xt_coin_remain} xt_coin_remain_convertusdt {xt_coin_remain_convertusdt} xt_mid_price {mid_price} xt_average_price {xt_average_price} bn_coin_remain {bn_coin_remain} bn_entry_price {bn_entry_price} bn_cost_usdt {bn_cost_usdt} bn_unRealizedProfit {bn_unRealizedProfit} bn_usdt_remain {bn_usdt_remain}")
        time.sleep(5)
    
    #logging.info()
    import time
    from datetime import datetime

    # 获取今天的日期
    now = datetime.now()
    today_10am = datetime(now.year, now.month, now.day, 10, 0, 0)  # 10:00:00

    # 转换为时间戳
    timestamp_10am = time.mktime(today_10am.timetuple())
    logging.info(timestamp_10am)
    res = order_manager.client.get_history_orders(symbol=config["symbol"], limit=100, start_time=timestamp_10am)
    logging.info(len(res["items"]))
    #logging.info(res)
    #res = order_manager.client.get_account()
    #logging.info(res)
    #logging.info(res)
    # 1. get depth correct?
    # 2. 
    # 
    #for order in res:
    for order in res["items"]:
        logging.info(order["state"])
        
        #assert order["state"] == "CANCELED"
        if order["state"] != "CANCELED":
        #if float(order["price"]) > 1 and order["side"] == "BUY":
            logging.info(order)
        #if order["side"] == "BUY":

        #    logging.info(order)
    
    #info = order_manager.client.order("btc5l_usdt", side="SELL", type="MARKET", time_in_force="IOC", quantity=14036.90)
    #logging.info(info) 
    #info = order_manager.client.balances(["USDT","STG5L","BTC5L"])
    #logging.info(info)
    '''
    info = order_manager.client.balances(["USDT"])
    logging.info(info)
    
    #info = order_manager.client.order(config["symbol"], side="SELL", type="LIMIT", price=1.5, quantity=50)
    #logging.info(info)
    
        
    data = [
    {
      "symbol": "stg5l_usdt",
      "clientOrderId": "16559590087220001",
      "side": "BUY",
      "type": "LIMIT",
      "timeInForce": "GTC",
      "bizType": "SPOT",
      "price": 1.5,
      "quantity": 10,
      "quoteQty": None
    }
    ]*2
    res = order_manager.client.batch_order(data, batch_id=51232)
    logging.info(res) 
    
    #res = self.order_manager.add_orders_batch(orders[0], batch_id=51232)
    if order_manager.risk_actions(risk_controller.risk_level):
        wash_controller = WashController(order_manager)
        market_maker = MarketMaker(order_manager)
        #risk_controller.
        depth = risk_controller.get_depth_data(config["symbol"])
        logging.info(depth)
        
        market_maker.make_orders(symbol=config["symbol"])
        hedging = Hedge()
        
    thread1 = threading.Thread(target=nv.run, daemon=True)
    thread2 = threading.Thread(target=EtfStrategy.run, args=(config, risk_controller, wash_controller, market_maker, nv))
    if config["Enable_hedging"]:
        thread3 = threading.Thread(target=hedging.run, args=(order_manager, config), daemon=True)
    if config["Enable_wash_trading"]:
        thread4 = threading.Thread(target=wash_controller.run, args=(risk_controller, config), daemon=True)

    thread1.start()
    thread2.start()
    if config["Enable_hedging"]:
        thread3.start()
    if config["Enable_wash_trading"]:
        thread4.start()
    
    thread1.join()
    thread2.join()
    if config["Enable_hedging"]:
        thread3.join()
    if config["Enable_wash_trading"]:
        thread4.join()
    
    #EtfStrategy.run(config, risk_controller, wash_controller, market_maker, nv)
    '''
