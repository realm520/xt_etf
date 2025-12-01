"""
订单簿维护器测试 fixtures
"""

import pytest
from decimal import Decimal

from etf.orderbook.base import OrderLevel, OrderbookSnapshot, OrderOperation
from etf.orderbook.maintainer import (
    MaintainerConfig,
    LayerSpec,
    OrderbookMaintainer,
    OrderbookGenerator,
    OrderbookDiffer,
    CurrentOrderbook,
    ExistingOrder,
    MetricsCalculator,
)


@pytest.fixture
def default_config() -> MaintainerConfig:
    """默认维护器配置"""
    return MaintainerConfig(
        spread=Decimal("0.008"),  # 0.8%
        max_distance=Decimal("0.10"),  # 10%
        total_budget=Decimal("10000"),  # 10000 USDT
        price_precision=6,
        quantity_precision=4,
    )


@pytest.fixture
def small_config() -> MaintainerConfig:
    """小规模测试配置"""
    near_layer = LayerSpec(
        name="near",
        distance_range=(Decimal("0"), Decimal("0.005")),
        order_count=5,
        budget_ratio=Decimal("0.5"),
        distribution="arithmetic",
    )
    far_layer = LayerSpec(
        name="far",
        distance_range=(Decimal("0.005"), Decimal("0.05")),
        order_count=5,
        budget_ratio=Decimal("0.5"),
        distribution="geometric",
    )
    return MaintainerConfig(
        spread=Decimal("0.01"),  # 1%
        max_distance=Decimal("0.05"),  # 5%
        total_budget=Decimal("1000"),  # 1000 USDT
        near_layer=near_layer,
        far_layer=far_layer,
        price_precision=4,
        quantity_precision=2,
    )


@pytest.fixture
def sample_nav() -> Decimal:
    """示例 NAV"""
    return Decimal("1.0")


@pytest.fixture
def generator() -> OrderbookGenerator:
    """订单簿生成器"""
    return OrderbookGenerator()


@pytest.fixture
def differ() -> OrderbookDiffer:
    """差异计算器"""
    return OrderbookDiffer()


@pytest.fixture
def maintainer(default_config: MaintainerConfig) -> OrderbookMaintainer:
    """订单簿维护器"""
    return OrderbookMaintainer(default_config)


@pytest.fixture
def sample_bids() -> list:
    """示例买单列表"""
    return [
        OrderLevel(
            price=Decimal("0.995"),
            quantity=Decimal("100"),
            value=Decimal("99.5"),
            side="bid",
            metadata={"layer": "near"},
        ),
        OrderLevel(
            price=Decimal("0.990"),
            quantity=Decimal("101"),
            value=Decimal("99.99"),
            side="bid",
            metadata={"layer": "near"},
        ),
        OrderLevel(
            price=Decimal("0.950"),
            quantity=Decimal("105"),
            value=Decimal("99.75"),
            side="bid",
            metadata={"layer": "far"},
        ),
    ]


@pytest.fixture
def sample_asks() -> list:
    """示例卖单列表"""
    return [
        OrderLevel(
            price=Decimal("1.005"),
            quantity=Decimal("99.5"),
            value=Decimal("99.9975"),
            side="ask",
            metadata={"layer": "near"},
        ),
        OrderLevel(
            price=Decimal("1.010"),
            quantity=Decimal("99"),
            value=Decimal("99.99"),
            side="ask",
            metadata={"layer": "near"},
        ),
        OrderLevel(
            price=Decimal("1.050"),
            quantity=Decimal("95"),
            value=Decimal("99.75"),
            side="ask",
            metadata={"layer": "far"},
        ),
    ]


@pytest.fixture
def empty_orderbook() -> CurrentOrderbook:
    """空订单簿"""
    return CurrentOrderbook.empty()


@pytest.fixture
def sample_exchange_orders() -> list:
    """模拟交易所订单格式"""
    return [
        {
            "orderId": "1001",
            "clientOrderId": "mm_001",
            "price": "0.995",
            "origQty": "100",
            "side": "BUY",
        },
        {
            "orderId": "1002",
            "clientOrderId": "mm_002",
            "price": "0.990",
            "origQty": "101",
            "side": "BUY",
        },
        {
            "orderId": "2001",
            "clientOrderId": "mm_003",
            "price": "1.005",
            "origQty": "99.5",
            "side": "SELL",
        },
        {
            "orderId": "2002",
            "clientOrderId": "mm_004",
            "price": "1.010",
            "origQty": "99",
            "side": "SELL",
        },
    ]
