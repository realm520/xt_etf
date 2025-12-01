"""
MaintainerConfig 单元测试
"""

import pytest
from decimal import Decimal

from etf.orderbook.maintainer import MaintainerConfig, LayerSpec


class TestLayerSpec:
    """LayerSpec 测试"""

    def test_create_near_layer(self):
        """测试创建近盘口层"""
        layer = LayerSpec(
            name="near",
            distance_range=(Decimal("0"), Decimal("0.005")),
            order_count=20,
            budget_ratio=Decimal("0.5"),
            distribution="arithmetic",
        )
        assert layer.name == "near"
        assert layer.order_count == 20
        assert layer.budget_ratio == Decimal("0.5")
        assert layer.distribution == "arithmetic"

    def test_create_far_layer(self):
        """测试创建远盘口层"""
        layer = LayerSpec(
            name="far",
            distance_range=(Decimal("0.005"), Decimal("0.10")),
            order_count=80,
            budget_ratio=Decimal("0.5"),
            distribution="geometric",
        )
        assert layer.name == "far"
        assert layer.order_count == 80
        assert layer.distribution == "geometric"

    def test_auto_type_conversion(self):
        """测试自动类型转换"""
        layer = LayerSpec(
            name="near",
            distance_range=(0, 0.005),  # float
            order_count=10,
            budget_ratio=0.5,  # float
        )
        assert isinstance(layer.distance_range[0], Decimal)
        assert isinstance(layer.budget_ratio, Decimal)

    def test_invalid_name(self):
        """测试无效层名"""
        with pytest.raises(ValueError, match="layer name must be"):
            LayerSpec(
                name="middle",  # 无效
                distance_range=(Decimal("0"), Decimal("0.005")),
                order_count=10,
                budget_ratio=Decimal("0.5"),
            )

    def test_invalid_order_count(self):
        """测试无效订单数"""
        with pytest.raises(ValueError, match="order_count must be >= 1"):
            LayerSpec(
                name="near",
                distance_range=(Decimal("0"), Decimal("0.005")),
                order_count=0,
                budget_ratio=Decimal("0.5"),
            )

    def test_invalid_budget_ratio(self):
        """测试无效预算比例"""
        with pytest.raises(ValueError, match="budget_ratio must be in"):
            LayerSpec(
                name="near",
                distance_range=(Decimal("0"), Decimal("0.005")),
                order_count=10,
                budget_ratio=Decimal("1.5"),  # 超过 1
            )

    def test_invalid_distribution(self):
        """测试无效分布类型"""
        with pytest.raises(ValueError, match="distribution must be"):
            LayerSpec(
                name="near",
                distance_range=(Decimal("0"), Decimal("0.005")),
                order_count=10,
                budget_ratio=Decimal("0.5"),
                distribution="linear",  # 无效
            )

    def test_invalid_distance_range(self):
        """测试无效距离范围"""
        with pytest.raises(ValueError, match="distance_range"):
            LayerSpec(
                name="near",
                distance_range=(Decimal("0.01"), Decimal("0.005")),  # max < min
                order_count=10,
                budget_ratio=Decimal("0.5"),
            )


class TestMaintainerConfig:
    """MaintainerConfig 测试"""

    def test_create_default_config(self, default_config: MaintainerConfig):
        """测试创建默认配置"""
        assert default_config.spread == Decimal("0.008")
        assert default_config.max_distance == Decimal("0.10")
        assert default_config.total_budget == Decimal("10000")

    def test_layers_property(self, default_config: MaintainerConfig):
        """测试 layers 属性"""
        layers = default_config.layers
        assert len(layers) == 2
        assert layers[0].name == "near"
        assert layers[1].name == "far"

    def test_total_orders_per_side(self, default_config: MaintainerConfig):
        """测试每边总订单数"""
        total = default_config.total_orders_per_side
        expected = (
            default_config.near_layer.order_count
            + default_config.far_layer.order_count
        )
        assert total == expected

    def test_budget_ratio_validation(self):
        """测试预算比例验证"""
        near = LayerSpec(
            name="near",
            distance_range=(Decimal("0"), Decimal("0.005")),
            order_count=10,
            budget_ratio=Decimal("0.3"),  # 0.3 + 0.5 ≠ 1.0
        )
        far = LayerSpec(
            name="far",
            distance_range=(Decimal("0.005"), Decimal("0.10")),
            order_count=10,
            budget_ratio=Decimal("0.5"),
        )
        with pytest.raises(ValueError, match="budget_ratio sum must be 1.0"):
            MaintainerConfig(
                spread=Decimal("0.008"),
                max_distance=Decimal("0.10"),
                total_budget=Decimal("10000"),
                near_layer=near,
                far_layer=far,
            )

    def test_spread_validation(self):
        """测试 spread 验证"""
        with pytest.raises(ValueError, match="spread must be > 0"):
            MaintainerConfig(
                spread=Decimal("0"),
                max_distance=Decimal("0.10"),
                total_budget=Decimal("10000"),
            )

    def test_max_distance_validation(self):
        """测试 max_distance 验证"""
        with pytest.raises(ValueError, match="max_distance must be > spread"):
            MaintainerConfig(
                spread=Decimal("0.10"),
                max_distance=Decimal("0.05"),  # < spread
                total_budget=Decimal("10000"),
            )

    def test_from_dict(self):
        """测试从字典创建"""
        config_dict = {
            "spread": 0.01,
            "max_distance": 0.05,
            "total_budget": 5000,
            "near_layer": {
                "distance_min": 0,
                "distance_max": 0.005,
                "order_count": 10,
                "budget_ratio": 0.6,
                "distribution": "arithmetic",
            },
            "far_layer": {
                "distance_min": 0.005,
                "distance_max": 0.05,
                "order_count": 20,
                "budget_ratio": 0.4,
                "distribution": "geometric",
            },
        }
        config = MaintainerConfig.from_dict(config_dict)
        assert config.spread == Decimal("0.01")
        assert config.total_budget == Decimal("5000")
        assert config.near_layer.order_count == 10
        assert config.far_layer.order_count == 20

    def test_to_dict(self, default_config: MaintainerConfig):
        """测试转换为字典"""
        config_dict = default_config.to_dict()
        assert "spread" in config_dict
        assert "near_layer" in config_dict
        assert "far_layer" in config_dict
        assert isinstance(config_dict["spread"], float)

    def test_roundtrip(self, default_config: MaintainerConfig):
        """测试字典往返转换"""
        config_dict = default_config.to_dict()
        restored = MaintainerConfig.from_dict(config_dict)
        assert restored.spread == default_config.spread
        assert restored.max_distance == default_config.max_distance
        assert restored.near_layer.order_count == default_config.near_layer.order_count
