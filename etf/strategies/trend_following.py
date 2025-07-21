"""
趋势跟随策略
基于净值变化识别趋势，动态调整库存偏向
"""

import logging
import numpy as np
import pandas as pd
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List, Tuple
import redis
import json

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class TrendFollower:
    """趋势跟随策略"""

    def __init__(self, redis_host: str = "localhost", redis_port: int = 6379):
        """
        初始化趋势跟随策略
        Args:
            redis_host: Redis服务器地址
            redis_port: Redis端口
        """
        # Redis连接
        self.r = redis.Redis(host=redis_host, port=redis_port, db=0)

        # 策略参数
        self.params = {
            "ema_short": 10,  # 短期EMA周期（分钟）
            "ema_long": 30,  # 长期EMA周期（分钟）
            "rsi_period": 14,  # RSI周期
            "trend_threshold": 0.02,  # 趋势识别阈值（2%）
            "max_inventory_bias": 0.5,  # 最大库存偏向（±50%）
        }

        # 净值历史缓存
        self.net_value_history = {}

        # 技术指标缓存
        self.indicators = {}

        # 库存偏向历史
        self.inventory_bias_history = []

    def update_net_value(self, symbol: str, net_value: float):
        """
        更新净值数据
        Args:
            symbol: 交易对
            net_value: 最新净值
        """
        try:
            # 初始化历史记录
            if symbol not in self.net_value_history:
                self.net_value_history[symbol] = []

            # 添加新数据点
            self.net_value_history[symbol].append({
                "timestamp": datetime.now(),
                "value": net_value,
            })

            # 保留最近2小时的数据
            cutoff_time = datetime.now() - timedelta(hours=2)
            self.net_value_history[symbol] = [
                point
                for point in self.net_value_history[symbol]
                if point["timestamp"] > cutoff_time
            ]

            # 同时更新到Redis（供其他进程使用）
            redis_key = f"net_value_history:{symbol}"
            self.r.lpush(
                redis_key,
                json.dumps({
                    "timestamp": datetime.now().isoformat(),
                    "value": net_value,
                }),
            )
            self.r.ltrim(redis_key, 0, 1000)  # 保留最近1000个数据点

        except Exception as e:
            logging.error(f"更新净值失败: {e}")

    def calculate_trend_signal(self, symbol: str) -> Dict[str, Any]:
        """
        计算趋势信号
        Returns:
            包含趋势方向、强度和建议库存偏向的字典
        """
        try:
            # 获取净值历史
            history = self.net_value_history.get(symbol, [])
            if len(history) < 20:
                return {
                    "trend": "neutral",
                    "strength": 0.0,
                    "inventory_bias": 1.0,
                    "indicators": {},
                }

            # 转换为DataFrame
            df = pd.DataFrame(history)
            df.set_index("timestamp", inplace=True)

            # 计算技术指标
            indicators = self._calculate_indicators(df)

            # 判断趋势
            trend_signal = self._determine_trend(indicators)

            # 计算库存偏向
            inventory_bias = self._calculate_inventory_bias(trend_signal)

            # 记录历史
            self._record_bias_history(symbol, inventory_bias, trend_signal)

            result = {
                "trend": trend_signal["trend"],
                "strength": trend_signal["strength"],
                "inventory_bias": inventory_bias,
                "indicators": indicators,
                "confidence": trend_signal.get("confidence", 0.5),
            }

            logging.info(
                f"趋势信号: {result['trend']}, "
                f"强度: {result['strength']:.2f}, "
                f"库存偏向: {result['inventory_bias']:.2f}"
            )

            return result

        except Exception as e:
            logging.error(f"计算趋势信号失败: {e}")
            return {
                "trend": "neutral",
                "strength": 0.0,
                "inventory_bias": 1.0,
                "indicators": {},
            }

    def _calculate_indicators(self, df: pd.DataFrame) -> Dict[str, float]:
        """计算技术指标"""
        try:
            # 重采样到1分钟
            df_1min = df.resample("1T").last().ffill()
            values = df_1min["value"].values

            if len(values) < self.params["ema_long"]:
                return {}

            # 计算EMA
            ema_short = self._calculate_ema(values, self.params["ema_short"])
            ema_long = self._calculate_ema(values, self.params["ema_long"])

            # 计算RSI
            rsi = self._calculate_rsi(values, self.params["rsi_period"])

            # 计算MACD
            macd, signal = self._calculate_macd(values)

            # 计算价格变化率
            price_change_1h = (
                (values[-1] - values[-60]) / values[-60] if len(values) >= 60 else 0
            )
            price_change_15m = (
                (values[-1] - values[-15]) / values[-15] if len(values) >= 15 else 0
            )

            indicators = {
                "ema_short": ema_short[-1],
                "ema_long": ema_long[-1],
                "ema_diff": (ema_short[-1] - ema_long[-1]) / ema_long[-1],
                "rsi": rsi,
                "macd": macd,
                "macd_signal": signal,
                "price_change_1h": price_change_1h,
                "price_change_15m": price_change_15m,
                "current_price": values[-1],
            }

            # 缓存指标
            self.indicators[df.index[-1]] = indicators

            return indicators

        except Exception as e:
            logging.error(f"计算技术指标失败: {e}")
            return {}

    def _calculate_ema(self, values: np.ndarray, period: int) -> np.ndarray:
        """计算指数移动平均"""
        alpha = 2 / (period + 1)
        ema = np.zeros_like(values)
        ema[0] = values[0]

        for i in range(1, len(values)):
            ema[i] = alpha * values[i] + (1 - alpha) * ema[i - 1]

        return ema

    def _calculate_rsi(self, values: np.ndarray, period: int) -> float:
        """计算RSI指标"""
        if len(values) < period + 1:
            return 50.0

        deltas = np.diff(values)
        seed = deltas[: period + 1]
        up = seed[seed >= 0].sum() / period
        down = -seed[seed < 0].sum() / period

        if down == 0:
            return 100.0

        rs = up / down
        rsi = 100 - (100 / (1 + rs))

        return rsi

    def _calculate_macd(self, values: np.ndarray) -> Tuple[float, float]:
        """计算MACD指标"""
        if len(values) < 26:
            return 0.0, 0.0

        ema_12 = self._calculate_ema(values, 12)
        ema_26 = self._calculate_ema(values, 26)

        macd = ema_12[-1] - ema_26[-1]
        signal = self._calculate_ema(ema_12 - ema_26, 9)[-1]

        return macd, signal

    def _determine_trend(self, indicators: Dict[str, float]) -> Dict[str, Any]:
        """判断趋势方向和强度"""
        if not indicators:
            return {"trend": "neutral", "strength": 0.0, "confidence": 0.0}

        # 趋势得分系统
        score = 0.0
        confidence = 0.0

        # EMA交叉信号（权重：30%）
        ema_diff = indicators.get("ema_diff", 0)
        if abs(ema_diff) > 0.001:
            score += 30 * np.sign(ema_diff) * min(abs(ema_diff) / 0.02, 1.0)
            confidence += 0.3

        # RSI信号（权重：20%）
        rsi = indicators.get("rsi", 50)
        if rsi > 70:
            score += 20
            confidence += 0.2
        elif rsi < 30:
            score -= 20
            confidence += 0.2
        elif 40 < rsi < 60:
            confidence += 0.1

        # MACD信号（权重：20%）
        macd = indicators.get("macd", 0)
        macd_signal = indicators.get("macd_signal", 0)
        if macd > macd_signal:
            score += 20 * min((macd - macd_signal) / 0.01, 1.0)
            confidence += 0.2
        else:
            score -= 20 * min((macd_signal - macd) / 0.01, 1.0)
            confidence += 0.2

        # 短期价格变化（权重：30%）
        price_change_15m = indicators.get("price_change_15m", 0)
        if abs(price_change_15m) > 0.005:
            score += (
                30 * np.sign(price_change_15m) * min(abs(price_change_15m) / 0.03, 1.0)
            )
            confidence += 0.3

        # 归一化得分
        score = max(-100, min(100, score))

        # 确定趋势
        if score > 30:
            trend = "bullish"
        elif score < -30:
            trend = "bearish"
        else:
            trend = "neutral"

        return {
            "trend": trend,
            "strength": abs(score) / 100.0,
            "score": score,
            "confidence": min(confidence, 1.0),
        }

    def _calculate_inventory_bias(self, trend_signal: Dict[str, Any]) -> float:
        """
        计算库存偏向
        Returns:
            库存偏向系数（0.5-1.5，1.0为中性）
        """
        trend = trend_signal["trend"]
        strength = trend_signal["strength"]
        confidence = trend_signal.get("confidence", 0.5)

        # 基础偏向
        if trend == "bullish":
            base_bias = 1.0 + self.params["max_inventory_bias"] * strength
        elif trend == "bearish":
            base_bias = 1.0 - self.params["max_inventory_bias"] * strength
        else:
            base_bias = 1.0

        # 根据置信度调整
        bias = 1.0 + (base_bias - 1.0) * confidence

        # 限制范围
        min_bias = 1.0 - self.params["max_inventory_bias"]
        max_bias = 1.0 + self.params["max_inventory_bias"]
        bias = max(min_bias, min(max_bias, bias))

        return bias

    def _record_bias_history(self, symbol: str, bias: float, signal: Dict[str, Any]):
        """记录库存偏向历史"""
        self.inventory_bias_history.append({
            "timestamp": datetime.now(),
            "symbol": symbol,
            "bias": bias,
            "trend": signal["trend"],
            "strength": signal["strength"],
            "score": signal.get("score", 0),
        })

        # 保留最近1000条记录
        if len(self.inventory_bias_history) > 1000:
            self.inventory_bias_history = self.inventory_bias_history[-1000:]

    def get_strategy_stats(self) -> Dict[str, Any]:
        """获取策略统计信息"""
        if not self.inventory_bias_history:
            return {}

        recent_history = self.inventory_bias_history[-100:]
        biases = [h["bias"] for h in recent_history]

        # 统计趋势分布
        trend_counts = {"bullish": 0, "bearish": 0, "neutral": 0}
        for h in recent_history:
            trend_counts[h["trend"]] += 1

        return {
            "avg_bias": np.mean(biases),
            "std_bias": np.std(biases),
            "max_bias": np.max(biases),
            "min_bias": np.min(biases),
            "trend_distribution": trend_counts,
            "total_signals": len(self.inventory_bias_history),
        }

    def update_params(self, new_params: Dict[str, Any]):
        """更新策略参数"""
        self.params.update(new_params)
        logging.info(f"策略参数更新: {self.params}")

    def get_net_value_from_redis(
        self, symbol: str, hours: int = 1
    ) -> List[Dict[str, Any]]:
        """从Redis获取历史净值数据"""
        try:
            redis_key = f"net_value_history:{symbol}"
            data = self.r.lrange(redis_key, 0, hours * 60)  # 假设每分钟一个数据点

            history = []
            for item in data:
                try:
                    point = json.loads(item)
                    point["timestamp"] = datetime.fromisoformat(point["timestamp"])
                    history.append(point)
                except:
                    continue

            # 按时间排序
            history.sort(key=lambda x: x["timestamp"])

            # 更新本地缓存
            self.net_value_history[symbol] = history

            return history

        except Exception as e:
            logging.error(f"从Redis获取净值历史失败: {e}")
            return []
