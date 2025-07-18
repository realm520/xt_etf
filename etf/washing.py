import time
import random
import logging
import numpy as np
import redis

class WashController:
    def __init__(self, order_manager, market_maker):
        self.order_manager = order_manager
        self.market_maker = market_maker
        self.returns = []
        
        self.max_trade_amount = 50
        self.total_spent = 0
        self.r = redis.Redis(host='localhost', port=6379, db=0) 

    def wash(self, symbol, last_mid_price, mid_price, prec=4, prec_amount=2, interval=60):
        
        self.returns.append((mid_price - last_mid_price) / last_mid_price)
        tick = float(f"1e-{prec}")
        
        # 1min k-line
        if len(self.returns) > interval:
            new_mid_price = last_mid_price + random.randint(1, 2) * tick
            logging.info(f"[{time.strftime('%H:%M:%S')}] last {interval / 60} min closing price {last_mid_price}, closing prices from {mid_price} to {new_mid_price}")
            mid_price = new_mid_price
            self.returns = [(mid_price - last_mid_price) / last_mid_price]

        price_change = mid_price - last_mid_price
        amount = np.random.randint(1, self.max_trade_amount) if price_change > 0 else np.random.randint(1, self.max_trade_amount // 3)
        
        
        
        volatility = self.returns[-1]
        if volatility > 0.01:
            logging.info(f"volatility {volatility} too high, skipping order")
            return mid_price
        
        
        # min value 5 USDT
        if mid_price * amount < 5:
            amount = 5 / mid_price

        amount = round(amount + random.uniform(0, 1), prec_amount)     
        logging.info(f"price change {price_change}, by tick {price_change / tick}")
        logging.info(f"sending orders with amount {amount}, volatility {volatility}, and price {mid_price}")
 
        last_mid_price = mid_price
    
        rd = random.randint(0,1)
        try:    
            buy_data = [{
                "symbol": symbol,
                "clientOrderId": "16559590087220001",
                "side": "BUY" if rd == 0 else "SELL",
                "type": "LIMIT",
                "timeInForce": "GTC", 
                "bizType": "SPOT",
                "price": round(mid_price, prec),
                "quantity": amount,
                "quoteQty": None
            }]
            res1 = self.order_manager.add_orders_batch(buy_data, batch_id=51232, is_wash_trading=True)
            logging.info(res1)
            sell_data = [{
                "symbol": symbol,
                "clientOrderId": "16559590087220001",
                "side": "SELL" if rd == 0 else "BUY",
                "type": "LIMIT",
                "timeInForce": "GTC", 
                "bizType": "SPOT",
                "price": round(mid_price, prec),
                "quantity": amount,
                "quoteQty": None
            }]
            res2 = self.order_manager.add_orders_batch(sell_data, batch_id=51232, is_wash_trading=True)
            logging.info(res2)

        except Exception as e:
            logging.info(e)

        return last_mid_price 
    
    def get_washing_price(self, config):

        if self.market_maker.best_sell == 0:
            mid_price = float(self.r.get(config["netvalue"]).decode())
            bid_ask_spread = 0.05
        
            best_sell = mid_price - ( (mid_price * bid_ask_spread)/2 )
            best_buy = mid_price + ( (mid_price * bid_ask_spread)/2 )
        else:
            best_sell = self.market_maker.best_sell
            best_buy = self.market_maker.best_buy
        
        # washing price with respect to best_sell or mid_price
        if config["wash"] == "best_sell":
            washing_price = float(best_sell) - float(f"1e-{config['precision']}") * random.randint(5, 10)
        elif config["wash"] == "mid_price":
            washing_price = (float(best_sell) + float(best_buy)) / 2
        
        return washing_price
    
    def run(self, risk_controller, config):

        time.sleep(random.randint(1, 5))
        
        # For initialization
        last_mid_price = self.get_washing_price(config)
 
        while True:
            time.sleep(random.randint(5, 10))
            
            # For each washing trade
            mid_price = self.get_washing_price(config)

            last_mid_price = self.wash(
                config["symbol"],
                last_mid_price,
                mid_price,
                config["precision"],
                config["prec_amount"],
                config["kline_continuity_interval"])
