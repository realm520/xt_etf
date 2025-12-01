"""
订单簿维护器配置

设计决策：
- 两层结构：近盘口(0-0.5%) + 远盘口(0.5%-max)
- 混合分布：近盘口等差密集，远盘口等比稀疏
- 操作限制：每周期最多20个操作
"""

from dataclasses import dataclass, field
from decimal import Decimal
from typing import Tuple, List, Optional


@dataclass
class LayerSpec:
    """单层规格配置"""

    name: str  # 层名称: 'near' | 'far'
    distance_range: Tuple[Decimal, Decimal]  # 距离范围 (min, max)，相对于NAV的百分比
    order_count: int  # 该层订单数（单边）
    budget_ratio: Decimal  # 预算占比 (0.0-1.0)
    distribution: str = "arithmetic"  # 价格分布: 'arithmetic' | 'geometric'

    def __post_init__(self):
        """参数验证和类型转换"""
        # 确保 distance_range 是 Decimal 元组
        if not isinstance(self.distance_range[0], Decimal):
            self.distance_range = (
                Decimal(str(self.distance_range[0])),
                Decimal(str(self.distance_range[1])),
            )

        # 确保 budget_ratio 是 Decimal
        if not isinstance(self.budget_ratio, Decimal):
            self.budget_ratio = Decimal(str(self.budget_ratio))

        # 验证
        if self.name not in ("near", "far"):
            raise ValueError(f"layer name must be 'near' or 'far', got {self.name}")

        if self.order_count < 1:
            raise ValueError(f"order_count must be >= 1, got {self.order_count}")

        if not (Decimal("0") <= self.budget_ratio <= Decimal("1")):
            raise ValueError(
                f"budget_ratio must be in [0, 1], got {self.budget_ratio}"
            )

        if self.distribution not in ("arithmetic", "geometric"):
            raise ValueError(
                f"distribution must be 'arithmetic' or 'geometric', got {self.distribution}"
            )

        if self.distance_range[0] < Decimal("0"):
            raise ValueError(
                f"distance_range[0] must be >= 0, got {self.distance_range[0]}"
            )

        if self.distance_range[1] <= self.distance_range[0]:
            raise ValueError(
                f"distance_range[1] must be > distance_range[0], "
                f"got {self.distance_range}"
            )


def default_near_layer() -> LayerSpec:
    """默认近盘口配置"""
    return LayerSpec(
        name="near",
        distance_range=(Decimal("0"), Decimal("0.005")),  # 0 - 0.5%
        order_count=20,  # 每边20档
        budget_ratio=Decimal("0.5"),  # 50%预算
        distribution="arithmetic",  # 等差分布（密集）
    )


def default_far_layer() -> LayerSpec:
    """默认远盘口配置"""
    return LayerSpec(
        name="far",
        distance_range=(Decimal("0.005"), Decimal("0.10")),  # 0.5% - 10%
        order_count=80,  # 每边80档
        budget_ratio=Decimal("0.5"),  # 50%预算
        distribution="geometric",  # 等比分布（稀疏）
    )


@dataclass
class MaintainerConfig:
    """订单簿维护器配置"""

    # 核心参数
    spread: Decimal  # 买卖价差（如 0.008 = 0.8%）
    max_distance: Decimal  # 最远距离（如 0.10 = 10%）
    total_budget: Decimal  # 总预算（USDT）

    # 两层配置
    near_layer: LayerSpec = field(default_factory=default_near_layer)
    far_layer: LayerSpec = field(default_factory=default_far_layer)

    # 精度控制
    price_precision: int = 6  # 价格精度（小数位数）
    quantity_precision: int = 4  # 数量精度（小数位数）

    # 触发参数
    min_price_change: Decimal = field(
        default_factory=lambda: Decimal("0.002")
    )  # 最小触发变化 (0.2%)
    price_tolerance: Decimal = field(
        default_factory=lambda: Decimal("0.0001")
    )  # 价格匹配容差 (0.01%)
    quantity_tolerance: Decimal = field(
        default_factory=lambda: Decimal("0.1")
    )  # 数量匹配容差 (10%)

    # 操作限制
    max_operations_per_cycle: int = 20  # 每周期最大操作数

    def __post_init__(self):
        """参数验证和类型转换"""
        # 类型转换
        if not isinstance(self.spread, Decimal):
            self.spread = Decimal(str(self.spread))
        if not isinstance(self.max_distance, Decimal):
            self.max_distance = Decimal(str(self.max_distance))
        if not isinstance(self.total_budget, Decimal):
            self.total_budget = Decimal(str(self.total_budget))
        if not isinstance(self.min_price_change, Decimal):
            self.min_price_change = Decimal(str(self.min_price_change))
        if not isinstance(self.price_tolerance, Decimal):
            self.price_tolerance = Decimal(str(self.price_tolerance))
        if not isinstance(self.quantity_tolerance, Decimal):
            self.quantity_tolerance = Decimal(str(self.quantity_tolerance))

        # 验证
        if self.spread <= Decimal("0"):
            raise ValueError(f"spread must be > 0, got {self.spread}")

        if self.max_distance <= self.spread:
            raise ValueError(
                f"max_distance must be > spread, got {self.max_distance} <= {self.spread}"
            )

        if self.total_budget <= Decimal("0"):
            raise ValueError(f"total_budget must be > 0, got {self.total_budget}")

        if self.max_operations_per_cycle < 1:
            raise ValueError(
                f"max_operations_per_cycle must be >= 1, "
                f"got {self.max_operations_per_cycle}"
            )

        # 验证预算比例总和
        total_ratio = self.near_layer.budget_ratio + self.far_layer.budget_ratio
        if abs(total_ratio - Decimal("1")) > Decimal("0.001"):
            raise ValueError(
                f"budget_ratio sum must be 1.0, got {total_ratio}"
            )

    @property
    def layers(self) -> List[LayerSpec]:
        """返回所有层配置"""
        return [self.near_layer, self.far_layer]

    @property
    def total_orders_per_side(self) -> int:
        """每边总订单数"""
        return self.near_layer.order_count + self.far_layer.order_count

    @classmethod
    def from_dict(cls, config: dict) -> "MaintainerConfig":
        """从字典创建配置"""
        near_config = config.get("near_layer", {})
        far_config = config.get("far_layer", {})

        near_layer = LayerSpec(
            name="near",
            distance_range=(
                Decimal(str(near_config.get("distance_min", 0))),
                Decimal(str(near_config.get("distance_max", 0.005))),
            ),
            order_count=near_config.get("order_count", 20),
            budget_ratio=Decimal(str(near_config.get("budget_ratio", 0.5))),
            distribution=near_config.get("distribution", "arithmetic"),
        )

        far_layer = LayerSpec(
            name="far",
            distance_range=(
                Decimal(str(far_config.get("distance_min", 0.005))),
                Decimal(str(far_config.get("distance_max", 0.10))),
            ),
            order_count=far_config.get("order_count", 80),
            budget_ratio=Decimal(str(far_config.get("budget_ratio", 0.5))),
            distribution=far_config.get("distribution", "geometric"),
        )

        return cls(
            spread=Decimal(str(config.get("spread", 0.008))),
            max_distance=Decimal(str(config.get("max_distance", 0.10))),
            total_budget=Decimal(str(config.get("total_budget", 10000))),
            near_layer=near_layer,
            far_layer=far_layer,
            price_precision=config.get("price_precision", 6),
            quantity_precision=config.get("quantity_precision", 4),
            min_price_change=Decimal(str(config.get("min_price_change", 0.002))),
            price_tolerance=Decimal(str(config.get("price_tolerance", 0.0001))),
            quantity_tolerance=Decimal(str(config.get("quantity_tolerance", 0.1))),
            max_operations_per_cycle=config.get("max_operations_per_cycle", 20),
        )

    def to_dict(self) -> dict:
        """转换为字典"""
        return {
            "spread": float(self.spread),
            "max_distance": float(self.max_distance),
            "total_budget": float(self.total_budget),
            "near_layer": {
                "distance_min": float(self.near_layer.distance_range[0]),
                "distance_max": float(self.near_layer.distance_range[1]),
                "order_count": self.near_layer.order_count,
                "budget_ratio": float(self.near_layer.budget_ratio),
                "distribution": self.near_layer.distribution,
            },
            "far_layer": {
                "distance_min": float(self.far_layer.distance_range[0]),
                "distance_max": float(self.far_layer.distance_range[1]),
                "order_count": self.far_layer.order_count,
                "budget_ratio": float(self.far_layer.budget_ratio),
                "distribution": self.far_layer.distribution,
            },
            "price_precision": self.price_precision,
            "quantity_precision": self.quantity_precision,
            "min_price_change": float(self.min_price_change),
            "price_tolerance": float(self.price_tolerance),
            "quantity_tolerance": float(self.quantity_tolerance),
            "max_operations_per_cycle": self.max_operations_per_cycle,
        }
