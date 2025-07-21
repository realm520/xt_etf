#!/usr/bin/env python3
"""
测试 Redis last_amount 存储功能
"""

import os
import sys
import time
import redis
import unittest
from unittest.mock import Mock, patch

# 添加项目路径
sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.storage.redis_last_amount import RedisLastAmountStorage


class TestRedisLastAmount(unittest.TestCase):
    """测试 Redis last_amount 存储功能"""

    def setUp(self):
        """测试前设置"""
        self.redis_client = redis.Redis(
            host="localhost", port=6379, db=15
        )  # 使用测试数据库
        self.storage = RedisLastAmountStorage(
            redis_client=self.redis_client, prefix="test_last_amount"
        )

        # 清理测试数据
        for key in self.redis_client.scan_iter(match="test_last_amount:*"):
            self.redis_client.delete(key)

    def tearDown(self):
        """测试后清理"""
        # 清理测试数据
        for key in self.redis_client.scan_iter(match="test_last_amount:*"):
            self.redis_client.delete(key)

    def test_set_and_get_last_amount(self):
        """测试基本的存储和获取功能"""
        symbol = "stg3l_usdt"
        amount = 12345.67

        # 存储
        success = self.storage.set_last_amount(symbol, amount)
        self.assertTrue(success)

        # 获取
        retrieved_amount = self.storage.get_last_amount(symbol)
        self.assertEqual(retrieved_amount, amount)

    def test_get_nonexistent_amount(self):
        """测试获取不存在的数据"""
        amount = self.storage.get_last_amount("nonexistent_symbol")
        self.assertIsNone(amount)

    def test_set_with_metadata(self):
        """测试带元数据的存储"""
        symbol = "stg5s_usdt"
        amount = 98765.43
        delta_amount = -100.5
        mid_price = 1.234

        # 存储带元数据
        success = self.storage.set_last_amount(
            symbol,
            amount,
            delta_amount=delta_amount,
            mid_price=mid_price,
            custom_field="test_value",
        )
        self.assertTrue(success)

        # 获取详细信息
        detail = self.storage.get_last_amount_detail(symbol)
        self.assertIsNotNone(detail)
        self.assertEqual(detail["amount"], amount)
        self.assertEqual(detail["delta_amount"], delta_amount)
        self.assertEqual(detail["mid_price"], mid_price)
        self.assertEqual(detail["custom_field"], "test_value")
        self.assertIn("timestamp", detail)

    def test_update_existing_amount(self):
        """测试更新已存在的数据"""
        symbol = "stg3s_usdt"

        # 第一次存储
        self.storage.set_last_amount(symbol, 1000.0)

        # 更新
        new_amount = 2000.0
        success = self.storage.set_last_amount(symbol, new_amount)
        self.assertTrue(success)

        # 验证更新
        retrieved_amount = self.storage.get_last_amount(symbol)
        self.assertEqual(retrieved_amount, new_amount)

    def test_delete_last_amount(self):
        """测试删除功能"""
        symbol = "stg5l_usdt"

        # 存储
        self.storage.set_last_amount(symbol, 5000.0)

        # 验证存在
        self.assertIsNotNone(self.storage.get_last_amount(symbol))

        # 删除
        success = self.storage.delete_last_amount(symbol)
        self.assertTrue(success)

        # 验证删除
        self.assertIsNone(self.storage.get_last_amount(symbol))

    def test_get_all_symbols(self):
        """测试获取所有symbol"""
        symbols_data = {
            "stg3l_usdt": 1000.0,
            "stg3s_usdt": 2000.0,
            "stg5l_usdt": 3000.0,
            "stg5s_usdt": 4000.0,
        }

        # 存储多个symbol
        for symbol, amount in symbols_data.items():
            self.storage.set_last_amount(symbol, amount)

        # 获取所有symbol
        all_symbols = self.storage.get_all_symbols()
        self.assertEqual(len(all_symbols), 4)
        for symbol in symbols_data.keys():
            self.assertIn(symbol, all_symbols)

    def test_health_check(self):
        """测试健康检查"""
        # 正常情况应该返回True
        self.assertTrue(self.storage.health_check())

        # 模拟Redis连接失败
        with patch.object(
            self.storage.redis, "ping", side_effect=Exception("Connection failed")
        ):
            self.assertFalse(self.storage.health_check())

    def test_data_expiration(self):
        """测试数据过期设置"""
        symbol = "test_expire"
        amount = 1000.0

        # 存储数据
        self.storage.set_last_amount(symbol, amount)

        # 检查TTL（应该接近30天）
        detail_key = self.storage._get_detail_key(symbol)
        ttl = self.redis_client.ttl(detail_key)
        self.assertGreater(ttl, 29 * 24 * 60 * 60)  # 大于29天
        self.assertLessEqual(ttl, 30 * 24 * 60 * 60)  # 小于等于30天

    def test_redis_failure_handling(self):
        """测试Redis故障处理"""
        symbol = "test_failure"
        amount = 5000.0

        # 模拟Redis写入失败
        with patch.object(
            self.storage.redis, "set", side_effect=Exception("Redis error")
        ):
            success = self.storage.set_last_amount(symbol, amount)
            self.assertFalse(success)

        # 模拟Redis读取失败
        with patch.object(
            self.storage.redis, "get", side_effect=Exception("Redis error")
        ):
            retrieved = self.storage.get_last_amount(symbol)
            self.assertIsNone(retrieved)


class TestRedisLastAmountIntegration(unittest.TestCase):
    """集成测试：测试与 hedging_aggregation.py 的集成"""

    @patch("redis.Redis")
    def test_fallback_mechanism(self, mock_redis_class):
        """测试故障恢复机制"""
        # 设置mock
        mock_redis = Mock()
        mock_redis_class.return_value = mock_redis

        # 模拟Redis完全失败
        mock_redis.get.side_effect = Exception("Redis connection failed")
        mock_redis.set.side_effect = Exception("Redis connection failed")
        mock_redis.ping.side_effect = Exception("Redis connection failed")

        storage = RedisLastAmountStorage(redis_client=mock_redis)

        # 测试读取失败返回None
        amount = storage.get_last_amount("stg3l_usdt")
        self.assertIsNone(amount)

        # 测试写入失败返回False
        success = storage.set_last_amount("stg3l_usdt", 1000.0)
        self.assertFalse(success)

        # 测试健康检查失败
        self.assertFalse(storage.health_check())


if __name__ == "__main__":
    # 检查Redis是否运行
    try:
        test_redis = redis.Redis(host="localhost", port=6379, db=15)
        test_redis.ping()
        print("Redis is running. Starting tests...")
    except:
        print("WARNING: Redis is not running. Some tests may fail.")
        print("Please start Redis with: redis-server")

    unittest.main(verbosity=2)
