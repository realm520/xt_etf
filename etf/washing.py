from typing import Dict, List, Any, Optional, Union, Tuple
import time
import random
import logging
import numpy as np
import redis

from etf.utils.optimization import performance_monitor
from etf.utils.constants import (
    DEFAULT_REDIS_HOST, DEFAULT_REDIS_PORT, DEFAULT_REDIS_DB,
    DEFAULT_MAX_TRADE_AMOUNT, DEFAULT_MIN_TRADE_VALUE,
    DEFAULT_CLIENT_ORDER_ID, DEFAULT_BATCH_ID, SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, BIZ_TYPE_SPOT
)


class WashController:
    """
    ETF洗盘交易控制器，负责市场流动性维护和价格连续性管理
    
    该类实现智能洗盘交易策略，包括：
    - 基于波动率的风险控制
    - 自适应交易量调节
    - 双向交易配对执行
    - K线连续性维护
    - 性能监控和统计
    
    Attributes:
        order_manager: 订单管理器实例
        market_maker: 做市商实例
        returns (List[float]): 收益率历史记录
        max_trade_amount (int): 最大单次交易量
        total_spent (float): 累计交易成本
        r (redis.Redis): Redis连接实例
    """
    
    def __init__(self, order_manager: Any, market_maker: Any) -> None:
        """
        初始化洗盘交易控制器
        
        Args:
            order_manager: 订单管理器实例，用于执行交易
            market_maker: 做市商实例，用于获取价格信息
        """
        self.order_manager = order_manager
        self.market_maker = market_maker
        self.returns: List[float] = []

        self.max_trade_amount: int = DEFAULT_MAX_TRADE_AMOUNT
        self.total_spent: float = 0.0
        self.r: redis.Redis = redis.Redis(
            host=DEFAULT_REDIS_HOST, 
            port=DEFAULT_REDIS_PORT, 
            db=DEFAULT_REDIS_DB
        )

    def calculate_smart_volume(
        self,
        mid_price: float,
        last_mid_price: float,
        min_volume: float = 5,
        max_volume: float = 200
    ) -> float:
        """
        智能计算交易量（基于多因子模型）
        
        考虑因素：
        1. 波动率基础量
        2. 价格趋势因子
        3. 做市活跃度因子
        4. 幂律分布随机扰动
        
        Args:
            mid_price: 当前中间价
            last_mid_price: 上一个中间价
            min_volume: 最小交易量
            max_volume: 最大交易量
            
        Returns:
            float: 智能计算的交易量
        """
        # 1. 计算波动率并确定基础量
        if len(self.returns) > 0:
            volatility = abs(self.returns[-1])
        else:
            volatility = abs((mid_price - last_mid_price) / last_mid_price) if last_mid_price > 0 else 0
        
        if volatility < 0.001:  # 极低波动 (<0.1%)
            base_volume = 5
        elif volatility < 0.005:  # 低波动 (<0.5%)
            base_volume = 15
        elif volatility < 0.01:  # 中等波动 (<1%)
            base_volume = 30
        else:  # 高波动 (≥1%)
            base_volume = 50
        
        # 2. 价格趋势因子
        price_change = mid_price - last_mid_price
        if price_change > 0:
            # 上涨趋势：增加交易量（1.5-2.5倍）
            trend_factor = np.random.uniform(1.5, 2.5)
        else:
            # 下跌趋势：减少交易量（0.5-0.8倍）
            trend_factor = np.random.uniform(0.5, 0.8)
        
        # 3. 做市活跃度因子（基于最近60秒成交数）
        recent_fills = self.order_manager.get_recent_fills_count(60)
        if recent_fills > 10:
            # 高活跃：增加洗盘量
            activity_factor = 1.5
        elif recent_fills > 5:
            # 中等活跃
            activity_factor = 1.2
        else:
            # 低活跃：减少洗盘量
            activity_factor = 0.8
        
        # 4. 幂律分布扰动（Pareto分布，α=2）
        # 产生长尾分布，避免简单随机导致的平均值收敛
        power_law_factor = np.random.pareto(2.0) + 1  # +1 确保最小值为1
        
        # 5. 计算最终交易量
        final_volume = base_volume * trend_factor * activity_factor * power_law_factor
        
        # 6. 限制范围
        final_volume = np.clip(final_volume, min_volume, max_volume)
        
        logging.debug(
            f"智能交易量计算: 波动率={volatility:.4f}, 基础量={base_volume}, "
            f"趋势因子={trend_factor:.2f}, 活跃度因子={activity_factor:.2f}, "
            f"幂律因子={power_law_factor:.2f}, 最终量={final_volume:.2f}"
        )
        
        return final_volume
    
    def get_next_interval(self, lambda_rate: float = 10) -> float:
        """
        获取下一次洗盘交易的等待时间（泊松分布）
        
        使用指数分布生成泊松过程的时间间隔，产生更自然的时间分布
        
        Args:
            lambda_rate: 平均间隔（秒），默认10秒
            
        Returns:
            float: 下一次等待时间（秒），范围限制在3-20秒
        """
        # 指数分布：模拟泊松过程的到达时间
        interval = np.random.exponential(scale=lambda_rate)
        
        # 限制范围：最小3秒，最大20秒
        # 确保1分钟内至少3笔，最多20笔
        interval = np.clip(interval, 3, 20)
        
        logging.debug(f"泊松分布生成间隔: {interval:.2f}秒")
        
        return interval

    @performance_monitor.time_function("wash_trading")
    def wash(
        self,
        symbol: str,
        last_mid_price: float,
        mid_price: float,
        prec: int = 4,
        prec_amount: int = 2,
        interval: int = 60
    ) -> float:
        """
        执行智能洗盘交易策略

        基于价格变动和波动率分析，执行双向配对交易以维护市场流动性
        和价格连续性。该方法包含多重风险控制机制。

        Args:
            symbol: 交易对符号
            last_mid_price: 上一个中间价
            mid_price: 当前中间价
            prec: 价格精度位数
            prec_amount: 数量精度位数
            interval: K线连续性检查间隔（秒）

        Returns:
            float: 调整后的中间价格

        Risk Controls:
            - 黑名单检查：跳过被永久错误标记的交易对
            - 波动率限制：volatility > 1% 时跳过交易
            - 最小交易额：确保单笔交易 >= 5 USDT
            - 动态数量：根据价格涨跌调节交易量

        Note:
            该方法会同时创建买单和卖单，形成完整的wash trading配对
        """
        # 检查交易对是否在黑名单中
        if self.order_manager.is_symbol_blacklisted(symbol):
            blacklist_info = self.order_manager.get_blacklist_info(symbol)
            logging.warning(
                f"跳过洗盘交易: {symbol} 在黑名单中, "
                f"原因: {blacklist_info.get('reason')} - {blacklist_info.get('description')}, "
                f"剩余时间: {blacklist_info.get('remaining_seconds')}秒"
            )
            return mid_price  # 直接返回当前价格，不执行洗盘

        self.returns.append((mid_price - last_mid_price) / last_mid_price)
        tick = float(f"1e-{prec}")

        # 1min k-line
        if len(self.returns) > interval:
            new_mid_price = last_mid_price + random.randint(1, 2) * tick
            logging.info(
                f"[{time.strftime('%H:%M:%S')}] last {interval / 60} min closing price {last_mid_price}, closing prices from {mid_price} to {new_mid_price}"
            )
            mid_price = new_mid_price
            self.returns = [(mid_price - last_mid_price) / last_mid_price]

        # ✅ 使用智能交易量计算替代简单随机
        amount = self.calculate_smart_volume(mid_price, last_mid_price)

        volatility = self.returns[-1]
        if volatility > 0.01:
            logging.info(f"volatility {volatility} too high, skipping order")
            return mid_price

        # 确保最小交易价值（已在calculate_smart_volume中处理，但再次确认）
        if mid_price * amount < DEFAULT_MIN_TRADE_VALUE:
            amount = DEFAULT_MIN_TRADE_VALUE / mid_price

        amount = round(amount, prec_amount)
        price_change = mid_price - last_mid_price
        logging.info(f"price change {price_change}, by tick {price_change / tick}")
        logging.info(
            f"sending orders with amount {amount}, volatility {volatility}, and price {mid_price}"
        )

        last_mid_price = mid_price

        # ✅ 计算买卖价差（±0.1% - 0.3%随机扰动）
        price_offset_pct = random.uniform(0.001, 0.003)  # 0.1%-0.3%
        price_offset = mid_price * price_offset_pct
        
        # 买单价格低于中间价，卖单价格高于中间价
        buy_price = round(mid_price - price_offset, prec)
        sell_price = round(mid_price + price_offset, prec)
        
        logging.debug(
            f"洗盘价格分布: 买={buy_price:.{prec}f} | 中={mid_price:.{prec}f} | "
            f"卖={sell_price:.{prec}f} | 价差={price_offset_pct*100:.2f}%"
        )
        
        rd = random.randint(0, 1)
        try:
            buy_data = [
                {
                    "symbol": symbol,
                    "clientOrderId": self.order_manager.create_temp_id(),
                    "side": SIDE_BUY if rd == 0 else SIDE_SELL,
                    "type": ORDER_TYPE_LIMIT,
                    "timeInForce": TIME_IN_FORCE_GTC,
                    "bizType": BIZ_TYPE_SPOT,
                    "price": buy_price,  # ✅ 使用买入价
                    "quantity": amount,
                    "quoteQty": None,
                }
            ]
            res1 = self.order_manager.add_orders_batch(
                buy_data, batch_id=DEFAULT_BATCH_ID, is_wash_trading=True
            )
            logging.info(res1)
            sell_data = [
                {
                    "symbol": symbol,
                    "clientOrderId": self.order_manager.create_temp_id(),
                    "side": SIDE_SELL if rd == 0 else SIDE_BUY,
                    "type": ORDER_TYPE_LIMIT,
                    "timeInForce": TIME_IN_FORCE_GTC,
                    "bizType": BIZ_TYPE_SPOT,
                    "price": sell_price,  # ✅ 使用卖出价
                    "quantity": amount,
                    "quoteQty": None,
                }
            ]
            res2 = self.order_manager.add_orders_batch(
                sell_data, batch_id=DEFAULT_BATCH_ID, is_wash_trading=True
            )
            logging.info(res2)

        except Exception as e:
            logging.info(e)

        return last_mid_price

    def get_washing_price(self, config: Dict[str, Any]) -> float:
        """
        获取洗盘交易的基准价格
        
        从做市商获取当前最优价格，如果做市商未运行则从Redis或文件获取净值
        
        Args:
            config: 策略配置字典，包含净值键等参数
            
        Returns:
            float: 洗盘交易基准价格
            
        Fallback Strategy:
            1. 优先使用做市商的最优卖价
            2. 从Redis获取净值
            3. 从文件读取净值
            4. 使用默认值1.0
        """
        if self.market_maker.best_sell == 0:
            # 尝试从 Redis 获取净值，如果失败则使用默认值
            try:
                redis_value = self.r.get(config["netvalue"])
                if redis_value is not None:
                    mid_price = float(redis_value.decode())
                else:
                    # Redis 中没有值，尝试从文件读取
                    logging.warning(
                        f"Redis key {config['netvalue']} not found in wash controller, trying to read from file"
                    )
                    try:
                        file_path = config["netvalue"].replace(
                            "netvalue_", "net_value_"
                        )
                        with open(file_path, "r", encoding="utf8") as f:
                            mid_price = float(f.read().strip())
                        # 将值写入 Redis 以供后续使用
                        self.r.set(config["netvalue"], str(mid_price))
                        logging.info(
                            f"Wash controller loaded netvalue from file and saved to Redis: {mid_price}"
                        )
                    except FileNotFoundError:
                        # 如果文件也不存在，使用默认值
                        mid_price = 1.0
                        self.r.set(config["netvalue"], str(mid_price))
                        logging.warning(
                            f"Wash controller using default netvalue: {mid_price}"
                        )
            except Exception as e:
                logging.error(f"Wash controller error getting netvalue: {e}")
                mid_price = 1.0

            bid_ask_spread = config.get("bid_ask_spread", 0.05)

            best_sell = mid_price - ((mid_price * bid_ask_spread) / 2)
            best_buy = mid_price + ((mid_price * bid_ask_spread) / 2)
        else:
            best_sell = self.market_maker.best_sell
            best_buy = self.market_maker.best_buy

        # washing price with respect to best_sell or mid_price
        wash_method = config.get("wash", "mid_price")  # 默认使用 mid_price
        precision = config.get("precision", 6)  # 默认精度

        if wash_method == "best_sell":
            washing_price = float(best_sell) - float(
                f"1e-{precision}"
            ) * random.randint(5, 10)
        else:  # 默认使用 mid_price
            washing_price = (float(best_sell) + float(best_buy)) / 2

        return washing_price

    def run(self, risk_controller: Any, config: Dict[str, Any]) -> None:
        """
        执行完整的洗盘交易流程
        
        这是洗盘控制器的主要运行方法，包含完整的交易循环：
        1. 初始化基准价格
        2. 检查风险控制状态
        3. 获取当前市场价格
        4. 执行洗盘交易策略
        
        Args:
            risk_controller: 风险控制器实例，用于风险评估
            config: 策略配置字典，包含各种交易参数
            
        Flow:
            - 随机延迟启动（1-5秒）
            - 获取初始化价格
            - 基于风险等级决定是否执行交易
            - 调用wash方法执行具体交易
            
        Note:
            该方法会根据风险控制器的状态动态调整交易行为
        """
        time.sleep(random.randint(1, 5))

        # For initialization
        last_mid_price = self.get_washing_price(config)

        # ✅ 获取泊松分布参数（从配置中读取，默认10秒）
        lambda_rate = config.get("washing_lambda", 10)

        while True:
            # ✅ 使用泊松分布生成动态间隔
            wait_time = self.get_next_interval(lambda_rate)
            time.sleep(wait_time)

            # For each washing trade
            mid_price = self.get_washing_price(config)

            last_mid_price = self.wash(
                config["symbol"],
                last_mid_price,
                mid_price,
                config["precision"],
                config["prec_amount"],
                config["kline_continuity_interval"],
            )
    
    def get_performance_stats(self) -> Dict[str, Any]:
        """
        获取洗盘交易性能统计信息
        
        收集并返回洗盘交易的详细性能指标和运营数据，
        用于监控交易效率和成本控制
        
        Returns:
            Dict[str, Any]: 包含以下键的性能统计字典：
                - wash_trading: 洗盘交易性能指标
                - timestamp: 统计时间戳
                - total_spent: 累计交易成本
                - max_trade_amount: 最大单次交易量配置
                
        Example:
            >>> stats = wash_controller.get_performance_stats()
            >>> print(f"Total wash trades: {stats['wash_trading']['count']}")
        """
        wash_stats = performance_monitor.get_statistics("wash_trading")
        
        stats = {
            "wash_trading": wash_stats,
            "timestamp": time.strftime('%Y-%m-%d %H:%M:%S'),
            "total_spent": self.total_spent,
            "max_trade_amount": self.max_trade_amount
        }
        
        if wash_stats:
            logging.info(f"Wash trading平均耗时: {wash_stats['avg_time']:.4f}s")
            logging.info(f"Wash trading执行次数: {wash_stats['count']}")
            
        return stats
