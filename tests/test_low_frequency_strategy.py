"""
中低频策略测试文件
测试配置加载和策略参数
"""

import pytest
from etf.config.loader import load_strategy_config, get_available_strategies


class TestLowFrequencyStrategy:
    """测试中低频策略参数"""

    @pytest.fixture
    def all_strategies(self):
        """加载所有策略配置"""
        strategies = {}
        for name in get_available_strategies():
            strategies[name] = load_strategy_config(name)
        return strategies

    def test_sleep_interval_settings(self, all_strategies):
        """测试sleep_interval参数设置"""
        for strategy_name, config in all_strategies.items():
            sleep_interval = config.get("sleep_interval", 10)
            assert 10 <= sleep_interval <= 15, (
                f"{strategy_name}的sleep_interval应在10-15秒之间，当前为{sleep_interval}秒"
            )
            print(f"✓ {strategy_name} sleep_interval: {sleep_interval}秒")

    def test_washing_lambda_settings(self, all_strategies):
        """测试washing_lambda参数设置"""
        for strategy_name, config in all_strategies.items():
            washing_lambda = config.get("washing_lambda", 30)
            assert 10 <= washing_lambda <= 60, (
                f"{strategy_name}的washing_lambda应在10-60秒之间，当前为{washing_lambda}秒"
            )
            print(f"✓ {strategy_name} washing_lambda: {washing_lambda}秒")

    def test_bid_ask_spread_by_leverage(self, all_strategies):
        """测试不同杠杆的价差设置"""
        for strategy_name, config in all_strategies.items():
            bid_ask_spread = config.get("bid_ask_spread", 0.008)
            leverage = config.get("leverage", 3)

            if leverage <= 3:
                min_spread, max_spread = 0.005, 0.02
            else:
                min_spread, max_spread = 0.01, 0.10

            assert min_spread <= bid_ask_spread <= max_spread, (
                f"{strategy_name}的bid_ask_spread应在{min_spread:.1%}-{max_spread:.1%}之间"
            )
            print(f"✓ {strategy_name} bid_ask_spread: {bid_ask_spread:.1%}")

    def test_leverage_config(self, all_strategies):
        """测试杠杆配置是否正确"""
        for strategy_name, config in all_strategies.items():
            leverage = config.get("leverage")
            assert leverage in (3, 5), f"{strategy_name} leverage应为3或5"
            print(f"✓ {strategy_name} leverage: {leverage}x")

    def test_orderbook_config_exists(self, all_strategies):
        """测试订单簿配置是否存在"""
        for strategy_name, config in all_strategies.items():
            algorithm = config.get("orderbook_algorithm")
            assert algorithm in ("natural", "layered")
            
            orderbook_config = config.get("orderbook_config", {})
            assert "total_budget" in orderbook_config
            assert "layer" in orderbook_config
            
            print(f"✓ {strategy_name} orderbook: {algorithm}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
