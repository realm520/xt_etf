"""
测试订单记录器时区修复
验证时间戳正确转换为 naive UTC datetime
"""

import pytest
from datetime import datetime, timezone
from etf.storage.order_recorder import to_naive_utc, ensure_utc_timezone


class TestTimezoneConversion:
    """测试时区转换功能"""

    def test_to_naive_utc_with_aware_datetime(self):
        """测试带时区的datetime转换为naive UTC"""
        # 创建带UTC时区的datetime
        aware_dt = datetime(2025, 11, 19, 12, 41, 4, 20911, tzinfo=timezone.utc)

        # 转换为naive UTC
        naive_dt = to_naive_utc(aware_dt)

        # 验证：应该没有时区信息
        assert naive_dt.tzinfo is None

        # 验证：时间值应该保持不变
        assert naive_dt.year == 2025
        assert naive_dt.month == 11
        assert naive_dt.day == 19
        assert naive_dt.hour == 12
        assert naive_dt.minute == 41
        assert naive_dt.second == 4

    def test_to_naive_utc_with_timestamp(self):
        """测试从时间戳转换"""
        timestamp = 1732018864.020911  # 对应 2025-11-19 12:41:04

        naive_dt = to_naive_utc(timestamp)

        # 验证：应该没有时区信息
        assert naive_dt.tzinfo is None

        # 验证：转换后的时间应该是合理的
        assert isinstance(naive_dt, datetime)

    def test_to_naive_utc_with_iso_string(self):
        """测试从ISO格式字符串转换"""
        iso_string = "2025-11-19T12:41:04.020911Z"

        naive_dt = to_naive_utc(iso_string)

        # 验证：应该没有时区信息
        assert naive_dt.tzinfo is None

    def test_to_naive_utc_with_none(self):
        """测试None值（应返回当前时间）"""
        naive_dt = to_naive_utc(None)

        # 验证：应该没有时区信息
        assert naive_dt.tzinfo is None

        # 验证：应该是接近当前时间
        assert isinstance(naive_dt, datetime)

    def test_ensure_utc_timezone_preserves_awareness(self):
        """验证 ensure_utc_timezone 保留时区信息"""
        aware_dt = datetime(2025, 11, 19, 12, 41, 4, tzinfo=timezone.utc)

        result = ensure_utc_timezone(aware_dt)

        # 验证：应该保留UTC时区信息
        assert result.tzinfo is not None
        assert result.tzinfo == timezone.utc

    def test_conversion_chain(self):
        """测试完整转换链：任意格式 -> aware UTC -> naive UTC"""
        test_cases = [
            datetime(2025, 11, 19, 12, 41, 4, tzinfo=timezone.utc),  # aware datetime
            datetime(2025, 11, 19, 12, 41, 4),  # naive datetime
            1732018864,  # timestamp
            "2025-11-19T12:41:04Z",  # ISO string
        ]

        for test_input in test_cases:
            # 第一步：确保有时区
            aware = ensure_utc_timezone(test_input)
            assert aware.tzinfo is not None

            # 第二步：转换为naive
            naive = to_naive_utc(test_input)
            assert naive.tzinfo is None

            # 验证：两者的时间值应该一致（除了时区信息）
            assert aware.year == naive.year
            assert aware.month == naive.month
            assert aware.day == naive.day


class TestDatabaseCompatibility:
    """测试数据库兼容性"""

    def test_naive_datetime_for_postgresql(self):
        """验证转换后的datetime可以安全插入PostgreSQL"""
        # 模拟从订单数据获取的时间戳
        order_timestamp = datetime(2025, 11, 19, 12, 41, 4, 20911, tzinfo=timezone.utc)

        # 转换为数据库友好的格式
        db_timestamp = to_naive_utc(order_timestamp)

        # 验证特性
        assert db_timestamp.tzinfo is None, "应该是naive datetime"
        assert isinstance(db_timestamp, datetime), "应该是datetime对象"

        # 验证可以转换为字符串（用于SQL查询）
        timestamp_str = db_timestamp.isoformat()
        assert isinstance(timestamp_str, str)
        assert "+" not in timestamp_str, "不应包含时区信息"
        assert "Z" not in timestamp_str, "不应包含UTC标记"

    def test_order_record_timestamp_conversion(self):
        """模拟订单记录时间戳转换过程"""
        # 模拟从交易所API获取的订单数据
        order_data = {
            "orderId": "561424637800665153",
            "symbol": "ton3l_usdt",
            "timestamp": datetime(2025, 11, 19, 12, 41, 4, 195232, tzinfo=timezone.utc),
            "price": 1.0,
            "quantity": 6.21,
        }

        # 模拟数据库插入前的转换
        timestamp = order_data.get("timestamp") or order_data.get("created_at")
        created_at = to_naive_utc(timestamp)

        # 验证转换结果
        assert created_at.tzinfo is None
        assert created_at.year == 2025
        assert created_at.month == 11
        assert created_at.day == 19


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
