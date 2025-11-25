import logging
import time

from etf.xt import Spot
from etf.order_manager import OrderManager
from etf.config import load_api_keys, load_binance_api_keys

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
    
    # 使用统一配置加载 API 密钥
    try:
        xt_keys = load_api_keys(env=config["env"])
        bn_keys = load_binance_api_keys()
    except ValueError as e:
        logging.error(f"加载 API 密钥失败: {e}")
        exit(1)
    
    # 根据环境选择主机
    if config["env"] == "qa":
        host = "https://sapi.xt-qa2.com"
    else:
        host = "https://sapi.xt.com"
    
    spot = Spot(
        host=host,
        access_key=xt_keys["access_key"],
        secret_key=xt_keys["secret_key"]
    )

    # internal
    init_usdt = 10000
    init_symbol = 10000
    init_price = 1.0
    init_position = init_usdt + init_symbol * init_price
    bn_init_position = 2000

    order_manager = OrderManager(spot)
    bn_client = Client(bn_keys["access_key"], bn_keys["secret_key"])

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
