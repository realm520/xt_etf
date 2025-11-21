"""
自然K线模拟器 - 使用泊松过程和几何布朗运动模拟真实市场行为

该模块实现了一个智能K线维护系统，通过统计模型生成自然的交易模式，
确保K线连续性的同时避免被识别为机器人交易。

核心特性:
- 泊松过程：模拟真实交易的随机到达时间
- 几何布朗运动：生成符合金融市场特征的价格路径
- 自适应成交量：基于价格变动幅度调节交易量
- 安全检查：多重风险控制确保交易安全性
"""

import time
import random
import logging
import threading
from typing import Dict, Any, List, Optional, Tuple
import numpy as np
import redis

from etf.utils.constants import (
    DEFAULT_REDIS_HOST, DEFAULT_REDIS_PORT, DEFAULT_REDIS_DB,
    SIDE_BUY, SIDE_SELL, ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, BIZ_TYPE_SPOT
)


class NaturalKlineSimulator(threading.Thread):
    """
    自然K线模拟器

    使用随机过程模拟真实市场的交易模式，确保K线连续性且不易被识别。

    主要算法:
    1. 泊松过程 (Poisson Process): 模拟交易到达时间的随机性
       - 参数λ(lambda): 平均交易间隔（秒）
       - 时间间隔服从指数分布: P(T>t) = e^(-λt)

    2. 几何布朗运动 (Geometric Brownian Motion): 模拟价格随机游走
       - dS = μS*dt + σS*dW
       - μ: 漂移率（drift），通常设为0表示无趋势
       - σ: 波动率（volatility），控制价格波动幅度
       - dW: 维纳过程（布朗运动）

    Attributes:
        order_manager: 订单管理器实例
        config: 策略配置字典
        r: Redis连接实例
        daemon: 守护线程标志
    """

    def __init__(self, order_manager: Any, config: Dict[str, Any]) -> None:
        """
        初始化自然K线模拟器

        Args:
            order_manager: 订单管理器实例，用于执行交易
            config: 策略配置字典，包含交易参数和风险控制设置
        """
        super().__init__(daemon=True)
        self.order_manager = order_manager
        self.config = config
        self.r: redis.Redis = redis.Redis(
            host=DEFAULT_REDIS_HOST,
            port=DEFAULT_REDIS_PORT,
            db=DEFAULT_REDIS_DB
        )

        # 从配置读取参数（带默认值）
        kline_config = config.get("natural_kline", {})
        self.enabled = kline_config.get("enabled", True)
        self.kline_period = kline_config.get("kline_period", 60)  # K线周期（秒）
        self.avg_trades_per_period = kline_config.get("avg_trades_per_period", 3)  # 平均交易次数
        self.volatility = kline_config.get("volatility", 0.002)  # 年化波动率
        self.min_trade_amount = kline_config.get("min_trade_amount", 5)  # 最小交易金额（USDT）
        self.max_price_change_pct = kline_config.get("max_price_change_pct", 0.01)  # 最大单笔价格变化

        # 统计数据
        self.total_simulated_trades = 0
        self.last_trade_time = time.time()

        logging.info(
            f"自然K线模拟器初始化: "
            f"周期={self.kline_period}s, "
            f"平均交易数={self.avg_trades_per_period}, "
            f"波动率={self.volatility}"
        )

    def generate_trade_schedule(self) -> List[float]:
        """
        生成一个K线周期内的交易时间表（泊松过程）

        使用泊松过程模拟真实市场的交易到达时间。在泊松过程中，
        事件（交易）的到达时间间隔服从指数分布。

        算法:
        1. 计算平均时间间隔 λ = period / avg_trades
        2. 使用指数分布生成时间间隔: Δt ~ Exp(1/λ)
        3. 累加时间间隔直到超过周期

        Returns:
            List[float]: 相对时间点列表（秒），相对于周期开始时刻

        Example:
            >>> simulator.generate_trade_schedule()
            [12.3, 28.7, 45.1]  # 在12.3s, 28.7s, 45.1s执行交易
        """
        avg_interval = self.kline_period / self.avg_trades_per_period
        trade_times = []
        current_time = 0

        while current_time < self.kline_period:
            # 指数分布: λ = 1/avg_interval
            interval = np.random.exponential(scale=avg_interval)
            current_time += interval

            if current_time < self.kline_period:
                trade_times.append(current_time)

        # 确保至少有1笔交易
        if not trade_times:
            trade_times.append(random.uniform(10, self.kline_period - 10))

        logging.debug(f"生成交易时间表: {len(trade_times)}笔交易, 时间点: {trade_times}")
        return trade_times

    def generate_price_path(
        self,
        start_price: float,
        num_trades: int
    ) -> np.ndarray:
        """
        生成价格路径（几何布朗运动）

        使用几何布朗运动（GBM）模拟价格的随机游走，这是金融市场
        价格建模的标准方法。

        几何布朗运动公式:
        S(t+Δt) = S(t) * exp((μ - σ²/2)*Δt + σ*√Δt*Z)

        其中:
        - S(t): t时刻价格
        - μ: 漂移率（drift），设为0表示无趋势
        - σ: 波动率（volatility），年化标准差
        - Δt: 时间步长（以天为单位）
        - Z: 标准正态分布随机变量 ~ N(0,1)

        Args:
            start_price: 起始价格
            num_trades: 需要生成的价格数量

        Returns:
            np.ndarray: 价格序列

        Example:
            >>> prices = simulator.generate_price_path(100.0, 3)
            >>> prices
            array([100.0, 100.12, 99.98])  # 价格围绕初始价微小波动
        """
        if num_trades == 0:
            return np.array([start_price])

        # 参数设置
        drift = 0  # 无趋势（均值回归）
        dt = self.kline_period / (num_trades * 86400)  # 转换为天为单位

        # 生成随机收益率序列
        # 使用对数收益率: r = (μ - σ²/2)*Δt + σ*√Δt*Z
        returns = np.random.normal(
            loc=drift * dt,
            scale=self.volatility * np.sqrt(dt),
            size=num_trades
        )

        # 限制单笔最大变化
        returns = np.clip(
            returns,
            -self.max_price_change_pct,
            self.max_price_change_pct
        )

        # 从对数收益率转换为价格
        # S(t+1) = S(t) * exp(r)
        prices = start_price * np.exp(np.cumsum(returns))

        logging.debug(
            f"生成价格路径: 起始={start_price:.6f}, "
            f"最终={prices[-1]:.6f}, "
            f"变化率={((prices[-1]/start_price-1)*100):.4f}%"
        )

        return prices

    def calculate_trade_amount(
        self,
        price: float,
        price_change: float
    ) -> float:
        """
        计算交易数量（自适应成交量）

        基于价格变动幅度自适应调节成交量，模拟真实市场：
        - 价格变动大 → 成交量大（突破/反转）
        - 价格变动小 → 成交量小（盘整）

        算法:
        1. 基础金额 = min_trade_amount
        2. 波动调整 = base * (1 + |price_change| * 10)
        3. 随机扰动 = adjusted * random(0.8, 1.2)

        Args:
            price: 当前价格
            price_change: 价格变化率（相对值）

        Returns:
            float: 交易数量（币数）

        Example:
            >>> amount = simulator.calculate_trade_amount(100.0, 0.001)
            >>> amount
            0.055  # 约5.5 USDT等值的币
        """
        # 基础金额
        base_amount_usdt = self.min_trade_amount

        # 根据价格变动调整（变动越大，成交量越大）
        volatility_multiplier = 1 + abs(price_change) * 10
        adjusted_amount_usdt = base_amount_usdt * volatility_multiplier

        # 随机扰动（±20%）
        random_factor = random.uniform(0.8, 1.2)
        final_amount_usdt = adjusted_amount_usdt * random_factor

        # 转换为币数量
        amount = final_amount_usdt / price

        # 应用精度
        prec_amount = self.config.get("prec_amount", 2)
        amount = round(amount, prec_amount)

        return amount

    def _get_current_price(self) -> Optional[float]:
        """
        获取当前参考价格

        优先级:
        1. Redis中的净值（最准确）
        2. 订单管理器的最优价格
        3. None（无法获取）

        Returns:
            Optional[float]: 当前价格，失败时返回None
        """
        try:
            # 尝试从Redis获取净值
            netvalue_key = self.config.get("netvalue")
            if netvalue_key:
                redis_value = self.r.get(netvalue_key)
                if redis_value:
                    return float(redis_value.decode())

            # 降级：使用订单管理器的价格（如果有）
            # 注意：这需要market_maker在运行
            # 暂时返回None，让调用者处理
            return None

        except Exception as e:
            logging.error(f"获取当前价格失败: {e}")
            return None

    def _execute_wash_trade(
        self,
        price: float,
        amount: float
    ) -> bool:
        """
        执行wash trade（带安全检查）

        安全检查清单:
        1. 黑名单检查：跳过被永久错误标记的交易对
        2. 价格合理性：价格必须在合理范围内
        3. 数量合理性：数量必须满足最小要求
        4. 成本控制：避免过度wash（未来可扩展）

        Args:
            price: 交易价格
            amount: 交易数量

        Returns:
            bool: 是否成功执行
        """
        symbol = self.config["symbol"]

        # 1. 黑名单检查
        if self.order_manager.is_symbol_blacklisted(symbol):
            blacklist_info = self.order_manager.get_blacklist_info(symbol)
            logging.warning(
                f"自然K线模拟跳过: {symbol}在黑名单中, "
                f"原因: {blacklist_info.get('reason')}"
            )
            return False

        # 2. 价格合理性检查（相对于Redis净值）
        current_price = self._get_current_price()
        if current_price:
            price_deviation = abs(price - current_price) / current_price
            if price_deviation > 0.05:  # 偏离>5%
                logging.warning(
                    f"价格偏离过大: {price} vs {current_price} "
                    f"({price_deviation*100:.2f}%)"
                )
                return False

        # 3. 数量合理性检查
        min_value = self.min_trade_amount
        if price * amount < min_value:
            logging.warning(
                f"交易金额过小: {price * amount:.2f} < {min_value}"
            )
            return False

        # 4. 执行双向订单
        precision = self.config.get("precision", 6)
        rd = random.randint(0, 1)  # 随机决定先买后卖还是先卖后买

        try:
            # 订单1
            order1_data = [{
                "symbol": symbol,
                "clientOrderId": self.order_manager.create_temp_id(),
                "side": SIDE_BUY if rd == 0 else SIDE_SELL,
                "type": ORDER_TYPE_LIMIT,
                "timeInForce": TIME_IN_FORCE_GTC,
                "bizType": BIZ_TYPE_SPOT,
                "price": round(price, precision),
                "quantity": amount,
                "quoteQty": None,
            }]

            res1 = self.order_manager.add_orders_batch(
                order1_data,
                batch_id="natural_kline",
                is_wash_trading=True
            )

            # 订单2（对手方）
            order2_data = [{
                "symbol": symbol,
                "clientOrderId": self.order_manager.create_temp_id(),
                "side": SIDE_SELL if rd == 0 else SIDE_BUY,
                "type": ORDER_TYPE_LIMIT,
                "timeInForce": TIME_IN_FORCE_GTC,
                "bizType": BIZ_TYPE_SPOT,
                "price": round(price, precision),
                "quantity": amount,
                "quoteQty": None,
            }]

            res2 = self.order_manager.add_orders_batch(
                order2_data,
                batch_id="natural_kline",
                is_wash_trading=True
            )

            self.total_simulated_trades += 1
            self.last_trade_time = time.time()

            logging.info(
                f"自然K线成交: 价格={price:.6f}, 数量={amount:.4f}, "
                f"金额={price*amount:.2f} USDT"
            )

            return True

        except Exception as e:
            logging.error(f"自然K线交易执行失败: {e}")
            return False

    def run_one_cycle(self) -> None:
        """
        执行一个K线周期的模拟

        完整流程:
        1. 生成交易时间表（泊松过程）
        2. 生成价格路径（几何布朗运动）
        3. 按时间表执行交易
        4. 等待下个周期
        """
        # 获取起始价格
        start_price = self._get_current_price()
        if not start_price:
            logging.warning("无法获取起始价格，跳过本周期")
            time.sleep(self.kline_period)
            return

        # 1. 生成交易时间表
        trade_times = self.generate_trade_schedule()
        num_trades = len(trade_times)

        # 2. 生成价格路径
        prices = self.generate_price_path(start_price, num_trades)

        # 3. 执行交易
        cycle_start = time.time()

        for i, (trade_time, price) in enumerate(zip(trade_times, prices)):
            # 等待到指定时刻
            elapsed = time.time() - cycle_start
            sleep_duration = trade_time - elapsed

            if sleep_duration > 0:
                time.sleep(sleep_duration)

            # 计算价格变化率
            price_change = (price / start_price - 1) if i == 0 else (price / prices[i-1] - 1)

            # 计算交易数量
            amount = self.calculate_trade_amount(price, price_change)

            # 执行交易
            self._execute_wash_trade(price, amount)

        # 4. 等待周期结束
        remaining = self.kline_period - (time.time() - cycle_start)
        if remaining > 0:
            time.sleep(remaining)

    def run(self) -> None:
        """
        主运行循环

        无限循环执行K线模拟，每个周期独立运行。
        捕获所有异常确保线程不会意外退出。
        """
        if not self.enabled:
            logging.info("自然K线模拟器已禁用")
            return

        logging.info("自然K线模拟器启动")

        # 随机延迟启动（避免与其他组件同时启动）
        time.sleep(random.uniform(5, 15))

        while True:
            try:
                self.run_one_cycle()
            except Exception as e:
                logging.error(f"自然K线模拟器错误: {e}", exc_info=True)
                time.sleep(10)  # 错误后短暂休息

    def get_statistics(self) -> Dict[str, Any]:
        """
        获取统计信息

        Returns:
            Dict[str, Any]: 包含运行统计的字典
        """
        return {
            "enabled": self.enabled,
            "total_simulated_trades": self.total_simulated_trades,
            "last_trade_time": self.last_trade_time,
            "avg_trades_per_period": self.avg_trades_per_period,
            "kline_period": self.kline_period,
            "volatility": self.volatility,
        }
