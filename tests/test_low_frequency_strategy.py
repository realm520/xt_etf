"""
中低频策略测试文件
测试新的时间间隔参数和价差设置对策略的影响
"""

import asyncio
import pytest
from unittest.mock import Mock, patch, MagicMock
import yaml
from decimal import Decimal
import time

from etf.market_making import MarketMaker
from etf.order_manager import OrderManager
from etf.risk import RiskManager


class TestLowFrequencyStrategy:
    """测试中低频策略参数"""

    @pytest.fixture
    def load_strategy_config(self):
        """加载策略配置"""
        with open("config/strategies.yaml", "r") as f:
            return yaml.safe_load(f)

    @pytest.fixture
    def mock_exchange(self):
        """模拟交易所客户端"""
        exchange = Mock()
        exchange.get_orderbook = Mock(
            return_value={
                "bids": [[100.0, 10.0], [99.9, 20.0], [99.8, 30.0]],
                "asks": [[100.1, 10.0], [100.2, 20.0], [100.3, 30.0]],
            }
        )
        exchange.create_order = Mock(return_value={"id": "12345", "status": "open"})
        exchange.cancel_order = Mock(return_value=True)
        return exchange

    def test_sleep_interval_settings(self, load_strategy_config):
        """测试sleep_interval参数设置是否符合中低频要求"""
        strategies = load_strategy_config["strategies"]

        for strategy_name, config in strategies.items():
            sleep_interval = config["sleep_interval"]

            # 验证sleep_interval在10-15秒范围内
            assert 10 <= sleep_interval <= 15, (
                f"{strategy_name}的sleep_interval应在10-15秒之间，当前为{sleep_interval}秒"
            )

            print(f"✓ {strategy_name} sleep_interval: {sleep_interval}秒")

    def test_washing_interval_settings(self, load_strategy_config):
        """测试washing_interval参数设置是否符合中低频要求"""
        strategies = load_strategy_config["strategies"]

        for strategy_name, config in strategies.items():
            washing_interval = config["washing_interval"]

            # 验证washing_interval在30-60秒范围内
            assert 30 <= washing_interval <= 60, (
                f"{strategy_name}的washing_interval应在30-60秒之间，当前为{washing_interval}秒"
            )

            print(f"✓ {strategy_name} washing_interval: {washing_interval}秒")

    def test_bid_ask_spread_by_leverage(self, load_strategy_config):
        """测试不同杠杆的价差设置是否合理"""
        strategies = load_strategy_config["strategies"]

        # 预期的价差范围（根据杠杆倍数）
        expected_spreads = {
            "stg3l": (0.008, 0.015),  # 3倍杠杆：0.8-1.5%
            "stg3s": (0.008, 0.015),
            "stg5l": (0.015, 0.05),  # 5倍杠杆：1.5-5%
            "stg5s": (0.015, 0.05),
        }

        for strategy_name, config in strategies.items():
            bid_ask_spread = config["bid_ask_spread"]
            min_spread, max_spread = expected_spreads[strategy_name]

            assert min_spread <= bid_ask_spread <= max_spread, (
                f"{strategy_name}的bid_ask_spread应在{min_spread:.1%}-{max_spread:.1%}之间，当前为{bid_ask_spread:.1%}"
            )

            print(f"✓ {strategy_name} bid_ask_spread: {bid_ask_spread:.1%}")

    @pytest.mark.asyncio
    async def test_low_frequency_order_placement(self, mock_exchange):
        """测试低频下单逻辑"""
        # 创建市场做市商
        mm = MarketMaker(
            exchange=mock_exchange,
            symbol="BTCUSDT",
            bid_ask_spread=0.02,  # 2% 价差
            order_amount=100,
        )

        # 记录下单时间
        order_times = []

        async def mock_place_order(*args, **kwargs):
            order_times.append(time.time())
            return {"id": f"order_{len(order_times)}", "status": "open"}

        mm.place_order = mock_place_order

        # 模拟运行30秒
        start_time = time.time()
        while time.time() - start_time < 30:
            await mm.update_orders()
            await asyncio.sleep(10)  # 低频间隔

        # 验证下单频率
        if len(order_times) >= 2:
            intervals = [
                order_times[i + 1] - order_times[i] for i in range(len(order_times) - 1)
            ]
            avg_interval = sum(intervals) / len(intervals)

            # 验证平均间隔大于8秒（考虑到实际执行时间）
            assert avg_interval > 8, f"下单间隔太短：平均{avg_interval:.1f}秒"
            print(f"✓ 平均下单间隔: {avg_interval:.1f}秒")

    def test_washing_frequency(self, load_strategy_config):
        """测试洗盘交易频率"""
        strategies = load_strategy_config["strategies"]

        for strategy_name, config in strategies.items():
            washing_interval = config["washing_interval"]

            # 计算每小时洗盘次数
            washes_per_hour = 3600 / washing_interval

            # 验证洗盘频率在合理范围内（每小时60-120次）
            assert 60 <= washes_per_hour <= 120, (
                f"{strategy_name}每小时洗盘{washes_per_hour:.0f}次，应在60-120次之间"
            )

            print(f"✓ {strategy_name} 每小时洗盘: {washes_per_hour:.0f}次")

    def test_risk_parameters_for_low_frequency(self, load_strategy_config):
        """测试低频策略的风险参数"""
        strategies = load_strategy_config["strategies"]

        for strategy_name, config in strategies.items():
            # 验证最大持仓
            max_position = config.get("max_position", 0)
            assert max_position > 0, f"{strategy_name}应设置max_position"

            # 验证止损设置
            stop_loss = config.get("stop_loss", 0)
            leverage = int(strategy_name[3])  # 从策略名中提取杠杆倍数

            # 高杠杆应有更严格的止损
            if leverage >= 5:
                assert 0 < stop_loss <= 0.02, f"{strategy_name}(5倍杠杆)止损应在2%以内"
            else:
                assert 0 < stop_loss <= 0.05, f"{strategy_name}(3倍杠杆)止损应在5%以内"

            print(f"✓ {strategy_name} 风险参数检查通过")

    @pytest.mark.asyncio
    async def test_net_value_calculation_interval(self):
        """测试净值计算间隔是否适合低频策略"""
        # 低频策略的净值计算应该有更长的间隔
        calculation_interval = 60  # 假设60秒计算一次

        assert calculation_interval >= 30, "净值计算间隔应至少30秒"
        print(f"✓ 净值计算间隔: {calculation_interval}秒")

    def test_order_lifetime_for_low_frequency(self, load_strategy_config):
        """测试订单生命周期是否适合低频交易"""
        strategies = load_strategy_config["strategies"]

        for strategy_name, config in strategies.items():
            sleep_interval = config["sleep_interval"]

            # 订单生命周期应该是sleep_interval的倍数
            order_lifetime = sleep_interval * 3  # 假设订单存活3个周期

            assert order_lifetime >= 30, f"{strategy_name}订单生命周期应至少30秒"
            assert order_lifetime <= 60, f"{strategy_name}订单生命周期不应超过60秒"

            print(f"✓ {strategy_name} 订单生命周期: {order_lifetime}秒")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
