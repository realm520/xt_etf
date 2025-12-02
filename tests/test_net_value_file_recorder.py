# -*- coding: utf-8 -*-
"""
净值文件记录器单元测试

测试功能:
1. 基本记录功能
2. 按日期分文件
3. 自动压缩
4. 按天轮转
5. 文件统计
"""

import os
import gzip
import tempfile
import pytest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch, MagicMock

from etf.storage.net_value_file_recorder import (
    NetValueFileRecorder,
    create_net_value_recorder,
)


class TestNetValueFileRecorder:
    """净值文件记录器测试"""

    def test_init_creates_directory(self):
        """测试初始化时自动创建目录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            data_dir = os.path.join(tmpdir, "nested", "dir")
            recorder = NetValueFileRecorder("test", data_dir=data_dir)
            
            assert os.path.exists(data_dir)
            recorder.close()

    def test_init_creates_file_with_header(self):
        """测试初始化时创建带表头的CSV文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 检查文件存在
            assert recorder.file_path.exists()
            
            # 检查表头
            with open(recorder.file_path, 'r', encoding='utf-8') as f:
                header = f.readline().strip()
                assert "timestamp" in header
                assert "net_value" in header
                assert "spot_price" in header
            
            recorder.close()

    def test_file_name_format(self):
        """测试文件名格式: strategy_YYYY-MM-DD.csv"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("stg3l", data_dir=tmpdir)
            
            today = datetime.now().strftime('%Y-%m-%d')
            expected_name = f"stg3l_{today}.csv"
            
            assert recorder.file_path.name == expected_name
            recorder.close()

    def test_record_basic(self):
        """测试基本记录功能"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=0)
            
            recorder.record(net_value=1.0, spot_price=100.0)
            recorder.record(net_value=1.01, spot_price=101.0)
            recorder.flush()
            
            # 检查文件内容
            with open(recorder.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # 1 header + 2 records
                assert len(lines) == 3
            
            recorder.close()

    def test_record_with_price_change_rate(self):
        """测试记录时自动计算价格变化率"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=0)
            
            recorder.record(net_value=1.0, spot_price=100.0)
            recorder.record(net_value=1.01, spot_price=102.0)  # 2% 上涨
            recorder.flush()
            
            # 检查最后一条记录
            last_record = recorder.get_last_record()
            assert last_record is not None
            assert float(last_record['price_change_rate']) == pytest.approx(0.02, rel=1e-4)
            
            recorder.close()

    def test_memory_buffer_limit(self):
        """测试内存缓存上限"""
        with tempfile.TemporaryDirectory() as tmpdir:
            max_records = 10
            recorder = NetValueFileRecorder(
                "test", 
                data_dir=tmpdir, 
                max_memory_records=max_records
            )
            
            # 写入超过上限的记录
            for i in range(20):
                recorder.record(net_value=1.0 + i * 0.01, spot_price=100.0 + i)
            
            # 内存中应该只有 max_records 条
            recent = recorder.get_recent_records(100)
            assert len(recent) == max_records
            
            recorder.close()

    def test_get_recent_records(self):
        """测试获取最近记录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            for i in range(5):
                recorder.record(net_value=1.0 + i * 0.01, spot_price=100.0 + i)
            
            # 获取最近3条
            recent = recorder.get_recent_records(3)
            assert len(recent) == 3
            
            # 获取全部
            all_records = recorder.get_recent_records(100)
            assert len(all_records) == 5
            
            recorder.close()

    def test_get_last_record(self):
        """测试获取最后一条记录"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 空记录器
            assert recorder.get_last_record() is None
            
            # 添加记录
            recorder.record(net_value=1.5, spot_price=150.0)
            
            last = recorder.get_last_record()
            assert last is not None
            assert float(last['net_value']) == pytest.approx(1.5, rel=1e-4)
            
            recorder.close()

    def test_flush_interval(self):
        """测试刷新间隔控制"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 设置很长的刷新间隔
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=3600)
            
            recorder.record(net_value=1.0, spot_price=100.0)
            
            # 检查文件只有表头（数据还在内存中）
            with open(recorder.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                assert len(lines) == 1  # 只有表头
            
            # 强制刷新
            recorder.flush()
            
            with open(recorder.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                assert len(lines) == 2  # 表头 + 1条记录
            
            recorder.close()


class TestDateRotation:
    """日期轮转测试"""

    def test_rotate_on_date_change(self):
        """测试日期变化时轮转文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 记录第一天的数据
            recorder.record(net_value=1.0, spot_price=100.0)
            first_file = recorder.file_path
            
            # 模拟日期变化
            tomorrow = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
            with patch.object(recorder, '_get_date_str', return_value=tomorrow):
                recorder.record(net_value=1.01, spot_price=101.0)
            
            # 应该创建新文件
            assert recorder.file_path != first_file
            assert tomorrow in recorder.file_path.name
            
            recorder.close()

    def test_multiple_files_created(self):
        """测试多天产生多个文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 模拟3天的数据
            dates = [
                datetime.now().strftime('%Y-%m-%d'),
                (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d'),
                (datetime.now() + timedelta(days=2)).strftime('%Y-%m-%d'),
            ]
            
            for date in dates:
                with patch.object(recorder, '_get_date_str', return_value=date):
                    recorder._rotate_file_if_needed()
                    recorder.record(net_value=1.0, spot_price=100.0)
                    recorder.flush()
            
            # 检查文件数量
            files = list(Path(tmpdir).glob("test_*.csv"))
            assert len(files) == 3
            
            recorder.close()


class TestCompression:
    """压缩功能测试"""

    def test_compress_file(self):
        """测试文件压缩"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 创建测试文件
            test_file = Path(tmpdir) / "test_2025-01-01.csv"
            test_content = "timestamp,net_value\n2025-01-01 10:00:00,1.0\n"
            test_file.write_text(test_content)
            
            # 压缩
            result = recorder._compress_file(test_file)
            
            assert result is True
            assert not test_file.exists()  # 原文件已删除
            
            gz_file = test_file.with_suffix('.csv.gz')
            assert gz_file.exists()
            
            # 验证压缩内容
            with gzip.open(gz_file, 'rt', encoding='utf-8') as f:
                content = f.read()
                assert content == test_content
            
            recorder.close()

    def test_compress_nonexistent_file(self):
        """测试压缩不存在的文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            nonexistent = Path(tmpdir) / "nonexistent.csv"
            result = recorder._compress_file(nonexistent)
            
            assert result is False
            recorder.close()

    def test_skip_already_compressed(self):
        """测试跳过已压缩的文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 创建 .gz 文件
            gz_file = Path(tmpdir) / "test.csv.gz"
            with gzip.open(gz_file, 'wt', encoding='utf-8') as f:
                f.write("test")
            
            result = recorder._compress_file(gz_file)
            
            assert result is False
            recorder.close()

    def test_auto_compress_old_files(self):
        """测试自动压缩旧文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder(
                "test", 
                data_dir=tmpdir,
                compress_after_days=1
            )
            
            # 创建昨天的文件
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            old_file = Path(tmpdir) / f"test_{yesterday}.csv"
            old_file.write_text("timestamp,net_value\n2025-01-01,1.0\n")
            
            # 触发清理
            recorder._cleanup_old_files()
            
            # 检查文件被压缩
            assert not old_file.exists()
            assert old_file.with_suffix('.csv.gz').exists()
            
            recorder.close()


class TestRetention:
    """数据保留测试"""

    def test_no_deletion_by_default(self):
        """测试默认不删除文件（retention_days=0）"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder(
                "test", 
                data_dir=tmpdir,
                retention_days=0,  # 永不删除
                compress_after_days=999  # 也不压缩
            )
            
            # 创建很旧的文件
            old_date = (datetime.now() - timedelta(days=100)).strftime('%Y-%m-%d')
            old_file = Path(tmpdir) / f"test_{old_date}.csv"
            old_file.write_text("test")
            
            # 触发清理
            recorder._cleanup_old_files()
            
            # 文件应该仍然存在
            assert old_file.exists()
            
            recorder.close()

    def test_deletion_when_retention_set(self):
        """测试设置retention_days时删除过期文件"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder(
                "test", 
                data_dir=tmpdir,
                retention_days=7,
                compress_after_days=999  # 禁用压缩以便测试删除
            )
            
            # 创建10天前的文件（超过保留期）
            old_date = (datetime.now() - timedelta(days=10)).strftime('%Y-%m-%d')
            old_file = Path(tmpdir) / f"test_{old_date}.csv"
            old_file.write_text("test")
            
            # 创建3天前的文件（在保留期内）
            recent_date = (datetime.now() - timedelta(days=3)).strftime('%Y-%m-%d')
            recent_file = Path(tmpdir) / f"test_{recent_date}.csv"
            recent_file.write_text("test")
            
            # 触发清理
            recorder._cleanup_old_files()
            
            # 旧文件被删除
            assert not old_file.exists()
            # 新文件保留
            assert recent_file.exists()
            
            recorder.close()


class TestFileStats:
    """文件统计测试"""

    def test_get_file_stats_empty(self):
        """测试空目录的统计"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            stats = recorder.get_file_stats()
            
            assert stats['csv_files'] == 1  # 当前文件
            assert stats['gz_files'] == 0
            assert stats['current_file'] is not None
            
            recorder.close()

    def test_get_file_stats_mixed(self):
        """测试混合文件类型的统计"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir)
            
            # 创建一些文件
            (Path(tmpdir) / "test_2025-01-01.csv").write_text("test")
            (Path(tmpdir) / "test_2025-01-02.csv").write_text("test")
            
            with gzip.open(Path(tmpdir) / "test_2024-12-31.csv.gz", 'wt') as f:
                f.write("test")
            
            stats = recorder.get_file_stats()
            
            assert stats['csv_files'] == 3  # 当前 + 2个历史
            assert stats['gz_files'] == 1
            assert stats['oldest_date'] == '2024-12-31'
            
            recorder.close()


class TestFactoryFunction:
    """工厂函数测试"""

    def test_create_net_value_recorder(self):
        """测试工厂函数创建记录器"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = create_net_value_recorder(
                strategy_name="stg3l",
                data_dir=tmpdir,
                flush_interval=30
            )
            
            assert isinstance(recorder, NetValueFileRecorder)
            assert recorder.strategy_name == "stg3l"
            assert recorder.flush_interval == 30
            
            recorder.close()


class TestThreadSafety:
    """线程安全测试"""

    def test_concurrent_records(self):
        """测试并发写入"""
        import threading
        
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=0)
            
            def write_records():
                for i in range(100):
                    recorder.record(net_value=1.0 + i * 0.001, spot_price=100.0 + i)
            
            threads = [threading.Thread(target=write_records) for _ in range(5)]
            
            for t in threads:
                t.start()
            for t in threads:
                t.join()
            
            recorder.flush()
            
            # 应该有500条记录（但内存缓存限制为1000）
            # 文件中应该有所有记录
            with open(recorder.file_path, 'r', encoding='utf-8') as f:
                lines = f.readlines()
                # 1 header + 500 records
                assert len(lines) == 501
            
            recorder.close()


class TestEdgeCases:
    """边界情况测试"""

    def test_special_characters_in_strategy_name(self):
        """测试策略名称中的特殊字符"""
        with tempfile.TemporaryDirectory() as tmpdir:
            # 使用合法的策略名称
            recorder = NetValueFileRecorder("stg_3l_test", data_dir=tmpdir)
            
            assert "stg_3l_test" in recorder.file_path.name
            recorder.close()

    def test_zero_net_value(self):
        """测试零净值"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=0)
            
            recorder.record(net_value=0.0, spot_price=100.0)
            recorder.flush()
            
            last = recorder.get_last_record()
            assert float(last['net_value']) == 0.0
            
            recorder.close()

    def test_negative_price_change(self):
        """测试负价格变化"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=0)
            
            recorder.record(net_value=1.0, spot_price=100.0)
            recorder.record(net_value=0.9, spot_price=90.0)  # -10%
            recorder.flush()
            
            last = recorder.get_last_record()
            assert float(last['price_change_rate']) == pytest.approx(-0.1, rel=1e-4)
            
            recorder.close()

    def test_old_price_parameter(self):
        """测试 old_price 参数"""
        with tempfile.TemporaryDirectory() as tmpdir:
            recorder = NetValueFileRecorder("test", data_dir=tmpdir, flush_interval=0)
            
            recorder.record(
                net_value=1.0, 
                spot_price=100.0,
                price_change_rate=0.05,
                old_price=95.0
            )
            recorder.flush()
            
            last = recorder.get_last_record()
            assert "p0=95.0000" in last['price_detail']
            assert "p1=100.0000" in last['price_detail']
            
            recorder.close()
