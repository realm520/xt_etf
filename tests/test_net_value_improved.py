# -*- coding:utf-8 -*-

"""
测试改进版净值计算器

Author: AllenBrother
Date:   2024/12/19
"""

import time
import json
import redis
import pytest
from unittest.mock import MagicMock, patch
from loguru import logger

from etf.net_value_improved import ImprovedNetValue
from etf.net_value_recovery import NetValueRecovery


class TestImprovedNetValue:
    """测试改进版净值计算器"""

    @pytest.fixture
    def redis_client(self):
        """创建Redis测试客户端"""
        r = redis.Redis(host="localhost", port=6379, db=15, decode_responses=True)
        # 清理测试数据
        r.flushdb()
        yield r
        r.flushdb()

    @pytest.fixture
    def calculator(self, redis_client):
        """创建测试用的净值计算器"""
        with patch("etf.net_value_improved.redis.Redis") as mock_redis:
            mock_redis.return_value = redis_client
            calc = ImprovedNetValue(
                symbol="test_usdt",
                m_lever=3,
                long=True,
                time_gap_second=1,  # 加快测试速度
                max_single_change=0.10,
                max_restart_gap=300,
            )
            # Mock交易所客户端
            calc.spot_client = MagicMock()
            return calc

    def test_init_with_no_data(self, calculator):
        """测试无历史数据时的初始化"""
        assert calculator.net_value_data["net_value"] == 1.0
        assert calculator.net_value_data["last_price"] is None
        assert calculator.net_value_data["update_count"] == 0
        assert calculator.net_value_data["total_fee_deducted"] == 0.0

    def test_init_with_existing_data(self, redis_client, calculator):
        """测试有历史数据时的初始化"""
        # 预设数据
        test_data = {
            "net_value": 1.05,
            "last_price": 100.0,
            "last_update_ts": time.time() - 5,  # 5秒前
            "update_count": 10,
            "total_fee_deducted": 0.0001,
            "abnormal_events": [],
        }
        redis_client.set(calculator.redis_detail_key, json.dumps(test_data))

        # 重新初始化
        new_calc = ImprovedNetValue(symbol="test_usdt", m_lever=3, long=True)
        new_calc.r = redis_client
        new_calc.net_value_data = new_calc._init_net_value(1.0)

        assert new_calc.net_value_data["net_value"] == 1.05
        assert new_calc.net_value_data["update_count"] == 10

    def test_price_spike_protection(self, calculator):
        """测试价格异常波动保护"""
        calculator.net_value_data["net_value"] = 1.0
        calculator.underlying_mid_price_queue.put(100.0)
        calculator.underlying_mid_price_queue.put(115.0)  # 15%涨幅，超过限制

        net_value = calculator.cal_net_value()

        # 应该限制在10%
        expected = 1.0 * (1 + 3 * 0.10)  # 3倍杠杆，10%限制
        assert abs(net_value - expected) < 0.001
        assert len(calculator.net_value_data["abnormal_events"]) == 1
        assert calculator.net_value_data["abnormal_events"][0]["type"] == "price_spike"

    def test_rebalance_mechanism(self, calculator):
        """测试再平衡机制"""
        calculator.net_value_data["net_value"] = 1.0
        calculator.underlying_mid_price_queue.put(100.0)
        calculator.underlying_mid_price_queue.put(107.0)  # 7%涨幅，触发再平衡

        net_value = calculator.cal_net_value()

        # 应该触发一次再平衡（5%）+ 剩余2%
        # 净值 = 1.0 * (1 + 3 * 0.05) * (1 + 3 * 0.02)
        expected = 1.0 * 1.15 * 1.06
        assert abs(net_value - expected) < 0.001

    def test_fee_calculation(self, calculator):
        """测试管理费计算"""
        net_value = 1.0
        calculator.time_gap_fee = 0.0001  # 模拟管理费

        net_value_after_fee = calculator.cal_fee(net_value)

        assert net_value_after_fee == 0.9999
        assert calculator.net_value_data["total_fee_deducted"] == 0.0001

    def test_recovery_short_gap(self, calculator):
        """测试短时间断线恢复"""
        test_data = {
            "net_value": 1.0,
            "last_price": 100.0,
            "last_update_ts": time.time() - 45,  # 45秒前
            "update_count": 10,
            "total_fee_deducted": 0.0,
            "abnormal_events": [],
        }

        calculator._recover_net_value(test_data, 45)

        # 应该补扣4次管理费（45秒/10秒）
        assert test_data["total_fee_deducted"] > 0
        assert len(test_data["abnormal_events"]) == 1
        assert test_data["abnormal_events"][0]["type"] == "recovery"

    def test_recovery_long_gap(self, calculator):
        """测试长时间断线处理"""
        test_data = {
            "net_value": 1.0,
            "last_price": 100.0,
            "last_update_ts": time.time() - 400,  # 400秒，超过限制
            "update_count": 10,
            "total_fee_deducted": 0.0,
            "abnormal_events": [],
        }

        calculator._recover_net_value(test_data, 400)

        # 应该记录异常事件
        assert len(test_data["abnormal_events"]) == 1
        assert test_data["abnormal_events"][0]["type"] == "long_restart"

    def test_save_to_redis(self, calculator, redis_client):
        """测试Redis保存功能"""
        test_data = {
            "net_value": 1.05,
            "last_price": 101.0,
            "last_update_ts": time.time(),
            "update_count": 5,
            "total_fee_deducted": 0.0001,
            "abnormal_events": [],
        }

        calculator._save_to_redis(test_data)

        # 验证简单净值
        simple_value = redis_client.get(calculator.redis_key)
        assert float(simple_value) == 1.05

        # 验证详细数据
        detail_data = json.loads(redis_client.get(calculator.redis_detail_key))
        assert detail_data["net_value"] == 1.05
        assert detail_data["last_price"] == 101.0

        # 验证历史记录
        history_count = redis_client.llen(calculator.redis_history_key)
        assert history_count == 1


class TestNetValueRecovery:
    """测试净值恢复工具"""

    @pytest.fixture
    def recovery_tool(self):
        """创建测试用的恢复工具"""
        tool = NetValueRecovery(
            symbol="test_usdt", m_lever=3, rebalance=0.05, long=True
        )
        # Mock交易所客户端
        tool.spot_client = MagicMock()
        return tool

    def test_calculate_price_changes(self, recovery_tool):
        """测试价格变化计算"""
        # 模拟K线数据
        klines = [
            [1640000000000, "100", "101", "99", "100.5", "1000"],
            [1640000060000, "100.5", "102", "100", "101.5", "1200"],
            [1640000120000, "101.5", "103", "101", "102.0", "1100"],
        ]

        changes = recovery_tool.calculate_price_changes(klines)

        assert len(changes) == 3
        assert changes[0][2] == 0.0  # 第一个没有变化率
        assert abs(changes[1][2] - 0.00995) < 0.00001  # (101.5-100.5)/100.5
        assert abs(changes[2][2] - 0.00493) < 0.00001  # (102-101.5)/101.5

    def test_calculate_net_value_change_normal(self, recovery_tool):
        """测试正常净值变化计算"""
        net_value = recovery_tool._calculate_net_value_change(1.0, 0.02)  # 2%涨幅

        # 3倍做多，2%涨幅
        expected = 1.0 * (1 + 3 * 0.02)
        assert abs(net_value - expected) < 0.0001

    def test_calculate_net_value_change_with_rebalance(self, recovery_tool):
        """测试带再平衡的净值变化计算"""
        net_value = recovery_tool._calculate_net_value_change(1.0, 0.08)  # 8%涨幅

        # 应该触发一次再平衡（5%）+ 剩余3%
        expected = 1.0 * (1 + 3 * 0.05) * (1 + 3 * 0.03)
        assert abs(net_value - expected) < 0.0001

    def test_simple_recovery(self, recovery_tool):
        """测试简单恢复方法"""
        net_value, price, log = recovery_tool._simple_recovery(
            initial_net_value=1.0,
            last_price=100.0,
            current_price=105.0,  # 5%涨幅
            gap_seconds=300,  # 5分钟
            daily_fee=0.001,
        )

        # 验证分段计算
        assert log[-1]["method"] == "simple_segmented"
        assert log[-1]["segments"] == 5  # 5分钟分5段

        # 验证管理费扣除
        assert log[-1]["fee_deducted"] > 0

        # 验证净值合理性（3倍杠杆，5%涨幅，扣除管理费）
        assert net_value > 1.0 and net_value < 1.2

    def test_recover_with_short_gap(self, recovery_tool):
        """测试短时间断线恢复"""
        # Mock当前价格
        recovery_tool.spot_client.get_depth.return_value = {
            "bids": [["101.0", "100"]],
            "asks": [["101.2", "100"]],
        }

        net_value, price, log = recovery_tool.recover_net_value(
            initial_net_value=1.0,
            last_price=100.0,
            last_update_ts=time.time() - 30,  # 30秒前
            current_ts=time.time(),
            daily_fee=0.001,
        )

        assert log[0]["method"] == "linear_interpolation"
        assert price == 101.1  # (101.0 + 101.2) / 2
        assert net_value > 1.0  # 价格上涨，净值应该增加


def test_integration():
    """集成测试：模拟完整的使用场景"""
    # 这个测试需要Redis运行
    try:
        r = redis.Redis(host="localhost", port=6379, db=15)
        r.ping()
    except:
        pytest.skip("Redis not available")

    # 1. 创建计算器
    calc = ImprovedNetValue(symbol="test_usdt", m_lever=3, long=True, time_gap_second=1)
    calc.r = r
    calc.spot_client = MagicMock()

    # 2. 模拟价格更新
    prices = [100.0, 101.0, 102.0, 101.5, 103.0]
    for price in prices[:2]:
        calc.spot_client.get_depth.return_value = {
            "bids": [[str(price - 0.1), "100"]],
            "asks": [[str(price + 0.1), "100"]],
        }
        calc.underlying_mid_price_queue.put(price)

    # 3. 计算净值
    net_value = calc.cal_net_value()
    assert net_value is not None

    # 4. 保存数据
    calc.net_value_data["net_value"] = net_value
    calc.net_value_data["last_price"] = 101.0
    calc.net_value_data["last_update_ts"] = time.time()
    calc._save_to_redis(calc.net_value_data)

    # 5. 模拟重启
    new_calc = ImprovedNetValue(symbol="test_usdt", m_lever=3, long=True)
    new_calc.r = r

    # 6. 验证数据恢复
    assert abs(new_calc.net_value_data["net_value"] - net_value) < 0.0001

    # 清理
    r.flushdb()


if __name__ == "__main__":
    # 运行基本测试
    logger.info("开始测试改进版净值计算器...")

    # 可以使用pytest运行完整测试
    # pytest tests/test_net_value_improved.py -v

    # 或者运行简单的集成测试
    test_integration()
    logger.info("测试完成！")
