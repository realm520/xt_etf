from etf.risk import RiskController
from etf.washing import WashController
from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.xt import Spot
from net_value import NetValue
from hedging import Hedge
import json
import time
import logging
import threading
import atexit
import pandas as pd
import argparse

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
    def run(config, risk_controller, wash_controller, market_maker, depth=None):
        
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
                #market_maker.make_orders(config["symbol"])
        else:
            logging.info("skip cancel_all_open_orders")

        
        if config["pre_make_orders"]:
            logging.info("pre_make_orders")
            if len(depth["asks"]) == 0 or len(depth["bids"]) == 0:
                market_maker.make_orders()
        else:
            logging.info("skip pre_make_orders")
  
        # try:
            
        while True:

            time.sleep(1)
            
            market_maker.place_orders(
                config,
                symbol=config["symbol"], 
                env=config["env"], 
                currencies=config["currencies"], 
                prec=config["precision"])

            market_maker.order_manager.reset_open_orders(config["symbol"])
                
        # except Exception as e:
        #     if not config["Exit_with_cancel_all_open_orders"]:
        #         logging.info(e)
        #         return 
        #     else:
        #         try:
        #             order_manager.cancel_all_open_orders(config["symbol"])
        #         except Exception as e:
        #             return 
                

if __name__ == "__main__":
    
    prefix = "stg5l"
    config = {
        "env": "prod", # "qa"
        "clientOrderId": "1655",
        "symbol": prefix + "_usdt",
        "apikey": "APIKey.json",
        "netvalue": "netvalue_" + prefix,
        "bnsymbol": "STGUSDT",
        "currencies": ["USDT","STG5L", "STG5S", "STG3L", "STG3S"],
        "precision": 6,
        "prec_amount": 2,
        "Hedging_interval": 20, # seconds
        "washing_interval": 1, # seconds
        "kline_continuity_interval": 60, # seconds
        "Enable_risk_controller": False,
        "Enable_wash_trading": True,
        "cancel_all_open_orders": True,
        "pre_make_orders": False,
        "leverage": 5,
        "precision_amount": 0,
        "precision_price": 4,
        "Enable_hedging": False,
        "Exit_with_cancel_all_open_orders": False,
        "wash": "mid_price",
        "anti_pin_usdt": 300,
        "anti_pin_rate": 0.2,
        "Enable_market_making": True,
        "bid_ask_spread": 0.01
        }

    if config["env"] == "qa":
        spot = Spot(host="https://sapi.xt-qa.com", access_key="be3466e5-365c-4471-a368-7c425fd5dd61",
                secret_key="9ca42e6db6c35f0ca5f3541737b044c4e3d5abb2")
    
    elif config["env"] == "prod":
        with open(config["apikey"], 'r', encoding='utf8') as input:
            apikey = json.load(input)
            spot = Spot(host="https://sapi.xt.com", access_key=apikey["xt_" + prefix]["access_key"],
                secret_key=apikey["xt_" + prefix]["secret_key"])

    # risk related
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

    # market maker related 
    order_manager = OrderManager(spot)
    
    info = order_manager.client.balances(config["currencies"])
    logging.info(info)
    last_amount = [float(currency["totalAmount"]) for currency in info["assets"] if currency["currency"] == config["symbol"].split("_")[0].lower()][0]
    order_manager.init_amount = last_amount
    order_manager.last_amount = last_amount
    print(f"init market making {config['symbol']} amount {order_manager.last_amount}")
    if order_manager.risk_actions(risk_controller.risk_level):

        market_maker = MarketMaker(order_manager)
        wash_controller = WashController(order_manager, market_maker)

        depth = risk_controller.get_depth_data(config["symbol"])
        logging.info(depth)
        
        #market_maker.make_orders(symbol=config["symbol"])
        hedging = Hedge()
        
    # thread2 = threading.Thread(target=EtfStrategy.run, args=(config, risk_controller, wash_controller, market_maker))
    if config["Enable_hedging"]:
        thread3 = threading.Thread(target=hedging.run, args=(order_manager, config), daemon=True)
    if config["Enable_wash_trading"]:
        thread4 = threading.Thread(target=wash_controller.run, args=(risk_controller, config), daemon=True)

    # thread2.start()
    if config["Enable_hedging"]:
        thread3.start()
    if config["Enable_wash_trading"]:
        thread4.start()
    
    # thread2.join()
    # if config["Enable_hedging"]:
    #     thread3.join()
    # if config["Enable_wash_trading"]:
    #     thread4.join()
    if config["Enable_market_making"]:
        EtfStrategy.run(config, risk_controller, wash_controller, market_maker)
