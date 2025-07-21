"""
动态价差管理策略
根据市场状态和真实交易量动态调整价差
"""

import logging
import numpy as np
from datetime import datetime, timedelta
from typing import Dict, Any, Optional, List
import asyncio

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class DynamicSpreadManager:
    """动态价差管理器"""

    def __init__(self, base_spread: float = 0.01, order_manager=None):
        """
        初始化动态价差管理器
        Args:
            base_spread: 基础价差（如0.01表示1%）
            order_manager: 订单管理器实例
        """
        self.base_spread = base_spread
        self.order_manager = order_manager

        # 价差调整参数
        self.min_spread = base_spread * 0.5  # 最小价差为基础价差的50%
        self.max_spread = base_spread * 3.0  # 最大价差为基础价差的300%

        # 市场状态缓存
        self.volatility_cache = {}
        self.volume_cache = {}
        self.spread_history = []

        # 调整系数
        self.factors = {
            "real_volume": 0.3,  # 真实交易量权重
            "volatility": 0.3,  # 波动率权重
            "time_of_day": 0.2,  # 时段权重
            "inventory": 0.2,  # 库存权重
        }

    async def calculate_dynamic_spread(
        self, symbol: str, current_price: float, inventory_ratio: float = 0.5
    ) -> float:
        """
        计算动态价差
        Args:
            symbol: 交易对
            current_price: 当前价格
            inventory_ratio: 库存比例（0-1，0.5表示中性）
        Returns:
            调整后的价差
        """
        try:
            # 1. 获取真实交易量比例
            real_volume_factor = await self._calculate_real_volume_factor(symbol)

            # 2. 计算波动率因子
            volatility_factor = self._calculate_volatility_factor(symbol, current_price)

            # 3. 计算时段因子
            time_factor = self._calculate_time_factor()

            # 4. 计算库存因子
            inventory_factor = self._calculate_inventory_factor(inventory_ratio)

            # 5. 综合计算动态价差
            weighted_factor = (
                self.factors["real_volume"] * real_volume_factor
                + self.factors["volatility"] * volatility_factor
                + self.factors["time_of_day"] * time_factor
                + self.factors["inventory"] * inventory_factor
            )

            # 6. 应用调整系数
            dynamic_spread = self.base_spread * weighted_factor

            # 7. 限制在最大最小值范围内
            dynamic_spread = max(self.min_spread, min(self.max_spread, dynamic_spread))

            # 8. 记录历史
            self._record_spread_history(
                symbol,
                dynamic_spread,
                {
                    "real_volume_factor": real_volume_factor,
                    "volatility_factor": volatility_factor,
                    "time_factor": time_factor,
                    "inventory_factor": inventory_factor,
                },
            )

            logging.info(
                f"动态价差计算: 基础={self.base_spread:.4f}, "
                f"调整后={dynamic_spread:.4f}, "
                f"因子=[真实交易:{real_volume_factor:.2f}, "
                f"波动:{volatility_factor:.2f}, "
                f"时段:{time_factor:.2f}, "
                f"库存:{inventory_factor:.2f}]"
            )

            return dynamic_spread

        except Exception as e:
            logging.error(f"计算动态价差失败: {e}")
            return self.base_spread

    async def _calculate_real_volume_factor(self, symbol: str) -> float:
        """
        计算真实交易量因子
        真实交易量越多，价差越小（吸引更多交易）
        """
        try:
            if self.order_manager:
                real_volume_ratio = await self.order_manager.get_real_volume_ratio(
                    symbol
                )

                # 缓存结果
                self.volume_cache[symbol] = {
                    "ratio": real_volume_ratio,
                    "timestamp": datetime.now(),
                }

                # 真实交易量因子：
                # 0% 真实交易 -> 系数 1.5（扩大价差）
                # 30% 真实交易 -> 系数 1.0（正常价差）
                # 60%+ 真实交易 -> 系数 0.7（收窄价差）
                if real_volume_ratio < 0.1:
                    return 1.5
                elif real_volume_ratio < 0.3:
                    return 1.0 + 0.5 * (0.3 - real_volume_ratio) / 0.2
                elif real_volume_ratio < 0.6:
                    return 1.0 - 0.3 * (real_volume_ratio - 0.3) / 0.3
                else:
                    return 0.7

            return 1.0

        except Exception as e:
            logging.error(f"计算真实交易量因子失败: {e}")
            return 1.0

    def _calculate_volatility_factor(self, symbol: str, current_price: float) -> float:
        """
        计算波动率因子
        波动率越高，价差越大（补偿风险）
        """
        try:
            # 获取缓存的价格历史
            if symbol not in self.volatility_cache:
                self.volatility_cache[symbol] = {
                    "prices": [],
                    "last_update": datetime.now(),
                }

            # 添加当前价格
            cache = self.volatility_cache[symbol]
            cache["prices"].append(current_price)

            # 保留最近100个价格点
            if len(cache["prices"]) > 100:
                cache["prices"] = cache["prices"][-100:]

            # 计算波动率
            if len(cache["prices"]) >= 10:
                prices = np.array(cache["prices"])
                returns = np.diff(np.log(prices))
                volatility = np.std(returns)

                # 波动率因子：
                # 低波动（<1%） -> 系数 0.8
                # 正常波动（1-3%） -> 系数 1.0
                # 高波动（>5%） -> 系数 1.5
                if volatility < 0.01:
                    return 0.8
                elif volatility < 0.03:
                    return 0.8 + 0.2 * (volatility - 0.01) / 0.02
                elif volatility < 0.05:
                    return 1.0 + 0.5 * (volatility - 0.03) / 0.02
                else:
                    return 1.5

            return 1.0

        except Exception as e:
            logging.error(f"计算波动率因子失败: {e}")
            return 1.0

    def _calculate_time_factor(self) -> float:
        """
        计算时段因子
        根据交易时段调整价差
        """
        try:
            # 获取当前UTC时间
            now = datetime.utcnow()
            hour = now.hour

            # 时段因子：
            # 亚洲时段 (00:00-08:00 UTC) -> 系数 0.9
            # 欧洲时段 (08:00-16:00 UTC) -> 系数 1.0
            # 美洲时段 (16:00-24:00 UTC) -> 系数 1.1
            if 0 <= hour < 8:
                return 0.9  # 亚洲时段，活跃度高
            elif 8 <= hour < 16:
                return 1.0  # 欧洲时段
            else:
                return 1.1  # 美洲时段

        except Exception as e:
            logging.error(f"计算时段因子失败: {e}")
            return 1.0

    def _calculate_inventory_factor(self, inventory_ratio: float) -> float:
        """
        计算库存因子
        库存偏离中性越多，价差越大
        """
        try:
            # 库存因子：
            # 中性库存 (0.4-0.6) -> 系数 1.0
            # 轻微偏离 (0.3-0.4 或 0.6-0.7) -> 系数 1.1
            # 严重偏离 (<0.3 或 >0.7) -> 系数 1.3
            deviation = abs(inventory_ratio - 0.5)

            if deviation < 0.1:
                return 1.0
            elif deviation < 0.2:
                return 1.0 + 1.0 * deviation
            else:
                return 1.3

        except Exception as e:
            logging.error(f"计算库存因子失败: {e}")
            return 1.0

    def _record_spread_history(
        self, symbol: str, spread: float, factors: Dict[str, float]
    ):
        """记录价差历史"""
        self.spread_history.append({
            "timestamp": datetime.now(),
            "symbol": symbol,
            "spread": spread,
            "factors": factors,
        })

        # 保留最近1000条记录
        if len(self.spread_history) > 1000:
            self.spread_history = self.spread_history[-1000:]

    def get_spread_stats(self) -> Dict[str, Any]:
        """获取价差统计信息"""
        if not self.spread_history:
            return {}

        spreads = [record["spread"] for record in self.spread_history[-100:]]

        return {
            "current_base_spread": self.base_spread,
            "avg_spread": np.mean(spreads),
            "min_spread": np.min(spreads),
            "max_spread": np.max(spreads),
            "std_spread": np.std(spreads),
            "total_adjustments": len(self.spread_history),
        }

    def update_base_spread(self, new_base_spread: float):
        """更新基础价差"""
        self.base_spread = new_base_spread
        self.min_spread = new_base_spread * 0.5
        self.max_spread = new_base_spread * 3.0
        logging.info(f"基础价差更新为: {new_base_spread:.4f}")

    def adjust_factors(self, new_factors: Dict[str, float]):
        """调整权重因子"""
        total = sum(new_factors.values())
        if abs(total - 1.0) > 0.01:
            logging.warning(f"权重因子总和不为1: {total}")

        self.factors.update(new_factors)
        logging.info(f"权重因子更新: {self.factors}")
