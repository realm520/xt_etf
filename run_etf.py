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
            order_manager.cancel_all_open_orders(config["symbol"]) 
            if len(depth["asks"]) != 0 or len(depth["bids"]) != 0:
                try:
                    order_manager.cancel_all_open_orders(config["symbol"])
                    time.sleep(10)
                except Exception as e:
                    pass
                columns = ['price','quantity','orderId','time','UTC_PLUS_8','symbol','side','state']
                df = pd.DataFrame(columns=columns)
                df.to_csv(market_maker.order_manager.open_orders_csv_file, mode='w', index=False, header=True)
                
                logging.info("finish cancel_all_open_orders")
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
        formatter_class=argparse.ArgumentDefaultsHelpFormatter
    )

    parser.add_argument("--prefix", type=str, default="stg5s", help="Prefix for the symbol (e.g., 'stg5s').")
    parser.add_argument("--env", type=str, default="prod", choices=["qa", "prod"], help="Environment.")
    parser.add_argument("--client-order-id", type=str, default="1655", help="Client order ID.")
    parser.add_argument("--apikey", type=str, default="APIKey.json", help="Path to API key file.")
    parser.add_argument("--enable-risk-controller", type=str2bool, default=False, help="Enable risk controller.")
    parser.add_argument("--enable-wash-trading", type=str2bool, default=True, help="Enable wash trading.")
    parser.add_argument("--enable-hedging", type=str2bool, default=False, help="Enable hedging.")
    parser.add_argument("--enable-market-making", type=str2bool, default=True, help="Enable market making.")
    parser.add_argument("--cancel-all-open-orders", type=str2bool, default=False, help="Cancel all open orders on start.")
    parser.add_argument("--exit-with-cancel-all-open-orders", type=str2bool, default=True, help="Cancel all open orders before exit.")
    parser.add_argument("--pre-make-orders", type=str2bool, default=False, help="Make pre-orders before market making.")
    parser.add_argument("--hedging-interval", type=int, default=20, help="Hedging interval in seconds.")
    parser.add_argument("--washing-interval", type=int, default=1, help="Washing interval in seconds.")
    parser.add_argument("--kline-continuity-interval", type=int, default=60, help="Kline continuity check interval in seconds.")
    parser.add_argument("--precision", type=int, default=6, help="Precision for price.")
    parser.add_argument("--prec-amount", type=int, default=2, help="Precision for amount.")
    parser.add_argument("--precision-amount", type=int, default=0, help="Override precision for amount.")
    parser.add_argument("--precision-price", type=int, default=4, help="Override precision for price.")
    parser.add_argument("--leverage", type=int, default=5, help="Leverage for the position.")
    parser.add_argument("--wash", type=str, default="mid_price", help="Wash trading reference price.")
    parser.add_argument("--anti-pin-usdt", type=float, default=300, help="USDT threshold for anti-pin mechanism.")
    parser.add_argument("--anti-pin-rate", type=float, default=0.2, help="Rate for anti-pin mechanism.")
    parser.add_argument("--bid-ask-spread", type=float, default=0.05, help="Bid-ask spread for market making.")

    return parser

if __name__ == "__main__":
    
    parser = get_parser()
    args = parser.parse_args()

    prefix = args.prefix
    config = {
        "env": args.env,
        "clientOrderId": args.client_order_id,
        "symbol": args.prefix + "_usdt",
        "apikey": args.apikey,
        "netvalue": "netvalue_" + args.prefix,
        "bnsymbol": args.prefix.upper()[:-2] + "USDT",
        "precision": args.precision,
        "prec_amount": args.prec_amount,
        "Hedging_interval": args.hedging_interval,
        "washing_interval": args.washing_interval,
        "kline_continuity_interval": args.kline_continuity_interval,
        "Enable_risk_controller": args.enable_risk_controller,
        "Enable_wash_trading": args.enable_wash_trading,
        "cancel_all_open_orders": args.cancel_all_open_orders,
        "pre_make_orders": args.pre_make_orders,
        "leverage": args.leverage,
        "precision_amount": args.precision_amount,
        "precision_price": args.precision_price,
        "Enable_hedging": args.enable_hedging,
        "Exit_with_cancel_all_open_orders": args.exit_with_cancel_all_open_orders,
        "wash": args.wash,
        "anti_pin_usdt": args.anti_pin_usdt,
        "anti_pin_rate": args.anti_pin_rate,
        "Enable_market_making": args.enable_market_making,
        "bid_ask_spread": args.bid_ask_spread,
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
    
    # info = order_manager.client.balances(config["currencies"])
    # logging.info(info)
    # last_amount = [float(currency["totalAmount"]) for currency in info["assets"] if currency["currency"] == config["symbol"].split("_")[0].lower()][0]
    # order_manager.init_amount = last_amount
    # order_manager.last_amount = last_amount
    # print(f"init market making {config['symbol']} amount {order_manager.last_amount}")
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
