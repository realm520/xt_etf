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

        # 价格趋势管理
        self.price_trend: float = 0.0  # 当前价格趋势（-0.001 ~ +0.001）
        self.trend_duration: int = 0  # 趋势持续时间（秒）
        self.last_trend_switch: float = time.time()  # 上次趋势切换时间

    def get_last_trade_price(self, symbol: str) -> Optional[float]:
        """
        从Redis获取上一笔洗盘交易成交价

        Args:
            symbol: 交易对符号

        Returns:
            Optional[float]: 上一笔成交价，如果不存在返回None
        """
        key = f"last_wash_trade_price:{symbol}"
        price = self.r.get(key)
        if price:
            return float(price.decode())
        return None

    def set_last_trade_price(self, symbol: str, price: float) -> None:
        """
        保存本次洗盘交易成交价到Redis

        Args:
            symbol: 交易对符号
            price: 成交价格
        """
        key = f"last_wash_trade_price:{symbol}"
        # 1小时过期，避免长期不交易导致的价格断层
        self.r.set(key, str(price), ex=3600)
        logging.debug(f"保存洗盘成交价到Redis: {symbol} = {price:.6f}")

    def update_price_trend(self, config: Dict[str, Any]) -> None:
        """
        更新价格趋势（定期切换趋势方向）

        根据配置的切换间隔和概率，模拟真实市场的趋势转换

        Args:
            config: 策略配置，包含趋势参数
        """
        current_time = time.time()
        switch_interval = config.get("trend_switch_interval", 300)  # 默认5分钟

        # 检查是否需要切换趋势
        if current_time - self.last_trend_switch >= switch_interval:
            # 从配置读取趋势概率
            trend_up_prob = config.get("trend_up_prob", 0.15)
            trend_down_prob = config.get("trend_down_prob", 0.15)
            trend_oscillate_prob = config.get("trend_oscillate_prob", 0.70)

            # 随机选择趋势
            rand = random.random()
            if rand < trend_oscillate_prob:
                self.price_trend = 0.0  # 震荡
                trend_desc = "震荡"
            elif rand < trend_oscillate_prob + trend_up_prob:
                self.price_trend = 0.001  # 上涨 0.1%/分钟
                trend_desc = "上涨"
            else:
                self.price_trend = -0.001  # 下跌 0.1%/分钟
                trend_desc = "下跌"

            self.last_trend_switch = current_time
            self.trend_duration = 0

            logging.info(
                f"价格趋势切换: {trend_desc} ({self.price_trend*100:.2f}%/min), "
                f"下次切换时间: {switch_interval}秒后"
            )

        self.trend_duration += 1

    def generate_continuous_price(
        self,
        current_price: float,
        last_trade_price: Optional[float],
        bid_ask_spread: float,
        prec: int,
        config: Dict[str, Any]
    ) -> Tuple[float, float, float]:
        """
        生成连续K线价格（趋势+震荡+随机）

        基于上一笔成交价和当前趋势，生成自然波动的买卖价格

        Args:
            current_price: 当前净值价格（作为校准参考）
            last_trade_price: 上一笔成交价（如果有）
            bid_ask_spread: 买卖价差配置
            prec: 价格精度位数
            config: 策略配置

        Returns:
            Tuple[float, float, float]: (买入价, 卖出价, 预期成交价)
        """
        # 1. 确定基准价格
        if last_trade_price is not None:
            base_price = last_trade_price
        else:
            # 首次洗盘，使用净值价格
            base_price = current_price
            logging.info(f"首次洗盘，使用净值价格作为基准: {base_price:.{prec}f}")

        # 2. 应用趋势分量（每秒应用）
        trend_change = base_price * (self.price_trend / 60)  # 每分钟趋势/60 = 每秒趋势

        # 3. 应用震荡分量（±0.05%随机）
        volatility = config.get("kline_price_volatility", 0.001)
        oscillation = base_price * random.uniform(-volatility * 0.5, volatility * 0.5)

        # 4. 计算新基准价
        new_base = base_price + trend_change + oscillation

        # 5. 防止价格偏离净值过多（±2%限制）
        max_deviation = 0.02
        price_diff_pct = (new_base - current_price) / current_price
        if abs(price_diff_pct) > max_deviation:
            # 价格偏离过大，向净值回归
            new_base = current_price + (current_price * max_deviation * (1 if price_diff_pct > 0 else -1))
            logging.warning(
                f"价格偏离过大({price_diff_pct*100:.2f}%)，回归净值: "
                f"{base_price:.{prec}f} → {new_base:.{prec}f}"
            )

        # 6. 生成买卖价（使用配置的bid_ask_spread）
        half_spread = bid_ask_spread / 2
        buy_price = round(new_base * (1 - half_spread), prec)
        sell_price = round(new_base * (1 + half_spread), prec)

        # 7. 随机选择下一笔成交价（模拟市场情绪）
        if self.price_trend > 0:
            # 上涨趋势：60%概率卖价成交
            next_trade = sell_price if random.random() < 0.6 else buy_price
        elif self.price_trend < 0:
            # 下跌趋势：60%概率买价成交
            next_trade = buy_price if random.random() < 0.6 else sell_price
        else:
            # 震荡：50/50概率
            next_trade = random.choice([buy_price, sell_price])

        logging.debug(
            f"价格生成: 基准={base_price:.{prec}f}, 趋势={trend_change:.6f}, "
            f"震荡={oscillation:.6f}, 新基准={new_base:.{prec}f}, "
            f"买={buy_price:.{prec}f}, 卖={sell_price:.{prec}f}, 预计成交={next_trade:.{prec}f}"
        )

        return buy_price, sell_price, next_trade

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

    def generate_micro_trades(
        self,
        buy_price: float,
        sell_price: float,
        total_amount: float,
        prec: int,
        prec_amount: int,
        config: Dict[str, Any]
    ) -> List[Dict[str, Any]]:
        """
        生成多笔小单（分笔成交），模拟真实市场的成交分布
        
        每次洗盘生成3-5笔小单，价格在买卖区间内随机分布，
        自然形成K线的开高低收和上下影线。
        
        Args:
            buy_price: 买价区间下限
            sell_price: 卖价区间上限
            total_amount: 总交易量
            prec: 价格精度
            prec_amount: 数量精度
            config: 策略配置
            
        Returns:
            List[Dict]: 微交易列表，每个包含price和quantity
            
        Example:
            买价=0.7280, 卖价=0.7340, 总量=100
            生成:
            - 0.7285, 数量25 (低位)
            - 0.7310, 数量30 (中位)
            - 0.7335, 数量20 (高位)
            - 0.7295, 数量25 (回落)
            → K线: 开0.7285, 高0.7335, 低0.7285, 收0.7295
        """
        # 从配置读取参数
        micro_trades_count = config.get("micro_trades_count", random.randint(3, 5))
        
        # 确保至少3笔，最多7笔
        micro_trades_count = max(3, min(7, micro_trades_count))
        
        # 生成价格序列（在买卖区间内均匀+随机分布）
        prices = []
        price_range = sell_price - buy_price
        
        # 根据趋势决定价格分布偏向
        if self.price_trend > 0:
            # 上涨趋势：价格逐步上升，偏向高价
            for i in range(micro_trades_count):
                # 使用beta分布(α=2, β=5) → 偏向低位开始
                beta_sample = np.random.beta(2, 5) if i == 0 else np.random.beta(5, 2)
                price = buy_price + price_range * beta_sample
                prices.append(round(price, prec))
        elif self.price_trend < 0:
            # 下跌趋势：价格逐步下降，偏向低价
            for i in range(micro_trades_count):
                # 使用beta分布(α=5, β=2) → 偏向高位开始
                beta_sample = np.random.beta(5, 2) if i == 0 else np.random.beta(2, 5)
                price = buy_price + price_range * beta_sample
                prices.append(round(price, prec))
        else:
            # 震荡：随机分布
            for _ in range(micro_trades_count):
                price = buy_price + price_range * random.random()
                prices.append(round(price, prec))
        
        # 生成数量序列（确保总和=total_amount）
        # 使用Dirichlet分布生成数量权重
        alpha = np.ones(micro_trades_count)  # 均匀分布
        weights = np.random.dirichlet(alpha)
        
        quantities = []
        remaining = total_amount
        for i, weight in enumerate(weights[:-1]):
            qty = round(total_amount * weight, prec_amount)
            # 确保不超过剩余量
            qty = min(qty, remaining - (len(weights) - i - 1) * 0.01)
            quantities.append(max(0.01, qty))  # 最小0.01
            remaining -= qty
        
        # 最后一笔用剩余量
        quantities.append(round(max(0.01, remaining), prec_amount))
        
        # 组合成微交易列表
        micro_trades = []
        for price, quantity in zip(prices, quantities):
            micro_trades.append({
                "price": price,
                "quantity": quantity
            })
        
        # 按价格排序（模拟市场逐步成交）
        if self.price_trend > 0:
            micro_trades.sort(key=lambda x: x["price"])  # 上涨：从低到高
        elif self.price_trend < 0:
            micro_trades.sort(key=lambda x: x["price"], reverse=True)  # 下跌：从高到低
        else:
            random.shuffle(micro_trades)  # 震荡：随机顺序
        
        logging.debug(
            f"生成{len(micro_trades)}笔微交易: "
            f"价格范围[{min(p['price'] for p in micro_trades):.{prec}f}, "
            f"{max(p['price'] for p in micro_trades):.{prec}f}], "
            f"总量={sum(t['quantity'] for t in micro_trades):.{prec_amount}f}"
        )
        
        return micro_trades

    @performance_monitor.time_function("wash_trading")
    def wash(
        self,
        symbol: str,
        last_mid_price: float,
        mid_price: float,
        config: Dict[str, Any],
        prec: int = 4,
        prec_amount: int = 2
    ) -> float:
        """
        执行智能洗盘交易策略（基于连续K线生成）

        基于上一笔成交价和价格趋势，生成自然连续的K线，
        同时执行双向配对交易维护市场流动性。

        Args:
            symbol: 交易对符号
            last_mid_price: 上一个中间价（保留参数，兼容性）
            mid_price: 当前净值价格
            config: 策略配置字典
            prec: 价格精度位数
            prec_amount: 数量精度位数

        Returns:
            float: 本次洗盘的成交价（用于下一次基准）

        Risk Controls:
            - 黑名单检查：跳过被永久错误标记的交易对
            - 波动率限制：防止异常波动
            - 价格偏离限制：防止价格偏离净值过多（±2%）
            - 最小交易额：确保单笔交易 >= 5 USDT

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
            return mid_price

        # ✅ 获取上一笔成交价
        last_trade_price = self.get_last_trade_price(symbol)

        # ✅ 生成连续K线价格（趋势+震荡）
        bid_ask_spread = config.get("bid_ask_spread", 0.008)
        buy_price, sell_price, next_trade_price = self.generate_continuous_price(
            current_price=mid_price,
            last_trade_price=last_trade_price,
            bid_ask_spread=bid_ask_spread,
            prec=prec,
            config=config
        )

        # ✅ 使用智能交易量计算
        total_amount = self.calculate_smart_volume(mid_price, last_mid_price)

        # 确保最小交易价值
        if mid_price * total_amount < DEFAULT_MIN_TRADE_VALUE:
            total_amount = DEFAULT_MIN_TRADE_VALUE / mid_price

        total_amount = round(total_amount, prec_amount)

        # ✅ 生成分笔成交（3-5笔小单）
        micro_trades = self.generate_micro_trades(
            buy_price=buy_price,
            sell_price=sell_price,
            total_amount=total_amount,
            prec=prec,
            prec_amount=prec_amount,
            config=config
        )

        # 计算平均成交价（作为下一次的基准）
        avg_price = sum(t["price"] * t["quantity"] for t in micro_trades) / total_amount
        avg_price = round(avg_price, prec)

        logging.info(
            f"洗盘交易: {symbol} | 总量={total_amount} | 笔数={len(micro_trades)} | "
            f"价格区间=[{buy_price:.{prec}f}, {sell_price:.{prec}f}] | "
            f"平均价={avg_price:.{prec}f} | "
            f"上笔={'首次' if last_trade_price is None else f'{last_trade_price:.{prec}f}'}"
        )

        # ✅ 批量下单（所有微交易）
        try:
            orders_data = []
            
            for i, trade in enumerate(micro_trades):
                # 交替买卖方向，避免单方向堆积
                side = SIDE_BUY if i % 2 == 0 else SIDE_SELL
                
                orders_data.append({
                    "symbol": symbol,
                    "clientOrderId": self.order_manager.create_temp_id(),
                    "side": side,
                    "type": ORDER_TYPE_LIMIT,
                    "timeInForce": TIME_IN_FORCE_GTC,
                    "bizType": BIZ_TYPE_SPOT,
                    "price": trade["price"],
                    "quantity": trade["quantity"],
                    "quoteQty": None,
                })
            
            # 批量下单
            res = self.order_manager.add_orders_batch(
                orders_data, batch_id=DEFAULT_BATCH_ID, is_wash_trading=True
            )
            logging.debug(f"洗盘批量下单结果: {len(micro_trades)}笔, 响应={res}")

            # ✅ 保存本次平均成交价到Redis
            self.set_last_trade_price(symbol, avg_price)

        except Exception as e:
            logging.error(f"洗盘交易失败: {e}", exc_info=True)
            # 失败时返回当前净值价格
            return mid_price

        # ✅ 返回平均成交价，用于下一次计算
        return avg_price

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
        执行完整的洗盘交易流程（每秒检查+随机交易）

        这是洗盘控制器的主要运行方法，采用每秒检查机制：
        1. 每秒检查一次
        2. 根据配置的平均间隔计算交易概率
        3. 随机决定是否执行交易
        4. 更新价格趋势
        5. 执行洗盘交易策略

        Args:
            risk_controller: 风险控制器实例，用于风险评估
            config: 策略配置字典，包含各种交易参数

        Flow:
            - 随机延迟启动（1-5秒）
            - 固定间隔 + 随机抖动（±20%）
            - 根据washing_lambda作为基准间隔（如15秒）
            - 确保每分钟稳定执行指定次数（如4次）
            - 更新价格趋势（每5分钟切换）

        Note:
            使用固定间隔+抖动模式，确保最小交易频率的同时保持自然性
            例如：15秒基准 → 实际间隔12-18秒 → 1分钟约3.3-5次
        """
        time.sleep(random.randint(1, 5))

        # 初始化
        last_mid_price = self.get_washing_price(config)

        # ✅ 从配置读取基准间隔（默认15秒 → 1分钟4次）
        avg_interval = config.get("washing_lambda", 15)

        # ✅ 添加随机抖动范围（±20%，避免机械感）
        jitter_range = avg_interval * 0.2

        logging.info(
            f"洗盘交易启动: 基准间隔={avg_interval}秒, "
            f"抖动范围=±{jitter_range:.1f}秒, "
            f"预计1分钟{60/avg_interval:.1f}次（确保）"
        )

        while True:
            # ✅ 固定间隔 + 随机抖动
            sleep_time = avg_interval + random.uniform(-jitter_range, jitter_range)
            time.sleep(sleep_time)

            # ✅ 更新价格趋势（定期切换）
            self.update_price_trend(config)

            # 获取当前净值价格
            mid_price = self.get_washing_price(config)

            # 执行洗盘交易
            last_mid_price = self.wash(
                symbol=config["symbol"],
                last_mid_price=last_mid_price,
                mid_price=mid_price,
                config=config,
                prec=config["precision"],
                prec_amount=config["prec_amount"],
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
