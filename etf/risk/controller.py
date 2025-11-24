import logging
import math
from typing import List, Dict, Optional
import time
import numpy as np
import asyncio

from etf.risk.stop_loss import StopLossManager, StopLossAction
from etf.utils.common import get_mid_price, calculate_price_change_percentage
from etf.websocket import XTWebSocketClient

class RiskController:
    def __init__(self, client, risk_params, strategy_name: str = "unknown", ws_client: Optional[XTWebSocketClient] = None):
        """
        Initializes the RiskController.
        :param exchange_api: Instance of the exchange API interface.
        :param risk_params: Configuration for risk parameters.
        :param ws_client: Optional WebSocket client for real-time depth data

        Level 1: stop marker making and wash trading, cancel all orders
        Level 2: cancel near-end orders,
        """
        self.client = client
        self.risk_params = risk_params
        self.risk_level = 3
        self.midprices = []
        self.depth = None
        self.strategy_name = strategy_name

        # WebSocket客户端（用于实时depth数据）
        self.ws_client = ws_client
        self.use_websocket = ws_client is not None
        
        # 深度数据缓存（用于空订单簿降级）
        self._last_valid_depth = None
        self._last_valid_time = 0

        if self.use_websocket:
            logging.info(f"RiskController将使用WebSocket获取depth数据")
        else:
            logging.info(f"RiskController将使用REST API获取depth数据")

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
        """
        获取市场价格，带完整的错误处理和 fallback 机制

        Returns:
            float: 市场价格，失败时返回 None
        """
        try:
            ticker = self.client.get_tickers(symbol)
            logging.info(f"ticker: {ticker}")

            # 检查返回结果是否有效
            if not ticker or not isinstance(ticker, list) or len(ticker) == 0:
                logging.warning(f"API 返回空的 ticker 数据: {symbol}")
                return self._get_fallback_price(symbol)

            # 检查价格字段
            price = ticker[0].get('p')
            if price is None:
                logging.warning(f"ticker 中缺少价格字段: {ticker[0]}")
                return self._get_fallback_price(symbol)

            # 转换为 float
            try:
                return float(price)
            except (ValueError, TypeError) as e:
                logging.error(f"价格转换失败 - price: {price}, error: {e}")
                return self._get_fallback_price(symbol)

        except Exception as e:
            logging.error(f"获取市场价格失败: {symbol}, error: {e}")
            return self._get_fallback_price(symbol)

    def _get_fallback_price(self, symbol):
        """
        Fallback：从 WebSocket depth 数据计算中间价

        Returns:
            float: 从 depth 计算的中间价，失败时返回 None
        """
        try:
            if self.use_websocket and self.ws_client:
                depth_data = self.ws_client.get_cached_depth(max_age=5)
                if depth_data:
                    mid_price = self.get_mid_price_from_depth(depth_data)
                    logging.info(f"使用 WebSocket depth 计算的价格: {mid_price}")
                    return mid_price

            # 如果 WebSocket 也不可用，返回 None
            logging.error(f"无法获取 {symbol} 的有效价格数据")
            return None

        except Exception as e:
            logging.error(f"Fallback 价格获取失败: {e}")
            return None

    def get_depth_data(self, symbol):
        """
        获取深度数据（已废弃，保留用于兼容性）
        
        注意：该方法已不再使用，风险监控不再依赖订单簿深度。
        保留仅为向后兼容，避免破坏现有代码。
        
        Returns:
            None: 始终返回None
        """
        logging.debug(f"get_depth_data 已废弃，不再获取订单簿数据: {symbol}")
        return None
    
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

    # monitor_order_book_depth 方法已移除
    # 不再监控订单簿深度，风险等级计算已简化
        
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
    def risk_monitor(self, symbol: str, depth_data: Optional[Dict] = None):
        """
        实时监控风险等级（简化版，不再依赖订单簿深度）
        
        风险因素权重：
        - 市场波动性: 50%
        - 中间价偏离: 30%
        - 市场价偏离: 20%
        
        :param symbol: 交易对 (例如 'BTCUSDT')
        :param depth_data: 可选的预获取深度数据（已废弃，保留兼容性）
        :return: 当前风险等级
        """
        try:
            # 获取市场价格（从ticker）
            market_price = self.get_market_price(symbol)
            
            # 处理 market_price 为 None 的情况
            if market_price is None:
                logging.warning(f"无法获取有效市场价格，使用保守风险等级 3")
                self.risk_level = 3
                return
            
            # 计算各项风险因素
            vol_level = self.check_market_volatility(symbol)
            
            # 使用市场价格的历史数据计算偏离
            self.midprices.append(market_price)
            if len(self.midprices) > 60:
                self.midprices.pop(0)
            
            mean_price = np.mean(self.midprices)
            std_dev = np.std(self.midprices)
            
            # 价格偏离等级
            if std_dev > 0:
                if not mean_price - 1 * std_dev <= market_price <= mean_price + 1 * std_dev:
                    price_deviation_level = 3
                elif not mean_price - 2 * std_dev <= market_price <= mean_price + 2 * std_dev:
                    price_deviation_level = 2
                else:
                    price_deviation_level = 1
            else:
                price_deviation_level = 1
            
            logging.info(
                f"风险因素: vol_level={vol_level}, "
                f"price_deviation_level={price_deviation_level}"
            )
            
            # 简化的风险等级计算（移除订单簿深度因素）
            # 波动性50% + 价格偏离50%
            level = vol_level * 0.5 + price_deviation_level * 0.5
            
            if level < 1.5:
                self.risk_level = 1
            elif level < 2.5:
                self.risk_level = 2
            else:
                self.risk_level = 3
            
            logging.info(f"综合风险等级: {self.risk_level} (score={level:.2f})")
            
        except Exception as e:
            logging.error(f"风险监控出现异常: {e}, 使用默认风险等级 3", exc_info=True)
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
            
    async def check_stop_loss(self, symbol: str):
        """
        检查止损条件

        Returns:
            StopLossResult对象，包含止损检查结果
        """
        if not self.stop_loss_manager:
            # 返回未触发的止损结果
            from etf.risk.stop_loss import StopLossResult
            return StopLossResult(
                triggered=False,
                action=StopLossAction.NONE,
                reason="止损管理器未启用",
                loss_rate=0.0,
                position_to_close=0.0
            )

        # 直接返回 StopLossResult 对象
        result = await self.stop_loss_manager.check_stop_loss(symbol)
        return result
        
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
