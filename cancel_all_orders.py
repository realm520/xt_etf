import json
from etf.xt import Spot
from etf.order_manager import OrderManager


if __name__ == "__main__":
    
    config = { 
        'prefixs': ["stg5s"],
        "apikey": "APIKey.json",
    }

    with open(config["apikey"], 'r', encoding='utf8') as input:
        apikey = json.load(input)

    for prefix in config["prefixs"]:
        
        spot = Spot(host="https://sapi.xt.com", access_key=apikey["xt_" + prefix]["access_key"],
            secret_key=apikey["xt_" + prefix]["secret_key"])

        order_manager = OrderManager(spot)
        # order_manager.cancel_all_open_orders(prefix + "_usdt") 
        order_data = {
            "symbol": "stt5l_usdt",
            "clientOrderId": order_manager.create_temp_id(),
            "side": "SELL",
            "type": "LIMIT",
            "timeInForce": "GTC",
            "bizType": "SPOT",
            "price": 1,
            "quantity": 10,
            "quoteQty": None
        }
        response = order_manager.add_orders_batch([order_data], batch_id=51232, is_wash_trading=False)