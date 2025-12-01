"""
订单簿生成器

设计原则：
1. 价值平衡：买卖双方总金额相等
2. 混合分布：近盘口等差密集，远盘口等比稀疏
3. 每层独立配置订单数和预算
"""

from decimal import Decimal, ROUND_DOWN
from typing import List, Tuple

from ..base import OrderLevel, OrderbookSnapshot
from .config import MaintainerConfig, LayerSpec


class OrderbookGenerator:
    """订单簿生成器 - 价值平衡 + 混合分布"""

    def generate(self, nav: Decimal, config: MaintainerConfig) -> OrderbookSnapshot:
        """
        生成价值平衡的初始订单簿

        Args:
            nav: 当前净值
            config: 维护器配置

        Returns:
            OrderbookSnapshot: 生成的订单簿快照

        核心逻辑：
        1. 近盘口：等差分布（密集）
        2. 远盘口：等比分布（稀疏）
        3. 每层内价值均匀分配
        """
        if not isinstance(nav, Decimal):
            nav = Decimal(str(nav))

        if nav <= Decimal("0"):
            raise ValueError(f"nav must be positive, got {nav}")

        all_bids: List[OrderLevel] = []
        all_asks: List[OrderLevel] = []

        for layer in config.layers:
            layer_budget = config.total_budget * layer.budget_ratio
            bids, asks = self._generate_layer(nav, layer, layer_budget, config)
            all_bids.extend(bids)
            all_asks.extend(asks)

        # 排序：买单降序（高价在前），卖单升序（低价在前）
        all_bids.sort(key=lambda x: x.price, reverse=True)
        all_asks.sort(key=lambda x: x.price)

        return OrderbookSnapshot(
            bids=all_bids,
            asks=all_asks,
            algorithm="maintainer",
            generation_time=0.0,
        )

    def _generate_layer(
        self,
        nav: Decimal,
        layer: LayerSpec,
        budget: Decimal,
        config: MaintainerConfig,
    ) -> Tuple[List[OrderLevel], List[OrderLevel]]:
        """
        生成单层订单（支持等差/等比分布）

        Args:
            nav: 当前净值
            layer: 层配置
            budget: 该层预算
            config: 全局配置

        Returns:
            (bids, asks): 买单和卖单列表
        """
        half_budget = budget / 2
        n_orders = layer.order_count  # 单边订单数

        # 计算价格范围
        if layer.name == "near":
            # 近盘口从 spread/2 开始
            bid_start = nav * (Decimal("1") - config.spread / 2)
            bid_end = nav * (Decimal("1") - layer.distance_range[1])
            ask_start = nav * (Decimal("1") + config.spread / 2)
            ask_end = nav * (Decimal("1") + layer.distance_range[1])
        else:
            # 远盘口从近盘口边界开始
            bid_start = nav * (Decimal("1") - layer.distance_range[0])
            bid_end = nav * (Decimal("1") - layer.distance_range[1])
            ask_start = nav * (Decimal("1") + layer.distance_range[0])
            ask_end = nav * (Decimal("1") + layer.distance_range[1])

        # 根据分布类型生成价格
        if layer.distribution == "arithmetic":
            bid_prices = self._linspace(bid_start, bid_end, n_orders)
            ask_prices = self._linspace(ask_start, ask_end, n_orders)
        else:  # geometric
            bid_prices = self._geomspace(bid_start, bid_end, n_orders)
            ask_prices = self._geomspace(ask_start, ask_end, n_orders)

        # 价值均匀分配：每个订单金额相等
        value_per_order = half_budget / n_orders if n_orders > 0 else Decimal("0")

        # 生成买单
        bids = []
        for p in bid_prices:
            p_rounded = self._round_price(p, config.price_precision)
            if p_rounded <= Decimal("0"):
                continue  # 跳过无效价格

            qty = value_per_order / p_rounded
            qty_rounded = self._round_quantity(qty, config.quantity_precision)

            if qty_rounded <= Decimal("0"):
                continue  # 跳过无效数量

            bids.append(
                OrderLevel(
                    price=p_rounded,
                    quantity=qty_rounded,
                    value=p_rounded * qty_rounded,
                    side="bid",
                    metadata={"layer": layer.name},
                )
            )

        # 生成卖单
        asks = []
        for p in ask_prices:
            p_rounded = self._round_price(p, config.price_precision)
            if p_rounded <= Decimal("0"):
                continue

            qty = value_per_order / p_rounded
            qty_rounded = self._round_quantity(qty, config.quantity_precision)

            if qty_rounded <= Decimal("0"):
                continue

            asks.append(
                OrderLevel(
                    price=p_rounded,
                    quantity=qty_rounded,
                    value=p_rounded * qty_rounded,
                    side="ask",
                    metadata={"layer": layer.name},
                )
            )

        return bids, asks

    def _linspace(
        self, start: Decimal, end: Decimal, n: int
    ) -> List[Decimal]:
        """
        生成等差分布的价格序列

        Args:
            start: 起始价格
            end: 结束价格
            n: 数量

        Returns:
            价格列表
        """
        if n <= 0:
            return []
        if n == 1:
            return [start]

        step = (end - start) / (n - 1)
        return [start + step * i for i in range(n)]

    def _geomspace(
        self, start: Decimal, end: Decimal, n: int
    ) -> List[Decimal]:
        """
        生成等比分布的价格序列

        Args:
            start: 起始价格
            end: 结束价格
            n: 数量

        Returns:
            价格列表

        注意：远端间距逐渐增大，节省档位
        """
        if n <= 0:
            return []
        if n == 1:
            return [start]

        # 边界检查
        if start <= Decimal("0") or end <= Decimal("0"):
            # 降级为等差分布
            return self._linspace(start, end, n)

        # 计算公比: ratio = (end / start) ^ (1/(n-1))
        # 使用 float 进行幂运算，然后转回 Decimal
        ratio_float = (float(end) / float(start)) ** (1.0 / (n - 1))
        ratio = Decimal(str(ratio_float))

        result = []
        current = start
        for i in range(n):
            result.append(current)
            current = current * ratio

        return result

    def _round_price(self, price: Decimal, precision: int) -> Decimal:
        """
        四舍五入价格

        Args:
            price: 原始价格
            precision: 小数位数

        Returns:
            四舍五入后的价格
        """
        quantize_str = "0." + "0" * precision
        return price.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)

    def _round_quantity(self, quantity: Decimal, precision: int) -> Decimal:
        """
        四舍五入数量

        Args:
            quantity: 原始数量
            precision: 小数位数

        Returns:
            四舍五入后的数量
        """
        quantize_str = "0." + "0" * precision
        return quantity.quantize(Decimal(quantize_str), rounding=ROUND_DOWN)
