"""
MetricsCalculator 单元测试
"""

import pytest
from decimal import Decimal

from etf.orderbook.base import OrderLevel
from etf.orderbook.maintainer import BalanceMetrics, MetricsCalculator


class TestBalanceMetrics:
    """BalanceMetrics 测试"""

    def test_is_balanced_true(self):
        """测试平衡判断 - 平衡"""
        metrics = BalanceMetrics(
            vii=Decimal("0.05"),  # 5% 不平衡
            qii=Decimal("0.03"),
            v_bid=Decimal("1000"),
            v_ask=Decimal("950"),
            q_bid=Decimal("100"),
            q_ask=Decimal("97"),
            n_bid=10,
            n_ask=10,
        )
        assert metrics.is_value_balanced
        assert metrics.is_quantity_balanced
        assert metrics.is_balanced

    def test_is_balanced_false(self):
        """测试平衡判断 - 不平衡"""
        metrics = BalanceMetrics(
            vii=Decimal("0.20"),  # 20% 不平衡
            qii=Decimal("0.15"),
            v_bid=Decimal("1000"),
            v_ask=Decimal("700"),
            q_bid=Decimal("100"),
            q_ask=Decimal("75"),
            n_bid=10,
            n_ask=8,
        )
        assert not metrics.is_value_balanced
        assert not metrics.is_quantity_balanced
        assert not metrics.is_balanced

    def test_value_diff(self):
        """测试价值差异"""
        metrics = BalanceMetrics(
            vii=Decimal("0"),
            qii=Decimal("0"),
            v_bid=Decimal("1000"),
            v_ask=Decimal("800"),
            q_bid=Decimal("100"),
            q_ask=Decimal("80"),
            n_bid=10,
            n_ask=10,
        )
        assert metrics.value_diff == Decimal("200")
        assert metrics.quantity_diff == Decimal("20")

    def test_to_dict(self):
        """测试转换为字典"""
        metrics = BalanceMetrics(
            vii=Decimal("0.05"),
            qii=Decimal("0.03"),
            v_bid=Decimal("1000"),
            v_ask=Decimal("950"),
            q_bid=Decimal("100"),
            q_ask=Decimal("97"),
            n_bid=10,
            n_ask=10,
        )
        d = metrics.to_dict()
        assert "vii" in d
        assert "is_balanced" in d
        assert isinstance(d["vii"], float)


class TestMetricsCalculator:
    """MetricsCalculator 测试"""

    def test_calculate_balanced(self, sample_bids: list, sample_asks: list):
        """测试计算平衡指标"""
        metrics = MetricsCalculator.calculate(sample_bids, sample_asks)

        assert isinstance(metrics, BalanceMetrics)
        assert metrics.n_bid == len(sample_bids)
        assert metrics.n_ask == len(sample_asks)

    def test_calculate_empty(self):
        """测试空订单簿"""
        metrics = MetricsCalculator.calculate([], [])

        assert metrics.vii == Decimal("0")
        assert metrics.qii == Decimal("0")
        assert metrics.v_bid == Decimal("0")
        assert metrics.v_ask == Decimal("0")

    def test_calculate_vii_formula(self):
        """测试 VII 公式"""
        bids = [
            OrderLevel(
                price=Decimal("1.0"),
                quantity=Decimal("100"),
                value=Decimal("100"),
                side="bid",
            ),
        ]
        asks = [
            OrderLevel(
                price=Decimal("1.0"),
                quantity=Decimal("50"),
                value=Decimal("50"),
                side="ask",
            ),
        ]

        metrics = MetricsCalculator.calculate(bids, asks)

        # VII = (V_bid - V_ask) / (V_bid + V_ask) = (100 - 50) / (100 + 50) = 1/3
        expected_vii = Decimal("100") - Decimal("50")
        expected_vii = expected_vii / (Decimal("100") + Decimal("50"))
        assert abs(metrics.vii - expected_vii) < Decimal("0.001")

    def test_calculate_qii_formula(self):
        """测试 QII 公式"""
        bids = [
            OrderLevel(
                price=Decimal("1.0"),
                quantity=Decimal("100"),
                value=Decimal("100"),
                side="bid",
            ),
        ]
        asks = [
            OrderLevel(
                price=Decimal("1.0"),
                quantity=Decimal("80"),
                value=Decimal("80"),
                side="ask",
            ),
        ]

        metrics = MetricsCalculator.calculate(bids, asks)

        # QII = (Q_bid - Q_ask) / (Q_bid + Q_ask) = (100 - 80) / (100 + 80)
        expected_qii = Decimal("20") / Decimal("180")
        assert abs(metrics.qii - expected_qii) < Decimal("0.001")

    def test_calculate_spread(self, sample_bids: list, sample_asks: list):
        """测试价差计算"""
        spread_info = MetricsCalculator.calculate_spread(
            sample_bids, sample_asks, Decimal("1.0")
        )

        assert spread_info["best_bid"] is not None
        assert spread_info["best_ask"] is not None
        assert spread_info["spread"] > 0
        assert spread_info["mid_price"] is not None

    def test_calculate_spread_empty(self):
        """测试空订单簿价差"""
        spread_info = MetricsCalculator.calculate_spread([], [], Decimal("1.0"))

        assert spread_info["best_bid"] is None
        assert spread_info["spread"] is None

    def test_calculate_layer_metrics(self, sample_bids: list):
        """测试分层指标"""
        layer_metrics = MetricsCalculator.calculate_layer_metrics(
            sample_bids, Decimal("1.0")
        )

        assert "near" in layer_metrics
        assert "far" in layer_metrics

        near = layer_metrics["near"]
        assert near["order_count"] == 2  # 2 near orders in fixture
        assert near["total_value"] > 0

    def test_calculate_layer_metrics_empty(self):
        """测试空订单层指标"""
        layer_metrics = MetricsCalculator.calculate_layer_metrics([], Decimal("1.0"))
        assert len(layer_metrics) == 0
