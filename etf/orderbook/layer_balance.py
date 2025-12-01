"""
分层平衡检查器 - 做市订单的近、中、远三层分级管理

功能：
1. 每次调整时独立检查各层平衡
2. 近盘口: 硬性保证买一卖一 + 10%不平衡触发双向调整
3. 中盘口: 10%不平衡触发双向调整
4. 远盘口: 20%不平衡触发防御性调整（主要删除）

调整策略（双向调整）：
- 补充少的一侧（从目标订单选择，优先靠近NAV的）
- 删除多的一侧（从现有订单选择，优先远离NAV的）
"""

import logging
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple
from math import ceil, floor


@dataclass
class LayerBalanceConfig:
    """分层平衡配置"""

    # 近盘口配置 (0-0.5%)
    near_range: Tuple[float, float] = (0.0, 0.005)
    near_imbalance_threshold: float = 0.10  # 10%触发调整
    near_max_imbalance: float = 0.20  # 最大允许不平衡
    near_force_best_price: bool = True  # 硬性保证买一卖一

    # 中盘口配置 (0.5%-2%)
    mid_range: Tuple[float, float] = (0.005, 0.02)
    mid_imbalance_threshold: float = 0.10  # 10%触发
    mid_max_imbalance: float = 0.30

    # 远盘口配置 (2%-10%)
    far_range: Tuple[float, float] = (0.02, 0.10)
    far_imbalance_threshold: float = 0.20  # 20%触发（防御优先，更宽松）
    far_max_imbalance: float = 0.50
    far_defense_mode: bool = True  # 防御模式：主要删除过剩订单

    # 全局配置
    max_adjustment_per_cycle: int = 10  # 单周期最大调整数
    protect_best_orders: bool = True  # 保护买一卖一
    protect_count: int = 2  # 保护最优N档


@dataclass
class LayerState:
    """单层状态"""

    layer_name: str
    buy_orders: List[Dict] = field(default_factory=list)
    sell_orders: List[Dict] = field(default_factory=list)

    @property
    def buy_count(self) -> int:
        return len(self.buy_orders)

    @property
    def sell_count(self) -> int:
        return len(self.sell_orders)

    @property
    def total_count(self) -> int:
        return self.buy_count + self.sell_count

    @property
    def imbalance_ratio(self) -> float:
        """计算不平衡度: |buy - sell| / total"""
        if self.total_count == 0:
            return 0.0
        return abs(self.buy_count - self.sell_count) / self.total_count

    @property
    def best_buy(self) -> Optional[float]:
        """最高买价"""
        if not self.buy_orders:
            return None
        return max(float(o.get("price", 0)) for o in self.buy_orders)

    @property
    def best_sell(self) -> Optional[float]:
        """最低卖价"""
        if not self.sell_orders:
            return None
        prices = [float(o.get("price", 0)) for o in self.sell_orders if float(o.get("price", 0)) > 0]
        return min(prices) if prices else None

    def get_deficit_side(self) -> Optional[str]:
        """获取不足的一侧"""
        if self.buy_count < self.sell_count:
            return "BUY"
        elif self.sell_count < self.buy_count:
            return "SELL"
        return None

    def get_surplus_side(self) -> Optional[str]:
        """获取过剩的一侧"""
        deficit = self.get_deficit_side()
        if deficit == "BUY":
            return "SELL"
        elif deficit == "SELL":
            return "BUY"
        return None


class LayerBalanceChecker:
    """
    分层平衡检查器

    每次做市调整时独立检查各档位平衡，返回需要添加和取消的订单列表。
    """

    def __init__(
        self,
        config: Optional[LayerBalanceConfig] = None,
        logger: Optional[logging.Logger] = None,
    ):
        self.config = config or LayerBalanceConfig()
        self.logger = logger or logging.getLogger(__name__)

        # 受保护的订单ID集合（禁止取消）
        self._protected_order_ids: set = set()

    def check_and_adjust(
        self,
        current_orders: List[Dict],
        target_orders: List[Dict],
        nav: float,
        spread: float,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        检查各层平衡并返回调整订单

        Args:
            current_orders: 当前挂单列表
            target_orders: 目标订单列表
            nav: 当前净值
            spread: 目标买卖价差

        Returns:
            (add_orders, cancel_orders): 需要添加和取消的订单列表
        """
        add_orders: List[Dict] = []
        cancel_orders: List[Dict] = []

        if nav <= 0:
            self.logger.warning("NAV <= 0, 跳过平衡检查")
            return add_orders, cancel_orders

        # 识别并保护关键订单
        self._identify_protected_orders(current_orders, nav)

        # 按层级分类当前订单
        layers = self._classify_orders_by_layer(current_orders, nav)

        # 按层级分类目标订单
        target_layers = self._classify_target_orders(target_orders, nav)

        # 1. 近盘口检查（最高优先级）
        near_add, near_cancel = self._check_near_book(
            layers["near"], target_layers["near"], nav, spread
        )
        add_orders.extend(near_add)
        cancel_orders.extend(near_cancel)

        # 2. 中盘口检查
        mid_add, mid_cancel = self._check_mid_book(
            layers["mid"], target_layers["mid"], nav
        )
        add_orders.extend(mid_add)
        cancel_orders.extend(mid_cancel)

        # 3. 远盘口检查（防御优先）
        far_add, far_cancel = self._check_far_book(
            layers["far"], target_layers["far"], nav
        )
        add_orders.extend(far_add)
        cancel_orders.extend(far_cancel)

        # 过滤掉受保护的订单
        cancel_orders = self._filter_protected_orders(cancel_orders)

        # 日志统计
        self._log_adjustment_summary(layers, add_orders, cancel_orders)

        return add_orders, cancel_orders

    def _classify_orders_by_layer(
        self, orders: List[Dict], nav: float
    ) -> Dict[str, LayerState]:
        """按层级分类订单"""
        layers = {
            "near": LayerState(layer_name="near"),
            "mid": LayerState(layer_name="mid"),
            "far": LayerState(layer_name="far"),
        }

        for order in orders:
            price = float(order.get("price", 0))
            if price <= 0:
                continue

            # 计算距离NAV的百分比
            distance = abs(price - nav) / nav
            side = order.get("side", "").upper()

            # 分类到对应层级
            if distance <= self.config.near_range[1]:
                layer = layers["near"]
            elif distance <= self.config.mid_range[1]:
                layer = layers["mid"]
            elif distance <= self.config.far_range[1]:
                layer = layers["far"]
            else:
                continue  # 超出范围

            if side == "BUY":
                layer.buy_orders.append(order)
            elif side == "SELL":
                layer.sell_orders.append(order)

        return layers

    def _classify_target_orders(
        self, target_orders: List[Dict], nav: float
    ) -> Dict[str, LayerState]:
        """按层级分类目标订单"""
        layers = {
            "near": LayerState(layer_name="near"),
            "mid": LayerState(layer_name="mid"),
            "far": LayerState(layer_name="far"),
        }

        for order in target_orders:
            price = float(order.get("price", 0))
            if price <= 0:
                continue

            distance = abs(price - nav) / nav
            direction = order.get("direction", "").lower()

            if distance <= self.config.near_range[1]:
                layer = layers["near"]
            elif distance <= self.config.mid_range[1]:
                layer = layers["mid"]
            elif distance <= self.config.far_range[1]:
                layer = layers["far"]
            else:
                continue

            if direction == "bid":
                layer.buy_orders.append(order)
            elif direction == "ask":
                layer.sell_orders.append(order)

        return layers

    def _check_near_book(
        self,
        state: LayerState,
        target_state: LayerState,
        nav: float,
        spread: float,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        近盘口检查（最高优先级）

        规则：
        1. 硬性保证买一卖一存在
        2. 检查价差是否合理
        3. 10%不平衡触发双向调整
        """
        add_orders: List[Dict] = []
        cancel_orders: List[Dict] = []

        # 计算目标买一卖一价格
        target_buy1 = nav * (1 - spread / 2)
        target_sell1 = nav * (1 + spread / 2)

        # 规则1: 硬性保证买一卖一
        if self.config.near_force_best_price:
            if state.best_buy is None:
                # 买一缺失，从目标订单补充
                best_target_buy = self._find_best_target_order(
                    target_state.buy_orders, "BUY", nav
                )
                if best_target_buy:
                    add_orders.append(best_target_buy)
                    self.logger.warning(
                        f"[近盘口] 买一缺失，补单 @ {best_target_buy.get('price')}"
                    )

            if state.best_sell is None:
                # 卖一缺失，从目标订单补充
                best_target_sell = self._find_best_target_order(
                    target_state.sell_orders, "SELL", nav
                )
                if best_target_sell:
                    add_orders.append(best_target_sell)
                    self.logger.warning(
                        f"[近盘口] 卖一缺失，补单 @ {best_target_sell.get('price')}"
                    )

        # 规则2: 检查价差
        if state.best_buy and state.best_sell:
            actual_spread = (state.best_sell - state.best_buy) / nav
            if actual_spread > spread * 1.5:
                self.logger.warning(
                    f"[近盘口] 价差过大 {actual_spread:.2%} > 目标{spread:.2%}*1.5"
                )
                # 补充中间订单（后续迭代可优化）

        # 规则3: 10%不平衡触发双向调整
        if state.imbalance_ratio > self.config.near_imbalance_threshold:
            self.logger.warning(
                f"[近盘口] 不平衡 {state.imbalance_ratio:.1%} > {self.config.near_imbalance_threshold:.0%}, "
                f"BUY={state.buy_count}, SELL={state.sell_count}"
            )
            add, cancel = self._bidirectional_adjustment(
                state=state,
                target_state=target_state,
                nav=nav,
                threshold=self.config.near_imbalance_threshold,
                max_threshold=self.config.near_max_imbalance,
                max_adjust=self.config.max_adjustment_per_cycle,
            )
            add_orders.extend(add)
            cancel_orders.extend(cancel)

        return add_orders, cancel_orders

    def _check_mid_book(
        self,
        state: LayerState,
        target_state: LayerState,
        nav: float,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        中盘口检查

        规则：
        1. 10%不平衡触发温和双向调整
        2. 30%以上激进调整
        """
        add_orders: List[Dict] = []
        cancel_orders: List[Dict] = []

        if state.imbalance_ratio > self.config.mid_imbalance_threshold:
            aggressive = state.imbalance_ratio > self.config.mid_max_imbalance
            mode = "激进" if aggressive else "温和"
            self.logger.info(
                f"[中盘口] 不平衡 {state.imbalance_ratio:.1%}, {mode}调整, "
                f"BUY={state.buy_count}, SELL={state.sell_count}"
            )

            add, cancel = self._bidirectional_adjustment(
                state=state,
                target_state=target_state,
                nav=nav,
                threshold=self.config.mid_imbalance_threshold,
                max_threshold=self.config.mid_max_imbalance,
                max_adjust=self.config.max_adjustment_per_cycle,
                aggressive=aggressive,
            )
            add_orders.extend(add)
            cancel_orders.extend(cancel)

        return add_orders, cancel_orders

    def _check_far_book(
        self,
        state: LayerState,
        target_state: LayerState,
        nav: float,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        远盘口检查（防御优先）

        规则：
        1. 20%不平衡触发调整
        2. 防御模式：主要删除过剩订单，少量补充
        """
        add_orders: List[Dict] = []
        cancel_orders: List[Dict] = []

        if state.imbalance_ratio > self.config.far_imbalance_threshold:
            self.logger.warning(
                f"[远盘口] 不平衡 {state.imbalance_ratio:.1%} > {self.config.far_imbalance_threshold:.0%}, "
                f"BUY={state.buy_count}, SELL={state.sell_count}"
            )

            if self.config.far_defense_mode:
                # 防御模式：主要删除过剩订单
                cancel = self._defense_adjustment(state, nav)
                cancel_orders.extend(cancel)
            else:
                # 常规双向调整
                add, cancel = self._bidirectional_adjustment(
                    state=state,
                    target_state=target_state,
                    nav=nav,
                    threshold=self.config.far_imbalance_threshold,
                    max_threshold=self.config.far_max_imbalance,
                    max_adjust=self.config.max_adjustment_per_cycle,
                )
                add_orders.extend(add)
                cancel_orders.extend(cancel)

        return add_orders, cancel_orders

    def _bidirectional_adjustment(
        self,
        state: LayerState,
        target_state: LayerState,
        nav: float,
        threshold: float,
        max_threshold: float,
        max_adjust: int,
        aggressive: bool = False,
    ) -> Tuple[List[Dict], List[Dict]]:
        """
        双向调整策略

        - 补充少的一侧（从目标订单选择，优先靠近NAV的）
        - 删除多的一侧（从现有订单选择，优先远离NAV的）

        调整比例：
        - 温和(10%-20%): 补充 ceil(deficit/3)+1, 删除 floor(deficit/4)
        - 标准(20%-30%): 补充 ceil(deficit/2)+1, 删除 floor(deficit/3)
        - 激进(>30%): 补充 ceil(deficit/2)+2, 删除 floor(deficit/2)
        """
        add_orders: List[Dict] = []
        cancel_orders: List[Dict] = []

        deficit_side = state.get_deficit_side()
        surplus_side = state.get_surplus_side()

        if not deficit_side:
            return add_orders, cancel_orders

        # 计算不平衡数量
        deficit = abs(state.buy_count - state.sell_count)

        # 根据不平衡度确定调整数量
        imbalance = state.imbalance_ratio
        if imbalance > max_threshold or aggressive:
            # 激进模式
            add_count = min(ceil(deficit / 2) + 2, max_adjust)
            cancel_count = min(floor(deficit / 2), max_adjust // 2)
        elif imbalance > (threshold + max_threshold) / 2:
            # 标准模式
            add_count = min(ceil(deficit / 2) + 1, max_adjust)
            cancel_count = min(floor(deficit / 3), max_adjust // 2)
        else:
            # 温和模式
            add_count = min(ceil(deficit / 3) + 1, max_adjust // 2)
            cancel_count = min(floor(deficit / 4), max_adjust // 3)

        self.logger.info(
            f"[{state.layer_name}] 双向调整: 补充{deficit_side} {add_count}单, "
            f"删除{surplus_side} {cancel_count}单"
        )

        # 1. 补充不足侧（从目标订单选择，优先靠近NAV的）
        target_orders = (
            target_state.buy_orders if deficit_side == "BUY" else target_state.sell_orders
        )
        # 按距离NAV排序，优先近的
        sorted_targets = sorted(
            target_orders, key=lambda o: abs(float(o.get("price", 0)) - nav)
        )
        for target in sorted_targets[:add_count]:
            add_orders.append(self._convert_target_to_order(target, deficit_side))

        # 2. 删除过剩侧（从现有订单选择，优先远离NAV的）
        if surplus_side and cancel_count > 0:
            surplus_orders = (
                state.sell_orders if surplus_side == "SELL" else state.buy_orders
            )
            # 按距离NAV排序，优先远的
            sorted_surplus = sorted(
                surplus_orders,
                key=lambda o: abs(float(o.get("price", 0)) - nav),
                reverse=True,
            )
            cancel_orders.extend(sorted_surplus[:cancel_count])

        return add_orders, cancel_orders

    def _defense_adjustment(
        self, state: LayerState, nav: float
    ) -> List[Dict]:
        """
        防御性调整（远盘口专用）

        只删除过剩订单，不补充
        """
        cancel_orders: List[Dict] = []

        surplus_side = state.get_surplus_side()
        if not surplus_side:
            return cancel_orders

        deficit = abs(state.buy_count - state.sell_count)
        cancel_count = min(ceil(deficit / 2), self.config.max_adjustment_per_cycle)

        surplus_orders = (
            state.sell_orders if surplus_side == "SELL" else state.buy_orders
        )
        # 按距离NAV排序，优先删除最远的
        sorted_surplus = sorted(
            surplus_orders,
            key=lambda o: abs(float(o.get("price", 0)) - nav),
            reverse=True,
        )

        self.logger.info(
            f"[远盘口] 防御调整: 删除{surplus_side} {cancel_count}单"
        )

        cancel_orders.extend(sorted_surplus[:cancel_count])
        return cancel_orders

    def _identify_protected_orders(
        self, orders: List[Dict], nav: float
    ) -> None:
        """识别并保护关键订单（买一卖一及次优）"""
        self._protected_order_ids.clear()

        if not self.config.protect_best_orders:
            return

        # 分离买卖订单并排序
        buy_orders = sorted(
            [o for o in orders if o.get("side", "").upper() == "BUY"],
            key=lambda o: float(o.get("price", 0)),
            reverse=True,  # 买单按价格降序
        )
        sell_orders = sorted(
            [o for o in orders if o.get("side", "").upper() == "SELL"],
            key=lambda o: float(o.get("price", float("inf"))),
        )

        # 保护最优N档
        for order in buy_orders[: self.config.protect_count]:
            order_id = order.get("orderId") or order.get("order_id")
            if order_id:
                self._protected_order_ids.add(order_id)

        for order in sell_orders[: self.config.protect_count]:
            order_id = order.get("orderId") or order.get("order_id")
            if order_id:
                self._protected_order_ids.add(order_id)

    def _filter_protected_orders(
        self, cancel_orders: List[Dict]
    ) -> List[Dict]:
        """过滤掉受保护的订单"""
        if not self.config.protect_best_orders:
            return cancel_orders

        filtered = []
        for order in cancel_orders:
            order_id = order.get("orderId") or order.get("order_id")
            if order_id not in self._protected_order_ids:
                filtered.append(order)
            else:
                self.logger.debug(f"订单 {order_id} 受保护，跳过取消")

        return filtered

    def _find_best_target_order(
        self, target_orders: List[Dict], side: str, nav: float
    ) -> Optional[Dict]:
        """从目标订单中找最接近NAV的订单"""
        if not target_orders:
            return None

        sorted_targets = sorted(
            target_orders, key=lambda o: abs(float(o.get("price", 0)) - nav)
        )
        if sorted_targets:
            # 传入完整的目标订单（包含min_price, max_price等字段）
            return self._convert_target_to_order(sorted_targets[0], side)
        return None

    def _convert_target_to_order(
        self, target: Dict, side: str
    ) -> Dict:
        """将目标订单格式转换为可执行订单格式"""
        price = float(target.get("price", 0))
        quantity = target.get("quantity") or target.get("amount")
        return {
            "price": price,
            "quantity": quantity,
            "side": side,
            "type": "LIMIT",
            "timeInForce": "GTC",
            "order_purpose": f"balance_{side.lower()}",
            # 保留optimize_order_matching所需的字段
            "amount": quantity,
            "direction": "bid" if side == "BUY" else "ask",
            "min_price": target.get("min_price", price * 0.9999),
            "max_price": target.get("max_price", price * 1.0001),
        }

    def _log_adjustment_summary(
        self,
        layers: Dict[str, LayerState],
        add_orders: List[Dict],
        cancel_orders: List[Dict],
    ) -> None:
        """输出调整汇总日志"""
        if not add_orders and not cancel_orders:
            return

        summary_parts = []
        for name, state in layers.items():
            status = "OK" if state.imbalance_ratio <= 0.10 else f"{state.imbalance_ratio:.0%}"
            summary_parts.append(
                f"{name}[B{state.buy_count}/S{state.sell_count}:{status}]"
            )

        self.logger.info(
            f"[分层平衡] {' | '.join(summary_parts)} | "
            f"调整: +{len(add_orders)} -{len(cancel_orders)}"
        )
