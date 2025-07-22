import logging
import math
from typing import List, Dict, Optional
import time
import numpy as np
import asyncio

from etf.risk.stop_loss import StopLossManager, StopLossAction
from etf.utils.common import get_mid_price, calculate_price_change_percentage

class RiskController:
    def __init__(self, client, risk_params, strategy_name: str = "unknown"):
        """
        Initializes the RiskController.
        :param exchange_api: Instance of the exchange API interface.
        :param risk_params: Configuration for risk parameters.
        
        Level 1: stop marker making and wash trading, cancel all orders
        Level 2: cancel near-end orders,  
        """
        self.client = client
        self.risk_params = risk_params
        self.risk_level = 3
        self.midprices = []
        self.depth = None
        self.strategy_name = strategy_name
        
        # 初始化止损管理器（如果配置中启用）
        self.stop_loss_manager: Optional[StopLossManager] = None
        if risk_params.get("stop_loss", {}).get("enabled", False):
            stop_loss_config = risk_params["stop_loss"]
            self.stop_loss_manager = StopLossManager(
                strategy_name=strategy_name,
                fixed_threshold=stop_loss_config.get("fixed_threshold", -0.02),
                trailing_stop=stop_loss_config.get("trailing_stop", 0.01),
                time_stop_hours=stop_loss_config.get("time_stop", 24),
                cooldown_minutes=stop_loss_config.get("cooldown", 60),
                enable_partial_close=stop_loss_config.get("enable_partial_close", True)
            )

    def get_mid_price_from_depth(self, depth) -> float:
        """Calculates the mid price from the order book."""
        return get_mid_price(depth)

    def get_market_price(self, symbol):
        '''ticker
        [{'s': 'btc5l_usdt', 't': 1736171102959, 'p': '0.8822'}]
        '''
        ticker = self.client.get_tickers(symbol)
        logging.info(f"ticker: {ticker}")
        
        market_price = ticker[0]['p']
        return float(market_price)
    
    def get_depth_data(self, symbol):
        depth = self.client.get_depth(symbol)
        logging.debug(f"depth {depth}")
        '''
        {'symbol': 'btc5l_usdt', 'timestamp': 1736170681790, 'lastUpdateId': 1736148981744, 'bids': [['0.8822', '0.8896'], ['0.8813', '10.0000'], ['0.7983', '2.0000'], ['0.7975', '11.0000'], ['0.7223', '3.0000'], ['0.7216', '12.0000'], ['0.6536', '3.0000'], ['0.6529', '13.0000'], ['0.5914', '6.0000'], ['0.5908', '12.0000'], ['0.5351', '4.0000'], ['0.5346', '16.0000'], ['0.4842', '44.0000'], ['0.4381', '4.0000'], ['0.4377', '20.0000'], ['0.3964', '5.0000'], ['0.3960', '22.0000'], ['0.3587', '60.0000'], ['0.3245', '6.0000'], ['0.3242', '27.0000'], ['0.2937', '74.0000'], ['0.2657', '80.0000'], ['0.2404', '9.0000'], ['0.2402', '36.0000'], ['0.2176', '49.0000'], ['0.1968', '108.0000'], ['0.1781', '120.0000'], ['0.1612', '134.0000'], ['0.1458', '28.0000'], ['0.1457', '46.0000'], ['0.1320', '81.0000'], ['0.1194', '180.0000'], ['0.1080', '198.0000'], ['0.0978', '220.0000'], ['0.0884', '242.0000'], ['0.0800', '268.0000'], ['0.0724', '296.0000'], ['0.0655', '328.0000'], ['0.0593', '543.0000'], ['0.0536', '600.0000'], ['0.0485', '221.0000']], 'asks': [['1.1328', '18.0000'], ['1.2519', '20.0000'], ['1.3836', '22.0000'], ['1.5291', '24.0000'], ['1.6899', '26.0000'], ['1.8677', '30.0000'], ['2.0641', '32.0000'], ['2.2812', '36.0000'], ['2.5211', '40.0000'], ['2.7862', '44.0000'], ['3.0792', '48.0000'], ['3.4031', '54.0000'], ['3.7610', '58.0000'], ['4.1566', '64.0000'], ['4.5937', '72.0000'], ['5.0768', '80.0000'], ['5.6108', '88.0000'], ['6.2008', '96.0000'], ['6.8530', '106.0000'], ['7.5737', '118.0000'], ['8.3703', '130.0000'], ['9.2506', '144.0000'], ['10.2235', '160.0000'], ['11.2987', '176.0000'], ['12.4870', '194.0000'], ['13.8002', '216.0000'], ['15.2516', '238.0000'], ['16.8557', '264.0000'], ['18.6284', '290.0000'], ['20.5875', '322.0000']]}
        '''
        self.depth = depth
        return depth
    
    def calculate_volatility(self, close_prices: List[float]) -> float:
        """
        Manually calculates rolling standard deviation (volatility).
        :param close_prices: List of close prices.
        :param window: Rolling window size.
        :return: Volatility (standard deviation).
        """
        #if len(close_prices) < window:
        #    return 0.0  # Not enough data to compute volatility

        # Compute percentage changes (returns)
        returns = [
            (close_prices[i] - close_prices[i - 1]) / close_prices[i - 1]
            for i in range(1, len(close_prices))
        ]

        # Take the last `window` returns
        windowed_returns = returns

        # Compute mean of the returns
        mean_return = sum(windowed_returns) / len(windowed_returns)

        # Compute variance
        variance = sum((r - mean_return) ** 2 for r in windowed_returns) / len(windowed_returns)

        # Return standard deviation (volatility)
        return math.sqrt(variance), mean_return

    def check_market_volatility(self, symbol: str) -> str:
        """
        Compares 2-minute and 24-hour volatility to determine the risk level.
        :param symbol: The trading pair (e.g., 'BTCUSDT').
        :return: The current risk level ('Normal', 'Level 1', 'Level 2', 'Level 3').
        """
        start_time = int(time.time() * 1000)
        # end_time_1m = int(time.time() * 1000) + 60
        data_1m = self.client.get_kline(symbol=symbol, interval="1m", start_time=start_time, end_time=int(start_time+60))
        data_24h = self.client.get_kline(symbol=symbol, interval="1d", start_time=start_time, end_time=int(start_time+60*60*24))

        # Extract close prices
        close_prices_1m = [float(kline["c"]) for kline in data_1m]  # 'close' is the 5th element
        close_prices_24h = [float(kline["c"]) for kline in data_24h]

        # Calculate volatilities
        vol_1m, mean_1m = self.calculate_volatility(close_prices_1m)
        vol_24h, mean_24h = self.calculate_volatility(close_prices_24h)

        # Compute delta (relative volatility)
        delta = vol_24h
        
        if not mean_24h - 1 * delta <= vol_1m <= mean_24h + 1 * delta:
            return 3
        elif not mean_24h - 2 * delta <= vol_1m <= mean_24h + 2 * delta:
            return 2
        elif not mean_24h - 3 * delta <= vol_1m <= mean_24h + 3 * delta:
            return 1
        else:
            return 3

    def monitor_order_book_depth(self, depth_data):
        """
        监测订单簿异常波动。
        
        参数：
            depth_data (list of dict): 每个挂单的数据，包括 'bid' 和 'ask' 的价格和数量。
            threshold (float): 挂单量减少的阈值比例（例如 0.2 表示减少 80% 即异常）。
            
        返回：
            str: 异常侧信息或正常状态。
        """
        # 计算买单（bid）和卖单（ask）的总挂单量
        bid_volume = sum([float(order[1]) for order in depth_data["bids"]])
        ask_volume = sum([float(order[1]) for order in depth_data["asks"]])

        # 检查挂单量是否异常减少
        thresholds = self.risk_params['orderbook_threshold']
        base_bid_volume = self.risk_params['base_bid_volume']
        base_ask_volume = self.risk_params['base_ask_volume']

        for level, threshold in enumerate(thresholds, start=1):
            if bid_volume < base_bid_volume * threshold or ask_volume < base_ask_volume * threshold:
                return 4 - level
        return 3
        
    def market_price_deviation(self, market_price, mid_price) -> List[Dict]:
        """
        Identifies risky orders based on price deviation.
        :param symbol: The trading pair (e.g., 'BTCUSDT').
        :return: A list of risky orders.
        """

        # 成交价格与midprice 偏离
        deviation = abs(market_price - mid_price) / mid_price
        if deviation > self.risk_params['price_deviation_threshold'][0]:
            return 3
        elif deviation > self.risk_params['price_deviation_threshold'][1]:
            return 2
        elif deviation > self.risk_params['price_deviation_threshold'][2]:
            return 1
        else:
            return 3
        
    def mid_price_deviation(self, mid_price):   
        # midprice 超出历史midprice 均值2个标准差
        self.midprices.append(mid_price)
        if len(self.midprices) > 60:
            self.midprices.pop()

        mean_price = np.mean(self.midprices)
        std_dev = np.std(self.midprices)
        
        if not mean_price - 1 * std_dev <= mid_price <= mean_price + 1 * std_dev:
            return 3
        elif not mean_price - 2 * std_dev <= mid_price <= mean_price + 2 * std_dev:
            return 2
        elif not mean_price - 3 * std_dev <= mid_price <= mean_price + 3 * std_dev:
            return 1
        else:
            return 3
    # @staticmethod
    def risk_monitor(self, symbol: str):
        """
        Monitors risk levels in real-time.
        :param symbol: The trading pair (e.g., 'BTCUSDT').
        :return: The current risk level.
        """
        depth_data = self.get_depth_data(symbol)
        mid_price = self.get_mid_price_from_depth(depth_data)
        market_price = self.get_market_price(symbol)
        # depth_data = self.get_depth_data(symbol)

        vol_level = self.check_market_volatility(symbol)
        market_price_level = self.market_price_deviation(market_price, mid_price)
        mid_price_level = self.mid_price_deviation(mid_price)
        amount_level = self.monitor_order_book_depth(depth_data)
        logging.info(f"vol_level:{vol_level},mid_price_level:{mid_price_level},market_price_level:{market_price_level}, amount_level:{amount_level}") 
        level = vol_level * 0.4 + mid_price_level * 0.3 + market_price_level * 0.2 + amount_level * 0.1
        
        if level < 1.5:
            self.risk_level = 1
        elif level < 2.5:
            self.risk_level = 2
        else:
            self.risk_level = 3
            
    def update_position_for_stop_loss(
        self,
        symbol: str,
        side: str,
        amount: float,
        entry_price: float,
        current_price: float
    ):
        """更新止损管理器的持仓信息"""
        if self.stop_loss_manager:
            self.stop_loss_manager.update_position(
                symbol=symbol,
                side=side,
                amount=amount,
                entry_price=entry_price,
                current_price=current_price
            )
            
    async def check_stop_loss(self, symbol: str) -> Optional[Dict]:
        """
        检查止损条件
        
        Returns:
            如果触发止损，返回止损结果；否则返回 None
        """
        if not self.stop_loss_manager:
            return None
            
        result = await self.stop_loss_manager.check_stop_loss(symbol)
        
        if result.triggered:
            return {
                "action": result.action,
                "reason": result.reason,
                "loss_rate": result.loss_rate,
                "position_to_close": result.position_to_close
            }
            
        return None
        
    def is_stop_loss_active(self) -> bool:
        """检查止损是否处于活动状态（非冷却期）"""
        if not self.stop_loss_manager:
            return True  # 没有止损管理器，不影响交易
            
        return not self.stop_loss_manager.is_in_cooldown
        
    def get_stop_loss_summary(self) -> Optional[Dict]:
        """获取止损汇总信息"""
        if not self.stop_loss_manager:
            return None
            
        return self.stop_loss_manager.get_stop_loss_summary()
