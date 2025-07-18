import json
import logging
import time

from etf.xt import Spot
from etf.order_manager import OrderManager

from binance import Client

logging.shutdown()
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s',
)
                
if __name__ == "__main__":
    
    config = {
        "env": "prod",
        "symbol": "stg5l_usdt",
        "bnsymbol": "STGUSDT",
        "currencies": ["USDT","STG5L"],
    }
    
    if config["env"] == "qa":
        spot = Spot(host="https://sapi.xt-qa.com", access_key="be3466e5-365c-4471-a368-7c425fd5dd61",
                secret_key="9ca42e6db6c35f0ca5f3541737b044c4e3d5abb2")
    
    elif config["env"] == "prod":
        with open('APIKey.json', 'r', encoding='utf8') as input:
            apikey = json.load(input)
            spot = Spot(host="https://sapi.xt.com", access_key=apikey["xt"]["access_key"],
                secret_key=apikey["xt"]["secret_key"])

    # intennal
    init_usdt = 10000
    init_symbol = 10000
    init_price = 1.0
    init_position = init_usdt + init_symbol * init_price
    bn_init_position = 2000

    order_manager = OrderManager(spot)
    bn_client = Client(apikey["bn"]["access_key"], apikey["bn"]["secret_key"])

    while True:
        time.sleep(1)
        try:
            info = order_manager.client.balances(config["currencies"])
            logging.info(info)
        except Exception as e:
            logging.error(e)
            logging.info("try again order_manager.client.balances(config['currencies'])")
            continue
        
        current_position = float(info["totalUsdtAmount"])

        logging.info(f"internal pnl: {current_position - init_position}")

        # external
        try:
            info = bn_client.futures_account_balance()
            logging.info(info)
        except Exception as e:
            logging.error(e)
            logging.info("try again bn_client.futures_account_balance()")
            continue
        logging.info(f"external pnl: {bn_init_position}")
