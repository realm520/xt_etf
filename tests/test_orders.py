"""
订单类型系统单元测试

测试订单枚举、基类和具体订单类型的功能。
"""

import pytest
from decimal import Decimal
from datetime import datetime
from etf.orders import (
    OrderType,
    OrderSide,
    OrderStatus,
    BaseOrder,
    MarketMakingOrder,
    WashTradingOrder,
    AntiPinOrder,
)


class TestOrderEnums:
    """测试订单枚举"""

    def test_order_type_enum(self):
        """测试OrderType枚举"""
        assert OrderType.MARKET_MAKING.value == "market_making"
        assert OrderType.WASH_TRADING.value == "wash_trading"
        assert OrderType.ANTI_PIN.value == "anti_pin"
        assert str(OrderType.MARKET_MAKING) == "market_making"

    def test_order_side_enum(self):
        """测试OrderSide枚举"""
        assert OrderSide.BUY.value == "BUY"
        assert OrderSide.SELL.value == "SELL"
        assert str(OrderSide.BUY) == "BUY"

    def test_order_status_enum(self):
        """测试OrderStatus枚举"""
        assert OrderStatus.PENDING.value == "PENDING"
        assert OrderStatus.NEW.value == "NEW"
        assert OrderStatus.FILLED.value == "FILLED"
        assert OrderStatus.CANCELED.value == "CANCELED"


class TestBaseOrder:
    """测试BaseOrder基类"""

    def test_create_base_order(self):
        """测试创建基础订单"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET_MAKING,
            client_order_id="test_order_1",
        )

        assert order.symbol == "BTCUSDT"
        assert order.side == OrderSide.BUY
        assert order.price == Decimal("50000")
        assert order.quantity == Decimal("0.1")
        assert order.order_type == OrderType.MARKET_MAKING
        assert order.status == OrderStatus.PENDING
        assert order.filled_quantity == Decimal("0")

    def test_order_validation_success(self):
        """测试订单验证 - 成功"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET_MAKING,
        )

        is_valid, error = order.validate()
        assert is_valid is True
        assert error == ""

    def test_order_validation_invalid_price(self):
        """测试订单验证 - 无效价格"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("0"),
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET_MAKING,
        )

        is_valid, error = order.validate()
        assert is_valid is False
        assert "价格必须大于0" in error

    def test_order_validation_invalid_quantity(self):
        """测试订单验证 - 无效数量"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("-0.1"),
            order_type=OrderType.MARKET_MAKING,
        )

        is_valid, error = order.validate()
        assert is_valid is False
        assert "数量必须大于0" in error

    def test_order_validation_empty_symbol(self):
        """测试订单验证 - 空交易对"""
        order = BaseOrder(
            symbol="",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET_MAKING,
        )

        is_valid, error = order.validate()
        assert is_valid is False
        assert "symbol不能为空" in error

    def test_is_terminal_status(self):
        """测试终态判断"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET_MAKING,
        )

        # 初始状态不是终态
        assert order.is_terminal() is False
        assert order.is_active() is True

        # NEW状态不是终态
        order.status = OrderStatus.NEW
        assert order.is_terminal() is False

        # FILLED是终态
        order.status = OrderStatus.FILLED
        assert order.is_terminal() is True
        assert order.is_active() is False

        # CANCELED是终态
        order.status = OrderStatus.CANCELED
        assert order.is_terminal() is True

        # REJECTED是终态
        order.status = OrderStatus.REJECTED
        assert order.is_terminal() is True

    def test_get_remaining_quantity(self):
        """测试获取剩余数量"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
            order_type=OrderType.MARKET_MAKING,
        )

        # 未成交
        assert order.get_remaining_quantity() == Decimal("1.0")

        # 部分成交
        order.filled_quantity = Decimal("0.3")
        assert order.get_remaining_quantity() == Decimal("0.7")

        # 完全成交
        order.filled_quantity = Decimal("1.0")
        assert order.get_remaining_quantity() == Decimal("0")

    def test_get_fill_percentage(self):
        """测试获取成交百分比"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("1.0"),
            order_type=OrderType.MARKET_MAKING,
        )

        # 未成交
        assert order.get_fill_percentage() == 0.0

        # 部分成交
        order.filled_quantity = Decimal("0.5")
        assert order.get_fill_percentage() == 50.0

        # 完全成交
        order.filled_quantity = Decimal("1.0")
        assert order.get_fill_percentage() == 100.0

    def test_order_to_dict(self):
        """测试订单序列化为字典"""
        order = BaseOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            order_type=OrderType.MARKET_MAKING,
            client_order_id="test_order_1",
        )

        data = order.to_dict()

        assert data["symbol"] == "BTCUSDT"
        assert data["side"] == "BUY"
        assert data["price"] == "50000"
        assert data["quantity"] == "0.1"
        assert data["order_type"] == "market_making"
        assert data["client_order_id"] == "test_order_1"
        assert data["status"] == "PENDING"
        assert "created_at" in data
        assert "updated_at" in data

    def test_order_from_dict(self):
        """测试从字典创建订单"""
        data = {
            "symbol": "BTCUSDT",
            "side": "BUY",
            "price": "50000",
            "quantity": "0.1",
            "order_type": "market_making",
            "client_order_id": "test_order_1",
            "order_id": "12345",
            "status": "NEW",
            "filled_quantity": "0.05",
            "created_at": datetime.now().isoformat(),
            "updated_at": datetime.now().isoformat(),
        }

        order = BaseOrder.from_dict(data)

        assert order.symbol == "BTCUSDT"
        assert order.side == OrderSide.BUY
        assert order.price == Decimal("50000")
        assert order.quantity == Decimal("0.1")
        assert order.order_type == OrderType.MARKET_MAKING
        assert order.client_order_id == "test_order_1"
        assert order.order_id == "12345"
        assert order.status == OrderStatus.NEW
        assert order.filled_quantity == Decimal("0.05")


class TestMarketMakingOrder:
    """测试MarketMakingOrder"""

    def test_create_market_making_order(self):
        """测试创建做市订单"""
        order = MarketMakingOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            layer_index=2,
        )

        assert order.order_type == OrderType.MARKET_MAKING
        assert order.layer_index == 2
        assert "mm_" in order.client_order_id
        assert "BTCUSDT" in order.client_order_id
        assert "L2" in order.client_order_id

    def test_market_making_order_auto_client_id(self):
        """测试做市订单自动生成client_order_id"""
        order = MarketMakingOrder(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            price=Decimal("3000"),
            quantity=Decimal("1.0"),
            layer_index=0,
        )

        # 验证自动生成的client_order_id格式
        assert order.client_order_id.startswith("mm_ETHUSDT_sell_L0_")

    def test_market_making_order_to_dict(self):
        """测试做市订单序列化"""
        order = MarketMakingOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.1"),
            layer_index=3,
        )

        data = order.to_dict()

        assert data["order_type"] == "market_making"
        assert data["layer_index"] == 3


class TestWashTradingOrder:
    """测试WashTradingOrder"""

    def test_create_wash_trading_order(self):
        """测试创建洗盘订单"""
        order = WashTradingOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.01"),
            micro_trade_index=3,
            batch_id="batch_12345",
        )

        assert order.order_type == OrderType.WASH_TRADING
        assert order.micro_trade_index == 3
        assert order.batch_id == "batch_12345"
        assert "wash_" in order.client_order_id
        assert "M3" in order.client_order_id

    def test_wash_trading_order_auto_batch_id(self):
        """测试洗盘订单自动生成batch_id"""
        order = WashTradingOrder(
            symbol="ETHUSDT",
            side=OrderSide.SELL,
            price=Decimal("3000"),
            quantity=Decimal("0.05"),
            micro_trade_index=0,
        )

        # 验证自动生成的batch_id
        assert order.batch_id.startswith("batch_")
        assert order.client_order_id.startswith("wash_ETHUSDT_sell_")

    def test_wash_trading_order_to_dict(self):
        """测试洗盘订单序列化"""
        order = WashTradingOrder(
            symbol="BTCUSDT",
            side=OrderSide.BUY,
            price=Decimal("50000"),
            quantity=Decimal("0.01"),
            micro_trade_index=5,
            batch_id="batch_test",
        )

        data = order.to_dict()

        assert data["order_type"] == "wash_trading"
        assert data["micro_trade_index"] == 5
        assert data["batch_id"] == "batch_test"


class TestAntiPinOrder:
    """测试AntiPinOrder"""

    def test_create_anti_pin_order(self):
        """测试创建反针对订单"""
        order = AntiPinOrder(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            price=Decimal("52500"),
            quantity=Decimal("0.5"),
            deviation_rate=0.05,
            anti_pin_generation=10,
        )

        assert order.order_type == OrderType.ANTI_PIN
        assert order.deviation_rate == 0.05
        assert order.anti_pin_generation == 10
        assert "antipin_" in order.client_order_id
        assert "G10" in order.client_order_id

    def test_anti_pin_order_auto_client_id(self):
        """测试反针对订单自动生成client_order_id"""
        order = AntiPinOrder(
            symbol="ETHUSDT",
            side=OrderSide.BUY,
            price=Decimal("2850"),
            quantity=Decimal("1.0"),
            anti_pin_generation=5,
        )

        # 验证自动生成的client_order_id格式
        assert order.client_order_id.startswith("antipin_ETHUSDT_buy_G5_")

    def test_anti_pin_order_is_outdated(self):
        """测试反针对订单是否过时"""
        order = AntiPinOrder(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            price=Decimal("52500"),
            quantity=Decimal("0.5"),
            anti_pin_generation=8,
        )

        # 当前批次号小于给定批次号，订单过时
        assert order.is_outdated(10) is True

        # 当前批次号等于给定批次号，订单未过时
        assert order.is_outdated(8) is False

        # 当前批次号大于给定批次号，订单未过时
        assert order.is_outdated(5) is False

    def test_anti_pin_order_to_dict(self):
        """测试反针对订单序列化"""
        order = AntiPinOrder(
            symbol="BTCUSDT",
            side=OrderSide.SELL,
            price=Decimal("52500"),
            quantity=Decimal("0.5"),
            deviation_rate=0.08,
            anti_pin_generation=15,
        )

        data = order.to_dict()

        assert data["order_type"] == "anti_pin"
        assert data["deviation_rate"] == 0.08
        assert data["anti_pin_generation"] == 15


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
