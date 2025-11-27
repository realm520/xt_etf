"""
分层订单簿算法

核心思想：
- 将订单簿分为3层：近盘口、过渡区、远盘口
- 不同层级有不同的更新频率和价格触发阈值
- 近盘口频繁更新跟随净值，远盘口较少更新

设计目标：
- 减少API调用次数（70%+优化）
- 保持盘口流动性和连续性
- 降低交易成本和滑点
"""

from typing import Dict, List, Tuple, Optional, Any
from decimal import Decimal
from dataclasses import dataclass, field
import time
import logging
import numpy as np

from etf.orderbook.base import (
    OrderbookAlgorithm,
    OrderbookConfig,
    OrderbookSnapshot,
    OrderLevel,
    OrderbookDiff,
    OrderOperation,
    register_algorithm,
)


@dataclass
class LayerConfig:
    """单层配置"""

    # 距离净值的范围
    distance_threshold: Optional[float] = None  # 单阈值（近盘口）
    distance_range: Optional[Tuple[float, float]] = None  # 范围（过渡区、远盘口）

    # 层级订单数量
    layer_count: int = 50  # 该层总档位数（买卖各一半）

    # 价格容差（匹配现有订单时的容差）
    price_tolerance: float = 0.001  # 0.1%

    # 更新控制
    update_interval: float = 30.0  # 最小更新间隔（秒）
    price_change_trigger: float = 0.002  # 价格变化触发阈值（0.2%）

    # 预算分配比例
    budget_ratio: float = 0.3  # 该层占总预算的比例

    def __post_init__(self):
        """验证配置"""
        if self.distance_threshold is None and self.distance_range is None:
            raise ValueError("Must specify either distance_threshold or distance_range")

        if self.distance_threshold is not None and self.distance_range is not None:
            raise ValueError("Cannot specify both distance_threshold and distance_range")


@dataclass
class LayeredOrderbookConfig(OrderbookConfig):
    """分层订单簿配置（扩展基础配置）"""

    # 三层配置
    near_book: LayerConfig = field(default_factory=lambda: LayerConfig(
        distance_threshold=0.005,  # 0.5%
        layer_count=50,
        price_tolerance=0.001,
        update_interval=30,
        price_change_trigger=0.002,
        budget_ratio=0.3,
    ))

    transition_zone: LayerConfig = field(default_factory=lambda: LayerConfig(
        distance_range=(0.005, 0.02),  # 0.5%-2%
        layer_count=150,
        price_tolerance=0.003,
        update_interval=60,
        price_change_trigger=0.005,
        budget_ratio=0.4,
    ))

    far_book: LayerConfig = field(default_factory=lambda: LayerConfig(
        distance_range=(0.02, 0.10),  # 2%-10%
        layer_count=300,
        price_tolerance=0.01,
        update_interval=180,
        price_change_trigger=0.01,
        budget_ratio=0.3,
    ))

    def __post_init__(self):
        """验证配置"""
        super().__post_init__()

        # 验证预算比例总和为1.0
        total_ratio = (
            self.near_book.budget_ratio +
            self.transition_zone.budget_ratio +
            self.far_book.budget_ratio
        )

        if abs(total_ratio - 1.0) > 0.01:
            raise ValueError(f"Budget ratios must sum to 1.0, got {total_ratio}")


@register_algorithm("layered")
class LayeredOrderbookAlgorithm(OrderbookAlgorithm):
    """分层订单簿算法实现

    特性：
    - 3层订单簿管理（near_book, transition_zone, far_book）
    - 差异化更新策略（不同层级不同频率）
    - 智能订单匹配（优先复用现有订单）
    - 冷却期机制（避免频繁更新）
    """

    def __init__(self, config: LayeredOrderbookConfig):
        """初始化分层订单簿算法

        Args:
            config: 分层订单簿配置
        """
        super().__init__(config)
        self.config: LayeredOrderbookConfig = config

        # 层级状态跟踪
        self.layer_states: Dict[str, Dict[str, Any]] = {
            "near_book": {
                "last_update_time": 0.0,
                "last_netvalue": None,
            },
            "transition_zone": {
                "last_update_time": 0.0,
                "last_netvalue": None,
            },
            "far_book": {
                "last_update_time": 0.0,
                "last_netvalue": None,
            },
        }

        # 首次运行标志
        self.first_run = True
        
        # ✅ 盘口不对称机制
        # asymmetry_bias: 正值=卖一更近净值, 负值=买一更近净值
        # 范围: -0.5 ~ +0.5 (对应 base_spread 的偏移比例)
        self.asymmetry_bias: float = 0.0
        self.last_bias_update: float = 0.0
        self.bias_update_interval: float = 60.0  # 每60秒更新一次偏移

    def validate_config(self):
        """验证配置"""
        # 基类已验证基础参数
        pass

    @property
    def algorithm_name(self) -> str:
        """算法名称"""
        return "layered_orderbook"

    @property
    def supported_layer_range(self) -> Tuple[int, int]:
        """支持的档位范围 (min, max)"""
        return (100, 1000000)  # 支持100到100万档

    def should_update_layers(self, current_netvalue: float) -> List[str]:
        """判断哪些层级需要更新

        决策逻辑：
        1. 首次运行 → 更新所有层级
        2. 检查冷却期 → 未到最小间隔的层级跳过
        3. 检查价格变化 → 超过阈值的层级更新

        Args:
            current_netvalue: 当前净值

        Returns:
            List[str]: 需要更新的层级名称列表
        """
        current_time = time.time()
        layers_to_update = []

        # 首次运行 → 初始化所有层级
        if self.first_run:
            self.first_run = False
            return ["near_book", "transition_zone", "far_book"]

        # 检查每一层
        for layer_name in ["near_book", "transition_zone", "far_book"]:
            layer_config = getattr(self.config, layer_name)
            layer_state = self.layer_states[layer_name]

            # 1. 检查冷却期
            time_since_update = current_time - layer_state["last_update_time"]
            if time_since_update < layer_config.update_interval:
                continue  # 冷却中，跳过

            # 2. 检查价格变化
            last_netvalue = layer_state["last_netvalue"]
            if last_netvalue is None:
                # 该层从未更新过，需要更新
                layers_to_update.append(layer_name)
                continue

            price_change_ratio = abs(current_netvalue - last_netvalue) / last_netvalue
            if price_change_ratio >= layer_config.price_change_trigger:
                layers_to_update.append(layer_name)

        return layers_to_update

    def generate_layer_orders(
        self,
        layer_name: str,
        netvalue: float
    ) -> Tuple[List[OrderLevel], List[OrderLevel]]:
        """生成单层订单

        Args:
            layer_name: 层级名称 ("near_book" | "transition_zone" | "far_book")
            netvalue: 当前净值

        Returns:
            Tuple[List[OrderLevel], List[OrderLevel]]: (买盘订单, 卖盘订单)
        """
        layer_config = getattr(self.config, layer_name)
        current_time = time.time()

        # ✅ 更新盘口不对称偏移（仅在近盘口层使用）
        if layer_name == "near_book":
            if current_time - self.last_bias_update >= self.bias_update_interval:
                # 生成新的不对称偏移: -0.4 ~ +0.4
                # 正值: 卖一更近净值（买方市场），负值: 买一更近净值（卖方市场）
                self.asymmetry_bias = np.random.uniform(-0.4, 0.4)
                self.last_bias_update = current_time
                logging.debug(
                    f"🔄 盘口不对称偏移更新: {self.asymmetry_bias:+.2f} "
                    f"({'卖一更近' if self.asymmetry_bias > 0 else '买一更近'})"
                )

        # 计算该层的价格范围
        if layer_name == "near_book":
            # 近盘口：净值 ± distance_threshold，应用不对称偏移
            base_spread = layer_config.distance_threshold
            
            # ✅ 计算不对称的买卖起始位置
            # asymmetry_bias > 0: 卖一距离缩小，买一距离扩大
            # asymmetry_bias < 0: 买一距离缩小，卖一距离扩大
            ask_base = 0.001 * (1 - self.asymmetry_bias * 0.5)  # 卖一起始点
            bid_base = 0.001 * (1 + self.asymmetry_bias * 0.5)  # 买一起始点
            
            # 确保最小距离不小于0.0005 (0.05%)
            ask_base = max(0.0005, ask_base)
            bid_base = max(0.0005, bid_base)
            
            ask_start = netvalue * (1 + ask_base)
            ask_end = netvalue * (1 + base_spread)
            bid_start = netvalue * (1 - base_spread)
            bid_end = netvalue * (1 - bid_base)
            
            logging.debug(
                f"📊 近盘口价格范围: 卖一={ask_start:.6f} (距净值{ask_base*100:.3f}%), "
                f"买一={bid_end:.6f} (距净值{bid_base*100:.3f}%)"
            )
        else:
            # 过渡区和远盘口：使用distance_range
            range_start, range_end = layer_config.distance_range
            ask_start = netvalue * (1 + range_start)
            ask_end = netvalue * (1 + range_end)
            bid_start = netvalue * (1 - range_end)
            bid_end = netvalue * (1 - range_start)

        # 生成价格档位
        n_ask = layer_config.layer_count // 2
        n_bid = layer_config.layer_count - n_ask

        # 卖单价格：从低到高线性分布
        ask_prices = np.linspace(ask_start, ask_end, n_ask)

        # 买单价格：从高到低线性分布
        bid_prices = np.linspace(bid_end, bid_start, n_bid)

        # 计算该层预算
        layer_budget = self.config.total_budget * layer_config.budget_ratio

        # 生成订单
        asks = []
        bids = []

        # 生成卖单
        for price in ask_prices:
            # 随机数量（80%-120%的平均值）
            avg_quantity = layer_budget / (n_ask * price)
            quantity = avg_quantity * np.random.uniform(0.8, 1.2)

            asks.append(OrderLevel(
                price=Decimal(str(round(price, self.config.price_precision))),
                quantity=Decimal(str(round(quantity, self.config.quantity_precision))),
                value=Decimal(str(round(price * quantity, 2))),
                side='ask',
                metadata={'layer': layer_name}
            ))

        # 生成买单
        for price in bid_prices:
            # 随机数量（80%-120%的平均值）
            avg_quantity = layer_budget / (n_bid * price)
            quantity = avg_quantity * np.random.uniform(0.8, 1.2)

            bids.append(OrderLevel(
                price=Decimal(str(round(price, self.config.price_precision))),
                quantity=Decimal(str(round(quantity, self.config.quantity_precision))),
                value=Decimal(str(round(price * quantity, 2))),
                side='bid',
                metadata={'layer': layer_name}
            ))

        return bids, asks

    def generate_snapshot(self) -> OrderbookSnapshot:
        """生成完整订单簿快照

        该方法会生成所有3层的订单，用于首次初始化或完整重建。

        Returns:
            OrderbookSnapshot: 完整的订单簿快照
        """
        start_time = time.time()

        all_bids = []
        all_asks = []

        # 生成所有层级的订单
        for layer_name in ["near_book", "transition_zone", "far_book"]:
            bids, asks = self.generate_layer_orders(layer_name, self.config.mid_price)
            all_bids.extend(bids)
            all_asks.extend(asks)

        # 按价格排序
        all_bids.sort(key=lambda x: x.price, reverse=True)  # 买单降序
        all_asks.sort(key=lambda x: x.price)  # 卖单升序

        generation_time = time.time() - start_time

        return OrderbookSnapshot(
            bids=all_bids,
            asks=all_asks,
            algorithm="layered_orderbook",
            generation_time=generation_time
        )

    def compute_diff(
        self,
        current_orders: Dict[str, List[dict]],
        netvalue: Optional[float] = None
    ) -> OrderbookDiff:
        """计算订单簿差异（智能增量更新）

        核心优化：
        1. 只更新需要更新的层级
        2. 优先复用价格接近的现有订单
        3. 避免全部取消重建

        Args:
            current_orders: 当前订单簿
                {
                    'bids': [{'order_id': '123', 'price': 1.0, 'quantity': 10}, ...],
                    'asks': [{'order_id': '456', 'price': 1.1, 'quantity': 10}, ...]
                }
            netvalue: 当前净值（如果提供，会更新config.mid_price）

        Returns:
            OrderbookDiff: 需要执行的操作列表
        """
        # 更新净值
        if netvalue is not None:
            self.config.mid_price = netvalue

        # 判断哪些层需要更新
        layers_to_update = self.should_update_layers(self.config.mid_price)

        if not layers_to_update:
            # 无需更新
            return OrderbookDiff(operations=[])

        operations = []

        # 为每个需要更新的层级计算差异
        for layer_name in layers_to_update:
            layer_config = getattr(self.config, layer_name)

            # 生成该层的目标订单
            target_bids, target_asks = self.generate_layer_orders(
                layer_name, self.config.mid_price
            )

            # 匹配买盘
            bid_ops = self._match_layer_orders(
                current_orders.get('bids', []),
                target_bids,
                layer_config,
                side='bid'
            )
            operations.extend(bid_ops)

            # 匹配卖盘
            ask_ops = self._match_layer_orders(
                current_orders.get('asks', []),
                target_asks,
                layer_config,
                side='ask'
            )
            operations.extend(ask_ops)

            # 更新层级状态
            current_time = time.time()
            self.layer_states[layer_name]["last_update_time"] = current_time
            self.layer_states[layer_name]["last_netvalue"] = self.config.mid_price

        return OrderbookDiff(operations=operations)

    def _match_layer_orders(
        self,
        current: List[dict],
        target: List[OrderLevel],
        layer_config: LayerConfig,
        side: str
    ) -> List[OrderOperation]:
        """匹配单层订单（智能匹配算法）

        策略：
        1. 对于每个目标价格，查找价格容差范围内的现有订单
        2. 如果找到匹配订单，保留它
        3. 如果没有找到，添加新订单
        4. 取消所有未匹配的现有订单

        Args:
            current: 当前订单列表
            target: 目标订单列表
            layer_config: 层级配置
            side: 'bid' | 'ask'

        Returns:
            List[OrderOperation]: 操作列表
        """
        operations = []
        matched_order_ids = set()

        # 为每个目标订单查找匹配
        for target_order in target:
            target_price = float(target_order.price)
            matched = False

            for current_order in current:
                if current_order['order_id'] in matched_order_ids:
                    continue  # 已匹配过

                current_price = float(current_order['price'])

                # 检查价格是否在容差范围内
                price_diff_ratio = abs(current_price - target_price) / target_price

                if price_diff_ratio <= layer_config.price_tolerance:
                    # 找到匹配订单，保留它
                    matched_order_ids.add(current_order['order_id'])
                    matched = True
                    break

            # 如果没有找到匹配，添加新订单
            if not matched:
                operations.append(OrderOperation(
                    action='add',
                    side=side,
                    price=target_order.price,
                    quantity=target_order.quantity,
                    reason=f'add_new_{side}_order'
                ))

        # 取消所有未匹配的订单
        for current_order in current:
            if current_order['order_id'] not in matched_order_ids:
                operations.append(OrderOperation(
                    action='cancel',
                    side=side,
                    order_id=current_order['order_id'],
                    reason=f'remove_old_{side}_order'
                ))

        return operations


# 工厂方法便捷创建
def create_layered_orderbook(
    symbol: str,
    total_budget: float,
    mid_price: float,
    bid_ask_spread: float = 0.01,
    **layer_configs
) -> LayeredOrderbookAlgorithm:
    """便捷创建分层订单簿实例

    Args:
        symbol: 交易对
        total_budget: 总预算
        mid_price: 中间价（净值）
        bid_ask_spread: 买卖价差
        **layer_configs: 层级配置覆盖
            例如: near_book={'layer_count': 100}

    Returns:
        LayeredOrderbookAlgorithm: 实例
    """
    config = LayeredOrderbookConfig(
        symbol=symbol,
        total_budget=total_budget,
        mid_price=mid_price,
        bid_ask_spread=bid_ask_spread,
        layer=500,  # 总档位数（会被各层配置覆盖）
    )

    # 应用层级配置覆盖
    for layer_name, layer_conf in layer_configs.items():
        if hasattr(config, layer_name):
            current = getattr(config, layer_name)
            for k, v in layer_conf.items():
                setattr(current, k, v)

    return LayeredOrderbookAlgorithm(config)
