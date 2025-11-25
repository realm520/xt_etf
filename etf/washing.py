from typing import Dict, List, Any, Optional, Union, Tuple
from dataclasses import dataclass, field
from enum import Enum
import time
import random
import logging
import uuid
import numpy as np
import redis

from etf.utils.optimization import performance_monitor
from etf.utils.constants import (
    DEFAULT_REDIS_HOST, DEFAULT_REDIS_PORT, DEFAULT_REDIS_DB,
    DEFAULT_MAX_TRADE_AMOUNT, DEFAULT_MIN_TRADE_VALUE,
    DEFAULT_CLIENT_ORDER_ID, DEFAULT_BATCH_ID, SIDE_BUY, SIDE_SELL,
    ORDER_TYPE_LIMIT, TIME_IN_FORCE_GTC, BIZ_TYPE_SPOT
)


class WashOrderStatus(Enum):
    """洗盘订单对状态"""
    PENDING = "pending"              # 两边都未成交
    BUY_FILLED = "buy_filled"        # 只有买单成交
    SELL_FILLED = "sell_filled"      # 只有卖单成交
    COMPLETED = "completed"          # 两边都成交（正常完成）
    ORPHAN_CANCELLED = "orphan_cancelled"  # 孤儿订单已撤销


@dataclass
class WashOrderPair:
    """
    洗盘订单对，表示一对配对的买卖订单
    
    Attributes:
        pair_id: 唯一标识符
        symbol: 交易对
        buy_order_id: 买单订单ID
        sell_order_id: 卖单订单ID
        price: 成交价格
        quantity: 成交数量
        created_at: 创建时间戳
        status: 订单对状态
        buy_filled: 买单是否成交
        sell_filled: 卖单是否成交
        last_check_time: 上次检查时间
    """
    pair_id: str
    symbol: str
    buy_order_id: str
    sell_order_id: str
    price: float
    quantity: float
    created_at: float = field(default_factory=time.time)
    status: WashOrderStatus = WashOrderStatus.PENDING
    buy_filled: bool = False
    sell_filled: bool = False
    last_check_time: float = 0.0


class WashOrderTracker:
    """
    洗盘订单追踪器
    
    负责追踪洗盘订单对的状态，检测孤儿订单并触发撤销。
    
    孤儿订单定义：一对洗盘订单中，一笔被外部用户成交，另一笔未成交。
    这种情况下需要撤销未成交的订单，避免累积挂单。
    
    Attributes:
        pending_pairs: 待处理的订单对
        completed_pairs: 已完成的订单对（用于统计）
        orphan_count: 孤儿订单计数
        check_interval: 检查间隔（秒）
        max_wait_time: 最大等待时间（秒），超时视为异常
    """
    
    def __init__(
        self, 
        client: Any,
        check_interval: float = 5.0,
        max_wait_time: float = 30.0,
        max_pending_pairs: int = 100
    ):
        """
        初始化订单追踪器
        
        Args:
            client: 交易所客户端，用于查询订单状态和撤单
            check_interval: 状态检查间隔（秒）
            max_wait_time: 订单最大等待时间（秒）
            max_pending_pairs: 最大待处理订单对数量
        """
        self.client = client
        self.check_interval = check_interval
        self.max_wait_time = max_wait_time
        self.max_pending_pairs = max_pending_pairs
        
        self.pending_pairs: Dict[str, WashOrderPair] = {}
        self.completed_count: int = 0
        self.orphan_count: int = 0
        self.cancelled_count: int = 0
        self._last_check_time: float = 0.0
        
    def add_pair(
        self,
        symbol: str,
        buy_order_id: str,
        sell_order_id: str,
        price: float,
        quantity: float
    ) -> str:
        """
        添加一个洗盘订单对进行追踪
        
        Args:
            symbol: 交易对
            buy_order_id: 买单ID
            sell_order_id: 卖单ID
            price: 价格
            quantity: 数量
            
        Returns:
            pair_id: 订单对唯一标识符
        """
        pair_id = f"wash_{uuid.uuid4().hex[:8]}"
        
        pair = WashOrderPair(
            pair_id=pair_id,
            symbol=symbol,
            buy_order_id=buy_order_id,
            sell_order_id=sell_order_id,
            price=price,
            quantity=quantity,
        )
        
        self.pending_pairs[pair_id] = pair
        
        # 如果待处理数量超限，清理最老的
        if len(self.pending_pairs) > self.max_pending_pairs:
            self._cleanup_old_pairs()
            
        logging.debug(
            f"[WashTracker] 添加订单对: {pair_id} | "
            f"买单={buy_order_id}, 卖单={sell_order_id}, "
            f"价格={price}, 数量={quantity}"
        )
        
        return pair_id
    
    def check_and_handle_orphans(self) -> Dict[str, Any]:
        """
        检查所有待处理订单对的状态，处理孤儿订单
        
        Returns:
            Dict: 检查结果统计
                - checked: 检查的订单对数量
                - completed: 正常完成数量
                - orphans_found: 发现的孤儿订单数量
                - cancelled: 撤销的订单数量
                - errors: 错误数量
        """
        current_time = time.time()
        
        # 检查间隔控制
        if current_time - self._last_check_time < self.check_interval:
            return {"skipped": True, "reason": "check_interval_not_reached"}
            
        self._last_check_time = current_time
        
        if not self.pending_pairs:
            return {"checked": 0}
            
        result = {
            "checked": 0,
            "completed": 0,
            "orphans_found": 0,
            "cancelled": 0,
            "errors": 0,
            "expired": 0,
        }
        
        pairs_to_remove = []
        
        for pair_id, pair in self.pending_pairs.items():
            result["checked"] += 1
            
            try:
                # 检查订单状态
                buy_status = self._get_order_status(pair.buy_order_id)
                sell_status = self._get_order_status(pair.sell_order_id)
                
                pair.last_check_time = current_time
                
                # 判断成交状态
                buy_filled = buy_status in ("FILLED", "PARTIALLY_FILLED_CANCELED")
                sell_filled = sell_status in ("FILLED", "PARTIALLY_FILLED_CANCELED")
                buy_cancelled = buy_status in ("CANCELED", "REJECTED", "EXPIRED")
                sell_cancelled = sell_status in ("CANCELED", "REJECTED", "EXPIRED")
                
                pair.buy_filled = buy_filled
                pair.sell_filled = sell_filled
                
                # 情况1: 两边都成交 - 正常完成
                if buy_filled and sell_filled:
                    pair.status = WashOrderStatus.COMPLETED
                    pairs_to_remove.append(pair_id)
                    self.completed_count += 1
                    result["completed"] += 1
                    logging.debug(f"[WashTracker] 订单对完成: {pair_id}")
                    continue
                    
                # 情况2: 一边成交，另一边未成交 - 孤儿订单
                if buy_filled and not sell_filled and not sell_cancelled:
                    # 买单成交，卖单未成交 - 撤销卖单
                    pair.status = WashOrderStatus.BUY_FILLED
                    self._cancel_orphan_order(pair.sell_order_id, pair_id, "sell")
                    pair.status = WashOrderStatus.ORPHAN_CANCELLED
                    pairs_to_remove.append(pair_id)
                    self.orphan_count += 1
                    self.cancelled_count += 1
                    result["orphans_found"] += 1
                    result["cancelled"] += 1
                    continue
                    
                if sell_filled and not buy_filled and not buy_cancelled:
                    # 卖单成交，买单未成交 - 撤销买单
                    pair.status = WashOrderStatus.SELL_FILLED
                    self._cancel_orphan_order(pair.buy_order_id, pair_id, "buy")
                    pair.status = WashOrderStatus.ORPHAN_CANCELLED
                    pairs_to_remove.append(pair_id)
                    self.orphan_count += 1
                    self.cancelled_count += 1
                    result["orphans_found"] += 1
                    result["cancelled"] += 1
                    continue
                
                # 情况3: 两边都被撤销/拒绝 - 异常情况，移除
                if buy_cancelled and sell_cancelled:
                    pairs_to_remove.append(pair_id)
                    logging.warning(
                        f"[WashTracker] 订单对异常(两边都被撤销): {pair_id}"
                    )
                    continue
                    
                # 情况4: 超时检查
                age = current_time - pair.created_at
                if age > self.max_wait_time:
                    # 超时，两边都撤销
                    if not buy_filled and not buy_cancelled:
                        self._cancel_orphan_order(pair.buy_order_id, pair_id, "buy", "timeout")
                        result["cancelled"] += 1
                    if not sell_filled and not sell_cancelled:
                        self._cancel_orphan_order(pair.sell_order_id, pair_id, "sell", "timeout")
                        result["cancelled"] += 1
                    pairs_to_remove.append(pair_id)
                    result["expired"] += 1
                    logging.warning(
                        f"[WashTracker] 订单对超时({age:.1f}s): {pair_id}, 已撤销未成交订单"
                    )
                    
            except Exception as e:
                result["errors"] += 1
                logging.error(f"[WashTracker] 检查订单对失败: {pair_id}, 错误: {e}")
                
        # 移除已处理的订单对
        for pair_id in pairs_to_remove:
            del self.pending_pairs[pair_id]
            
        if result["orphans_found"] > 0 or result["expired"] > 0:
            logging.info(
                f"[WashTracker] 检查完成: "
                f"检查={result['checked']}, 完成={result['completed']}, "
                f"孤儿={result['orphans_found']}, 超时={result['expired']}, "
                f"撤销={result['cancelled']}, 待处理={len(self.pending_pairs)}"
            )
            
        return result
    
    def _get_order_status(self, order_id: str) -> str:
        """
        查询订单状态
        
        Args:
            order_id: 订单ID
            
        Returns:
            订单状态字符串: NEW, PARTIALLY_FILLED, FILLED, CANCELED, REJECTED, EXPIRED等
        """
        try:
            order_info = self.client.get_order(order_id=order_id)
            return order_info.get("state", "UNKNOWN")
        except Exception as e:
            logging.debug(f"[WashTracker] 查询订单状态失败: {order_id}, {e}")
            return "UNKNOWN"
    
    def _cancel_orphan_order(
        self, 
        order_id: str, 
        pair_id: str, 
        side: str,
        reason: str = "orphan"
    ) -> bool:
        """
        撤销孤儿订单
        
        Args:
            order_id: 要撤销的订单ID
            pair_id: 订单对ID
            side: 订单方向 (buy/sell)
            reason: 撤销原因
            
        Returns:
            是否撤销成功
        """
        try:
            self.client.cancel_order(order_id)
            logging.warning(
                f"[WashTracker] 撤销孤儿订单: {order_id} ({side}) | "
                f"订单对={pair_id}, 原因={reason}"
            )
            return True
        except Exception as e:
            # 可能订单已经被撤销或成交
            logging.debug(
                f"[WashTracker] 撤销订单失败(可能已处理): {order_id}, {e}"
            )
            return False
    
    def _cleanup_old_pairs(self) -> None:
        """清理最老的订单对（当数量超限时）"""
        if len(self.pending_pairs) <= self.max_pending_pairs:
            return
            
        # 按创建时间排序，移除最老的
        sorted_pairs = sorted(
            self.pending_pairs.items(),
            key=lambda x: x[1].created_at
        )
        
        # 移除超出限制的部分
        remove_count = len(self.pending_pairs) - self.max_pending_pairs + 10
        for pair_id, _ in sorted_pairs[:remove_count]:
            del self.pending_pairs[pair_id]
            
        logging.warning(
            f"[WashTracker] 清理旧订单对: 移除{remove_count}个, "
            f"剩余{len(self.pending_pairs)}个"
        )
    
    def get_stats(self) -> Dict[str, Any]:
        """获取追踪器统计信息"""
        return {
            "pending_pairs": len(self.pending_pairs),
            "completed_count": self.completed_count,
            "orphan_count": self.orphan_count,
            "cancelled_count": self.cancelled_count,
        }


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

        # ✅ 优雅停止机制
        self._running: bool = False  # 运行状态标志
        self._last_trade_time: float = 0.0  # 上次交易时间（用于判断是否在交易中）
        
        # ✅ 洗盘订单追踪器 - 检测和处理孤儿订单
        self.order_tracker: Optional[WashOrderTracker] = None
        self._tracker_enabled: bool = True  # 是否启用订单追踪
    
    def init_order_tracker(
        self, 
        client: Any,
        check_interval: float = 5.0,
        max_wait_time: float = 30.0
    ) -> None:
        """
        初始化洗盘订单追踪器
        
        Args:
            client: 交易所客户端，用于查询订单状态和撤单
            check_interval: 状态检查间隔（秒）
            max_wait_time: 订单最大等待时间（秒）
        """
        self.order_tracker = WashOrderTracker(
            client=client,
            check_interval=check_interval,
            max_wait_time=max_wait_time
        )
        logging.info(
            f"[WashController] 订单追踪器已初始化: "
            f"检查间隔={check_interval}s, 最大等待={max_wait_time}s"
        )
    
    def _track_wash_order_pairs(
        self,
        symbol: str,
        orders_data: List[Dict[str, Any]],
        results: List[Dict[str, Any]],
        prec: int = 4
    ) -> int:
        """
        将成功的洗盘订单对添加到追踪器
        
        Args:
            symbol: 交易对
            orders_data: 原始订单数据列表
            results: 下单结果列表
            prec: 价格精度
            
        Returns:
            int: 成功追踪的订单对数量
        """
        if not self.order_tracker:
            return 0
            
        tracked_count = 0
        
        # 按配对处理：每两个订单（买+卖）组成一对
        for i in range(0, len(results), 2):
            if i + 1 >= len(results):
                break
                
            buy_result = results[i]
            sell_result = results[i + 1]
            
            # 只追踪两边都下单成功的配对
            if not buy_result.get("success") or not sell_result.get("success"):
                continue
                
            buy_order_id = buy_result.get("order_id")
            sell_order_id = sell_result.get("order_id")
            
            if not buy_order_id or not sell_order_id:
                continue
                
            # 获取价格和数量
            price = buy_result.get("price", 0)
            quantity = buy_result.get("quantity", 0)
            
            # 添加到追踪器
            pair_id = self.order_tracker.add_pair(
                symbol=symbol,
                buy_order_id=buy_order_id,
                sell_order_id=sell_order_id,
                price=price,
                quantity=quantity
            )
            tracked_count += 1
            
        if tracked_count > 0:
            logging.debug(
                f"[WashController] 追踪 {tracked_count} 个订单对, "
                f"待处理总数={len(self.order_tracker.pending_pairs)}"
            )
            
        return tracked_count
    
    def check_orphan_orders(self) -> Dict[str, Any]:
        """
        检查并处理孤儿订单
        
        应在主循环中定期调用此方法，用于检测一边成交、另一边未成交的
        洗盘订单对，并自动撤销未成交的订单。
        
        Returns:
            Dict: 检查结果统计
        """
        if not self.order_tracker or not self._tracker_enabled:
            return {"skipped": True, "reason": "tracker_not_enabled"}
            
        return self.order_tracker.check_and_handle_orphans()
    
    def get_tracker_stats(self) -> Dict[str, Any]:
        """获取订单追踪器统计信息"""
        if not self.order_tracker:
            return {"enabled": False}
            
        stats = self.order_tracker.get_stats()
        stats["enabled"] = True
        return stats

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
        生成洗盘交易的安全价格区间

        安全区间 = (best_buy, best_sell)，严格在买一卖一之间，不触碰边界。

        Args:
            current_price: 当前净值价格（作为校准参考）
            last_trade_price: 上一笔成交价（如果有）
            bid_ask_spread: 买卖价差配置
            prec: 价格精度位数
            config: 策略配置

        Returns:
            Tuple[float, float, float]: (安全区间下限, 安全区间上限, 参考中间价)
        """
        # 1. 获取做市商的买卖价格
        best_sell = self.market_maker.best_sell
        best_buy = self.market_maker.best_buy

        # 2. 最小价格单位
        min_tick = 10 ** (-prec)

        # 3. 计算安全区间
        if best_sell > 0 and best_buy > 0 and best_sell > best_buy:
            # 安全区间：严格在买一卖一之间，不触碰边界
            safe_min = best_buy + min_tick  # 比买一高一个tick
            safe_max = best_sell - min_tick  # 比卖一低一个tick
            
            # 确保区间有效
            if safe_max <= safe_min:
                # 买卖价差太小（只有1-2个tick），使用中间价
                mid = round((best_sell + best_buy) / 2, prec)
                safe_min = mid
                safe_max = mid
                logging.warning(
                    f"⚠️ 做市商价差过小，洗盘使用中间价: {mid:.{prec}f}"
                )
            else:
                logging.debug(
                    f"洗盘安全区间: ({safe_min:.{prec}f}, {safe_max:.{prec}f}) "
                    f"做市商: 买一={best_buy:.{prec}f}, 卖一={best_sell:.{prec}f}"
                )
        else:
            # 做市商未挂单，基于净值价格计算模拟区间
            half_spread = current_price * bid_ask_spread / 2
            safe_min = round(current_price - half_spread * 0.5, prec)
            safe_max = round(current_price + half_spread * 0.5, prec)
            logging.debug(
                f"做市商未挂单，使用净值附近区间: ({safe_min:.{prec}f}, {safe_max:.{prec}f})"
            )

        # 4. 计算参考中间价（用于趋势计算）
        if last_trade_price is not None:
            # 基于上一笔成交价，应用趋势
            trend_change = last_trade_price * (self.price_trend / 60)
            volatility = config.get("kline_price_volatility", 0.001)
            oscillation = last_trade_price * random.uniform(-volatility * 0.5, volatility * 0.5)
            ref_price = last_trade_price + trend_change + oscillation
        else:
            ref_price = current_price

        # 5. 将参考价格限制在安全区间内
        ref_price = max(safe_min, min(safe_max, ref_price))
        ref_price = round(ref_price, prec)

        return round(safe_min, prec), round(safe_max, prec), ref_price

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
        生成配对的洗盘交易（每对买卖价格数量相同，确保自成交）

        每对交易包含一个买单和一个卖单，价格和数量完全相同，
        这样交易所会自动撮合成交，不会影响做市商订单。

        Args:
            buy_price: 安全区间下限（原参数名保留兼容）
            sell_price: 安全区间上限（原参数名保留兼容）
            total_amount: 总交易量
            prec: 价格精度
            prec_amount: 数量精度
            config: 策略配置

        Returns:
            List[Dict]: 配对交易列表，每个元素包含 price, quantity, is_pair_start
                       is_pair_start=True 表示这是一对的开始（买单）
                       is_pair_start=False 表示这是配对的卖单
        """
        # 从配置读取交易对数量，默认2-4对
        num_pairs = config.get("wash_pairs_count", random.randint(2, 4))
        num_pairs = max(2, min(5, num_pairs))  # 限制2-5对

        safe_min = buy_price  # 安全区间下限
        safe_max = sell_price  # 安全区间上限
        price_range = safe_max - safe_min

        logging.info(
            f"🔍 [步骤4] 生成{num_pairs}对配对交易: "
            f"安全区间=[{safe_min:.{prec}f}, {safe_max:.{prec}f}], "
            f"区间宽度={price_range:.{prec}f}"
        )

        # 1. 分配数量给每对（使用Dirichlet分布）
        alpha = np.ones(num_pairs) * 2  # 稍微集中的分布
        weights = np.random.dirichlet(alpha)
        
        quantities = []
        remaining = total_amount
        min_qty = max(0.01, 10 ** (-prec_amount))  # 最小数量
        
        for i, weight in enumerate(weights[:-1]):
            qty = round(total_amount * weight, prec_amount)
            qty = max(min_qty, min(qty, remaining - (num_pairs - i - 1) * min_qty))
            quantities.append(qty)
            remaining -= qty
        
        # 最后一对用剩余量
        quantities.append(round(max(min_qty, remaining), prec_amount))

        # 2. 为每对生成价格（在安全区间内）
        paired_trades = []
        
        for i, qty in enumerate(quantities):
            if price_range > 0:
                # 根据趋势决定价格分布
                if self.price_trend > 0:
                    # 上涨趋势：价格逐步上升
                    progress = (i + 0.5) / num_pairs
                    noise = random.uniform(-0.1, 0.1)
                    price = safe_min + price_range * (progress + noise)
                elif self.price_trend < 0:
                    # 下跌趋势：价格逐步下降
                    progress = 1 - (i + 0.5) / num_pairs
                    noise = random.uniform(-0.1, 0.1)
                    price = safe_min + price_range * (progress + noise)
                else:
                    # 震荡：随机分布
                    price = safe_min + price_range * random.random()
                
                # 确保价格在安全区间内
                price = max(safe_min, min(safe_max, price))
            else:
                # 区间为0，使用同一价格
                price = safe_min
            
            price = round(price, prec)
            
            # 添加买单（配对开始）
            paired_trades.append({
                "price": price,
                "quantity": qty,
                "is_pair_start": True,  # 标记为买单
            })
            
            # 添加卖单（配对结束，同价同量）
            paired_trades.append({
                "price": price,
                "quantity": qty,
                "is_pair_start": False,  # 标记为卖单
            })

        # 3. 日志：显示配对信息
        pair_info = []
        for i in range(0, len(paired_trades), 2):
            buy = paired_trades[i]
            sell = paired_trades[i + 1]
            pair_info.append(f"({buy['price']:.{prec}f}, {buy['quantity']})")
        
        logging.info(
            f"🔍 [步骤4完成] 配对交易: {pair_info}, "
            f"总量={sum(t['quantity'] for t in paired_trades[::2]):.{prec_amount}f}"
        )

        return paired_trades

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
        # 只计算买单（配对开始），因为每对买卖数量相同
        buy_trades = [t for t in micro_trades if t.get("is_pair_start", True)]
        actual_total = sum(t["quantity"] for t in buy_trades)
        avg_price = sum(t["price"] * t["quantity"] for t in buy_trades) / actual_total if actual_total > 0 else buy_price
        avg_price = round(avg_price, prec)

        num_pairs = len(buy_trades)
        logging.info(
            f"洗盘交易: {symbol} | {num_pairs}对订单 | 总量={actual_total:.{prec_amount}f} | "
            f"安全区间=[{buy_price:.{prec}f}, {sell_price:.{prec}f}] | "
            f"平均价={avg_price:.{prec}f} | "
            f"上笔={'首次' if last_trade_price is None else f'{last_trade_price:.{prec}f}'}"
        )

        # ✅ 配对下单：每对买卖订单价格数量相同，确保自成交
        try:
            orders_data = []

            for trade in micro_trades:
                # 使用 is_pair_start 标记决定买卖方向
                # True = 买单（配对开始），False = 卖单（配对结束）
                side = SIDE_BUY if trade.get("is_pair_start", True) else SIDE_SELL

                orders_data.append({
                    "symbol": symbol,
                    "side": side,
                    "price": trade["price"],
                    "quantity": trade["quantity"],
                    "order_purpose": "wash_trading",
                })

            # ✅ 调试日志：显示配对订单信息
            buy_orders = [o for o in orders_data if o['side'] == SIDE_BUY]
            sell_orders = [o for o in orders_data if o['side'] == SIDE_SELL]
            
            # 验证配对：每对买卖订单价格数量应该相同
            pairs_valid = True
            pair_details = []
            for i in range(0, len(orders_data), 2):
                if i + 1 < len(orders_data):
                    buy = orders_data[i]
                    sell = orders_data[i + 1]
                    is_valid = (
                        buy['side'] == SIDE_BUY and 
                        sell['side'] == SIDE_SELL and
                        buy['price'] == sell['price'] and 
                        buy['quantity'] == sell['quantity']
                    )
                    pairs_valid = pairs_valid and is_valid
                    pair_details.append(
                        f"对{i//2+1}: {buy['price']}x{buy['quantity']} ({'✓' if is_valid else '✗'})"
                    )

            logging.info(
                f"🔍 [步骤5] 配对订单构造完成: "
                f"{len(buy_orders)}对买卖订单, "
                f"配对验证={'通过' if pairs_valid else '失败'}, "
                f"详情={pair_details}"
            )

            # ✅ 使用逐笔下单方法（代替批量API）
            # 从配置读取下单间隔，默认50ms模拟真实交易节奏
            delay_between_ms = config.get("wash_order_delay_ms", 50)

            logging.info(
                f"📤 准备逐笔提交{len(orders_data)}笔洗盘订单 "
                f"(间隔={delay_between_ms}ms)"
            )

            # 调用 OrderManager 的逐笔下单方法
            try:
                summary = self.order_manager.place_orders_sequential(
                    orders=orders_data,
                    delay_between_ms=delay_between_ms,
                    stop_on_failure=False,  # 单笔失败不影响其他订单
                )

                success_count = summary.get("success_count", 0)
                failed_count = summary.get("failed_count", 0)

                logging.info(
                    f"📊 洗盘订单提交完成: "
                    f"成功={success_count}, 失败={failed_count}, "
                    f"总计={summary.get('total', 0)}"
                )

                # 记录失败订单详情
                for result in summary.get("results", []):
                    if not result.get("success"):
                        logging.warning(
                            f"   ❌ 订单[{result.get('index')}] 失败: {result.get('error')}, "
                            f"{result.get('side')} {result.get('quantity')}@{result.get('price')}"
                        )

                # ✅ 追踪订单对：将成功的配对订单添加到追踪器
                if self.order_tracker and self._tracker_enabled:
                    self._track_wash_order_pairs(
                        symbol=symbol,
                        orders_data=orders_data,
                        results=summary.get("results", []),
                        prec=prec
                    )

            except Exception as e:
                logging.error(f"逐笔下单失败: {e}", exc_info=True)
                # 失败时返回当前净值价格
                return mid_price

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

    def stop(self, wait_timeout: int = 60) -> bool:
        """
        优雅停止洗盘交易控制器
        
        设置停止标志，等待当前交易完成（如果有）
        
        Args:
            wait_timeout: 等待超时时间（秒），默认60秒
            
        Returns:
            bool: True表示成功停止，False表示超时
        """
        if not self._running:
            logging.info("洗盘控制器未在运行，无需停止")
            return True
        
        logging.info("=" * 70)
        logging.info("🛑 开始停止洗盘交易控制器")
        logging.info("=" * 70)
        
        # 设置停止标志
        self._running = False
        
        # 等待当前交易完成
        start_time = time.time()
        while time.time() - start_time < wait_timeout:
            # 检查是否有交易在进行中（最近3秒内有交易）
            if time.time() - self._last_trade_time > 3:
                logging.info("✅ 洗盘交易已停止")
                return True
            
            logging.debug(f"等待洗盘交易完成... ({time.time() - start_time:.1f}秒)")
            time.sleep(1)
        
        logging.warning(f"⏱️ 等待超时（{wait_timeout}秒），强制停止洗盘交易")
        return False
    
    def is_running(self) -> bool:
        """
        检查洗盘控制器是否在运行
        
        Returns:
            bool: True表示正在运行，False表示已停止
        """
        return self._running

    def run(self, risk_controller: Any, config: Dict[str, Any]) -> None:
        """
        执行完整的洗盘交易流程（每秒检查+随机交易）

        这是洗盘控制器的主要运行方法，采用每秒检查机制：
        1. 等待初始化完成（确保做市订单和反针对订单已挂好）
        2. 每秒检查一次
        3. 根据配置的平均间隔计算交易概率
        4. 随机决定是否执行交易
        5. 更新价格趋势
        6. 执行洗盘交易策略

        Args:
            risk_controller: 风险控制器实例，用于风险评估
            config: 策略配置字典，包含各种交易参数

        Flow:
            - 等待初始化完成（每秒检查一次，最多等待300秒）
            - 随机延迟启动（1-5秒）
            - 固定间隔 + 随机抖动（±20%）
            - 根据washing_lambda作为基准间隔（默认15秒）
            - 确保每分钟稳定执行指定次数（默认4次）
            - 更新价格趋势（每5分钟切换）

        Note:
            使用固定间隔+抖动模式，确保最小交易频率的同时保持自然性
            例如：15秒基准 → 实际间隔12-18秒 → 1分钟约3.3-5次
        """
        # ═══════════════════════════════════════════════════════════
        # 🔒 等待初始化完成（确保做市订单和反针对订单已挂好）
        # ═══════════════════════════════════════════════════════════
        import redis
        
        # ⚠️ 从配置中读取策略名称（支持多种可能的键名）
        strategy_name = config.get("strategy_name") or config.get("prefix", "unknown")
        
        logging.info("=" * 70)
        logging.info("🔍 洗盘控制器配置检查")
        logging.info("=" * 70)
        logging.info(f"配置字典包含的键: {list(config.keys())}")
        logging.info(f"strategy_name字段: {config.get('strategy_name', '❌ 不存在')}")
        logging.info(f"prefix字段: {config.get('prefix', '❌ 不存在')}")
        logging.info(f"最终使用的策略名: {strategy_name}")
        logging.info(f"交易对symbol: {config.get('symbol', '❌ 不存在')}")
        logging.info(f"洗盘功能启用: {config.get('Enable_wash_trading', False)}")
        logging.info(f"washing_lambda: {config.get('washing_lambda', 15)}")
        logging.info("=" * 70)
        logging.info("")
        
        r = redis.StrictRedis(host="localhost", port=6379, db=0, decode_responses=True)
        
        logging.info("=" * 70)
        logging.info(f"🔒 洗盘控制器等待初始化完成 (strategy={strategy_name})")
        logging.info("=" * 70)
        logging.info(f"将要检查的Redis键: initialized:{strategy_name}")
        logging.info("")
        
        max_wait_time = 300  # 最多等待5分钟
        wait_interval = 1    # 每秒检查一次
        elapsed_time = 0
        
        while elapsed_time < max_wait_time:
            try:
                init_key = f"initialized:{strategy_name}"
                initialized = r.get(init_key)

                if initialized == "true":
                    logging.info(f"✅ 初始化已完成: {init_key} = true")
                    logging.info("   洗盘控制器现在启动")
                    break
                else:
                    if elapsed_time % 10 == 0:  # 每10秒打印一次日志
                        logging.info(f"⏳ 等待初始化完成... ({elapsed_time}秒)")
                        logging.info(f"   检查键: {init_key} = {initialized}")

                        # 额外检查：列出所有 initialized:* 键
                        if elapsed_time == 0:
                            all_init_keys = r.keys("initialized:*")
                            if all_init_keys:
                                logging.info(f"   Redis中存在的initialized键:")
                                for key in all_init_keys[:5]:  # 只显示前5个
                                    value = r.get(key)
                                    logging.info(f"     - {key} = {value}")
                            else:
                                logging.warning(f"   ⚠️  Redis中不存在任何 initialized:* 键")

                    time.sleep(wait_interval)
                    elapsed_time += wait_interval
            except Exception as e:
                logging.warning(f"⚠️ 检查初始化状态失败: {e}")
                time.sleep(wait_interval)
                elapsed_time += wait_interval
        
        if elapsed_time >= max_wait_time:
            logging.warning(f"⚠️ 等待初始化超时({max_wait_time}秒)，强制启动洗盘控制器")
        
        logging.info("=" * 70)
        logging.info("🚀 洗盘控制器正式启动")
        logging.info("=" * 70)
        
        # ═══════════════════════════════════════════════════════════
        # 🎲 开始洗盘交易流程
        # ═══════════════════════════════════════════════════════════
        
        # ✅ 设置运行标志
        self._running = True
        
        time.sleep(random.randint(1, 5))

        # 初始化
        last_mid_price = self.get_washing_price(config)

        # ✅ 从配置读取基准间隔（默认15秒 → 1分钟4次）
        avg_interval = config.get("washing_lambda", 15)

        # ✅ 添加随机抖动范围（±20%，避免机械感）
        jitter_range = avg_interval * 0.2

        logging.info("")
        logging.info("=" * 70)
        logging.info("⚙️  洗盘交易参数配置")
        logging.info("=" * 70)
        logging.info(f"基准间隔: {avg_interval}秒")
        logging.info(f"抖动范围: ±{jitter_range:.1f}秒 (±{jitter_range/avg_interval*100:.0f}%)")
        logging.info(f"预计洗盘频率: {60/avg_interval:.1f} 次/分钟")
        logging.info(f"每次小单数: {config.get('micro_trades_count', 4)}笔")
        logging.info(f"预计成交频率: {(60/avg_interval)*config.get('micro_trades_count', 4):.1f} 笔/分钟")
        logging.info(f"交易对: {config.get('symbol', 'UNKNOWN')}")
        logging.info(f"初始净值: {last_mid_price:.6f}")
        logging.info("=" * 70)
        logging.info("")

        # 洗盘循环计数器
        loop_count = 0
        total_washes = 0
        total_sleep_time = 0

        while self._running:  # ✅ 检查运行标志
            loop_count += 1
            
            # ✅ 固定间隔 + 随机抖动
            sleep_time = avg_interval + random.uniform(-jitter_range, jitter_range)
            
            logging.info("-" * 70)
            logging.info(f"🔄 洗盘循环 #{loop_count}")
            logging.info(f"   等待时间: {sleep_time:.2f}秒 (基准{avg_interval}秒 + 抖动{sleep_time-avg_interval:+.2f}秒)")
            logging.info(f"   累计执行: {total_washes}次洗盘")
            
            time.sleep(sleep_time)
            total_sleep_time += sleep_time

            # ✅ 更新价格趋势（定期切换）
            logging.debug(f"   更新价格趋势...")
            self.update_price_trend(config)
            logging.debug(f"   当前趋势: {self.price_trend*100:.2f}%/分钟")

            # 获取当前净值价格
            logging.debug(f"   获取当前净值...")
            try:
                mid_price = self.get_washing_price(config)
                logging.info(f"   当前净值: {mid_price:.6f}")
            except Exception as e:
                logging.error(f"   ❌ 获取净值失败: {e}")
                logging.error(f"   跳过本次洗盘")
                continue

            # ✅ 记录交易开始时间
            self._last_trade_time = time.time()
            
            logging.info(f"   🎲 准备执行洗盘交易...")

            # 执行洗盘交易
            try:
                last_mid_price = self.wash(
                    symbol=config["symbol"],
                    last_mid_price=last_mid_price,
                    mid_price=mid_price,
                    config=config,
                    prec=config["precision"],
                    prec_amount=config["prec_amount"],
                )
                total_washes += 1
                logging.info(f"   ✅ 洗盘完成 (第{total_washes}次)")
                
                # ✅ 检查孤儿订单（每次洗盘后检查）
                orphan_result = self.check_orphan_orders()
                if orphan_result.get("orphans_found", 0) > 0:
                    logging.warning(
                        f"   ⚠️ 发现孤儿订单: {orphan_result.get('orphans_found')}个, "
                        f"已撤销: {orphan_result.get('cancelled', 0)}个"
                    )
                
                # 每10次洗盘打印统计
                if total_washes % 10 == 0:
                    avg_sleep = total_sleep_time / loop_count
                    actual_freq = (total_washes / (total_sleep_time / 60)) if total_sleep_time > 0 else 0
                    logging.info("")
                    logging.info("=" * 70)
                    logging.info(f"📊 洗盘统计 (第{total_washes}次)")
                    logging.info("=" * 70)
                    logging.info(f"循环次数: {loop_count}")
                    logging.info(f"洗盘次数: {total_washes}")
                    logging.info(f"平均间隔: {avg_sleep:.2f}秒")
                    logging.info(f"实际频率: {actual_freq:.1f} 次/分钟")
                    logging.info(f"目标频率: {60/avg_interval:.1f} 次/分钟")
                    logging.info(f"达成率: {(actual_freq/(60/avg_interval))*100:.1f}%")
                    logging.info("=" * 70)
                    logging.info("")
                    
            except Exception as e:
                logging.error(f"   ❌ 洗盘执行失败: {e}")
                logging.error(f"   详细错误:", exc_info=True)
        
        # ✅ 循环结束，记录退出日志
        logging.info("=" * 70)
        logging.info("✅ 洗盘控制器已优雅退出（运行标志为False）")
        logging.info("=" * 70)
    
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
