"""
自然订单簿算法

基于真实交易所盘口特征设计：
- 三区分层价格分布（近端密集、远端稀疏）
- 幂律+对数正态混合数量分布
- 订单墙、空洞、整数聚集效应
"""

import time
import numpy as np
from decimal import Decimal
from typing import List, Tuple

from .base import (
    OrderbookAlgorithm,
    OrderbookConfig,
    OrderLevel,
    OrderbookSnapshot,
    register_algorithm,
)


@register_algorithm("natural")
class NaturalAlgorithm(OrderbookAlgorithm):
    """自然盘口算法

    支持：
    - 档位范围：1000-1000000
    - 自然度级别：low/medium/high/ultra
    - 预算自适应
    """

    @property
    def algorithm_name(self) -> str:
        return "natural"

    @property
    def supported_layer_range(self) -> Tuple[int, int]:
        return (10, 1_000_000)  # 支持10-1,000,000档

    def validate_config(self):
        """验证配置"""
        layer = self.config.layer
        min_layer, max_layer = self.supported_layer_range

        if not (min_layer <= layer <= max_layer):
            raise ValueError(
                f"Natural algorithm supports {min_layer}-{max_layer} layers, "
                f"got {layer}"
            )

        # 大档位警告
        if layer > 10_000:
            import warnings
            warnings.warn(
                f"Large layer count ({layer}) may impact performance. "
                f"Estimated generation time: ~{layer/1000:.1f}s"
            )

    def generate_snapshot(self) -> OrderbookSnapshot:
        """生成自然订单簿快照"""
        start_time = time.time()

        # 获取自然度级别
        naturalness = self.config.extra_params.get("naturalness", "high")

        # 计算买卖档位分配
        n = self.config.layer
        n_bid = n // 2
        n_ask = n - n_bid

        # 记录关键参数（调试用）
        import logging
        logging.info(f"📊 订单簿生成参数: 净值={self.config.mid_price:.6f}, spread={self.config.bid_ask_spread:.4f}")
        logging.info(f"   预期买1: {self.config.mid_price * (1 - self.config.bid_ask_spread/2):.6f}")
        logging.info(f"   预期卖1: {self.config.mid_price * (1 + self.config.bid_ask_spread/2):.6f}")

        # 生成价格
        bid_prices = self._generate_prices(n_bid, side='bid')
        ask_prices = self._generate_prices(n_ask, side='ask')
        
        # ✅ 价格边界检查（关键修复）
        mid_price = self.config.mid_price
        spread = self.config.bid_ask_spread
        
        # 检查买盘价格是否在净值下方
        max_bid_price = float(np.max(bid_prices))
        expected_max_bid = mid_price * (1 - spread / 2)
        if max_bid_price > mid_price:
            logging.error(f"❌ 买盘价格异常：最高买价({max_bid_price:.6f}) > 净值({mid_price:.6f})")
            logging.error(f"   预期最高买价: {expected_max_bid:.6f}")
        
        # 检查卖盘价格是否在净值上方
        min_ask_price = float(np.min(ask_prices))
        expected_min_ask = mid_price * (1 + spread / 2)
        if min_ask_price < mid_price:
            logging.error(f"❌ 卖盘价格异常：最低卖价({min_ask_price:.6f}) < 净值({mid_price:.6f})")
            logging.error(f"   预期最低卖价: {expected_min_ask:.6f}")
            logging.error(f"   卖盘价格范围: {min_ask_price:.6f} - {float(np.max(ask_prices)):.6f}")
            logging.error(f"   买盘价格范围: {float(np.min(bid_prices)):.6f} - {max_bid_price:.6f}")
            
            # 🔧 强制修正卖盘价格（应急措施）
            logging.warning(f"🔧 强制修正卖盘价格到合理范围...")
            ask_prices = ask_prices * (expected_min_ask / min_ask_price)
            min_ask_price = float(np.min(ask_prices))  # ✅ 更新变量！
            logging.warning(f"   修正后最低卖价: {min_ask_price:.6f}")
        
        # 检查盘口是否交叉
        if max_bid_price >= min_ask_price:
            logging.error(f"❌ 盘口交叉：买1({max_bid_price:.6f}) >= 卖1({min_ask_price:.6f})")
            raise ValueError(f"盘口交叉错误：买1({max_bid_price:.6f}) >= 卖1({min_ask_price:.6f})")
        
        logging.info(f"✅ 价格范围验证通过:")
        logging.info(f"   买盘: {float(np.min(bid_prices)):.6f} - {max_bid_price:.6f}")
        logging.info(f"   卖盘: {min_ask_price:.6f} - {float(np.max(ask_prices)):.6f}")

        # 生成数量
        bid_quantities = self._generate_quantities(bid_prices, naturalness)
        ask_quantities = self._generate_quantities(ask_prices, naturalness)

        # 应用特效
        if naturalness in ['high', 'ultra']:
            bid_quantities = self._apply_effects(bid_prices, bid_quantities, naturalness)
            ask_quantities = self._apply_effects(ask_prices, ask_quantities, naturalness)

        # 重新归一化到预算（关键修复）
        bid_quantities = self._normalize_to_budget(bid_prices, bid_quantities, 'bid')
        ask_quantities = self._normalize_to_budget(ask_prices, ask_quantities, 'ask')

        # 构造订单
        bids = self._build_levels(bid_prices, bid_quantities, 'bid')
        asks = self._build_levels(ask_prices, ask_quantities, 'ask')

        generation_time = time.time() - start_time

        return OrderbookSnapshot(
            bids=bids,
            asks=asks,
            algorithm=self.algorithm_name,
            generation_time=generation_time
        )

    def _generate_prices(self, n: int, side: str) -> np.ndarray:
        """三区分层价格生成

        Near Zone (10-20%档位): 0-0.5%，线性密集
        Mid Zone (20-30%档位): 0.5%-2%，对数间距
        Far Zone (50-70%档位): 2%-5%，整数聚类
        """
        mid = self.config.mid_price
        spread = self.config.bid_ask_spread

        # 动态分区比例（档位越多，远端占比越大）
        if n < 100:
            near_ratio, mid_ratio = 0.3, 0.3
        elif n < 1000:
            near_ratio, mid_ratio = 0.2, 0.3
        elif n < 10000:
            near_ratio, mid_ratio = 0.1, 0.2
        else:
            near_ratio, mid_ratio = 0.02, 0.1

        n_near = max(1, int(n * near_ratio))
        n_mid = max(1, int(n * mid_ratio))
        n_far = max(1, n - n_near - n_mid)

        # 价格基准
        base = mid * (1 - spread / 2) if side == 'bid' else mid * (1 + spread / 2)

        # Near区：线性密集（0.05%间距）
        if side == 'bid':
            near_prices = base * (1 - np.linspace(0, 0.005, n_near))
        else:
            near_prices = base * (1 + np.linspace(0, 0.005, n_near))

        # Mid区：对数间距
        mid_start = near_prices[-1]
        if side == 'bid':
            mid_end = mid_start * 0.98  # -2%
            mid_prices = np.geomspace(mid_start, mid_end, n_mid)
        else:
            mid_end = mid_start * 1.02  # +2%
            mid_prices = np.geomspace(mid_start, mid_end, n_mid)

        # Far区：整数聚类
        far_start = mid_prices[-1]
        if side == 'bid':
            far_end = far_start * 0.95  # -5%
        else:
            far_end = far_start * 1.05  # +5%

        far_prices = self._generate_clustered_prices(far_start, far_end, n_far)

        # 合并
        prices = np.concatenate([near_prices, mid_prices, far_prices])

        # 价格微调（±0.03%噪声）
        noise = np.random.normal(1, 0.0003, len(prices))
        prices *= noise

        # 确保单调性
        if side == 'bid':
            prices = np.sort(prices)[::-1]  # 降序
        else:
            prices = np.sort(prices)  # 升序

        return prices

    def _generate_quantities(
        self,
        prices: np.ndarray,
        naturalness: str
    ) -> np.ndarray:
        """幂律+对数正态混合数量生成"""
        n = len(prices)
        budget = self.config.total_budget / 2  # 单边预算

        # 基准金额
        avg_value = budget / n
        min_value = avg_value * 0.5

        # 根据自然度选择分布策略
        if naturalness == 'low':
            # 简单对数正态（70%自然度）
            ratios = np.random.lognormal(0, 0.5, n)

        elif naturalness == 'medium':
            # 混合分布（85%自然度）
            small_n = int(n * 0.70)
            medium_n = int(n * 0.25)
            large_n = n - small_n - medium_n

            small_ratios = np.random.lognormal(np.log(0.5), 0.5, small_n)
            medium_ratios = np.random.lognormal(np.log(2.0), 0.6, medium_n)
            large_ratios = np.random.pareto(2.5, large_n) * 10 + 10

            ratios = np.concatenate([small_ratios, medium_ratios, large_ratios])
            np.random.shuffle(ratios)

        else:  # high / ultra
            # 完整幂律分布（95%+自然度）
            small_n = int(n * 0.75)
            medium_n = int(n * 0.20)
            large_n = n - small_n - medium_n

            small_ratios = np.random.lognormal(np.log(0.5), 0.5, small_n)
            medium_ratios = np.random.lognormal(np.log(2.0), 0.6, medium_n)
            large_ratios = np.random.pareto(2.5, large_n) * 10 + 10

            ratios = np.concatenate([small_ratios, medium_ratios, large_ratios])
            np.random.shuffle(ratios)

        # 归一化（确保总预算）
        ratios = ratios / ratios.sum() * n

        # 计算数量（金额 / 价格）
        values = ratios * avg_value
        quantities = values / prices

        return quantities

    def _apply_effects(
        self,
        prices: np.ndarray,
        quantities: np.ndarray,
        naturalness: str
    ) -> np.ndarray:
        """应用特效：墙、聚集、噪声"""
        n = len(quantities)

        # 订单墙概率
        wall_prob = {'medium': 0.03, 'high': 0.06, 'ultra': 0.08}.get(naturalness, 0.06)

        # 订单墙
        wall_mask = np.random.random(n) < wall_prob
        if wall_mask.any():
            wall_multipliers = np.random.uniform(10, 20, wall_mask.sum())
            quantities[wall_mask] *= wall_multipliers

        # 整数聚集
        clustering_boost = {'medium': 2.0, 'high': 3.0, 'ultra': 5.0}.get(naturalness, 3.0)

        for i, p in enumerate(prices):
            if abs(p % 1000) < 1:  # 整千
                quantities[i] *= np.random.uniform(clustering_boost, clustering_boost + 2)
            elif abs(p % 100) < 1:  # 整百
                quantities[i] *= np.random.uniform(1.5, 2.0)

        # 数量噪声（±10%）
        noise = np.random.normal(1, 0.10, n)
        quantities *= noise

        # 确保非负
        quantities = np.abs(quantities)

        return quantities

    def _normalize_to_budget(
        self,
        prices: np.ndarray,
        quantities: np.ndarray,
        side: str
    ) -> np.ndarray:
        """归一化数量到预算约束
        
        确保单边总金额 = total_budget / 2
        """
        budget = self.config.total_budget / 2  # 单边预算
        
        # 计算当前总金额
        current_values = prices * quantities
        current_total = current_values.sum()
        
        # 缩放因子
        if current_total > 0:
            scale_factor = budget / current_total
            quantities = quantities * scale_factor
        
        return quantities

    def _get_clustering_step(self, price: float) -> float:
        """根据价格范围选择合适的聚类粒度
        
        Args:
            price: 价格
            
        Returns:
            聚类粒度（如 0.01, 1, 100 等）
        """
        if price < 0.1:
            return 0.001  # 小数点后3位
        elif price < 1:
            return 0.01   # 小数点后2位
        elif price < 10:
            return 0.1    # 小数点后1位
        elif price < 100:
            return 1      # 整数位
        elif price < 1000:
            return 10     # 整十位
        else:
            return 100    # 整百位
    
    def _generate_clustered_prices(
        self,
        start: float,
        end: float,
        n: int
    ) -> np.ndarray:
        """智能整数聚类价格生成
        
        根据价格范围自动选择合适的聚类粒度：
        - 低价币（< 1）：聚类到 0.01 或 0.001
        - 中价币（1-1000）：聚类到 1 或 10
        - 高价币（> 1000）：聚类到 100 或 1000
        """
        # 基础对数分布
        base_prices = np.geomspace(start, end, n)

        # 向合适粒度的价位聚拢（10%概率）
        for i in range(n):
            if np.random.random() < 0.1:
                price = base_prices[i]
                # 根据价格选择聚类粒度
                step = self._get_clustering_step(price)
                
                # 找最近的目标价位
                round_price = round(price / step) * step
                
                # ✅ 验证聚类结果合理性
                if round_price > 0 and abs(round_price - price) / price < 0.5:
                    # 向其靠拢（避免完全对齐，保持自然度）
                    base_prices[i] = (price + round_price) / 2
                # 否则保持原价格不变

        return base_prices

    def _build_levels(
        self,
        prices: np.ndarray,
        quantities: np.ndarray,
        side: str
    ) -> List[OrderLevel]:
        """构造订单档位列表"""
        levels = []

        for price, quantity in zip(prices, quantities):
            # 精度处理
            price_dec = Decimal(str(round(price, self.config.price_precision)))
            quantity_dec = Decimal(str(round(quantity, self.config.quantity_precision)))
            value_dec = price_dec * quantity_dec

            levels.append(OrderLevel(
                price=price_dec,
                quantity=quantity_dec,
                value=value_dec,
                side=side
            ))

        return levels
