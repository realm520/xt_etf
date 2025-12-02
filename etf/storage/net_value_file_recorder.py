# -*- coding: utf-8 -*-
"""
净值文件记录器 - 定期将净值数据保存到文件

格式: CSV
字段: timestamp, net_value, spot_price, price_change_rate
示例: 2025-01-20 10:30:00, 1.023456, 1.5025, 0.000123

Author: Claude
Date: 2025-01-20
"""

import os
import csv
import time
import gzip
import shutil
import logging
from datetime import datetime
from pathlib import Path
from typing import Optional, Dict
from threading import Lock
from collections import deque

logger = logging.getLogger(__name__)


class NetValueFileRecorder:
    """
    净值文件记录器
    
    特点:
    - 定期保存到CSV文件（默认60秒）
    - 按日期分文件: data/net_value/{strategy_name}_{date}.csv
    - 自动压缩过期文件为 .gz 格式
    - 按天轮转，自动清理过期文件
    - 内存缓存最近1000条记录
    - 线程安全
    """
    
    def __init__(
        self,
        strategy_name: str,
        data_dir: str = "data/net_value",
        flush_interval: int = 60,  # 默认60秒保存一次
        max_memory_records: int = 1000,
        retention_days: int = 0,  # 保留天数（0表示永不删除）
        compress_after_days: int = 1,  # 多少天后压缩
    ):
        """
        初始化文件记录器
        
        Args:
            strategy_name: 策略名称（如 ton3l）
            data_dir: 数据目录
            flush_interval: 刷新间隔（秒）
            max_memory_records: 内存保留的最大记录数
            retention_days: 保留天数（0表示永不删除）
            compress_after_days: 多少天后压缩文件
        """
        self.strategy_name = strategy_name
        self.data_dir = Path(data_dir)
        self.flush_interval = flush_interval
        self.max_memory_records = max_memory_records
        self.retention_days = retention_days
        self.compress_after_days = compress_after_days
        
        # 确保目录存在
        self.data_dir.mkdir(parents=True, exist_ok=True)
        
        # 当前日期和文件路径
        self._current_date: str = ""
        self._file_path: Optional[Path] = None
        
        # 内存缓存
        self._buffer: deque = deque(maxlen=max_memory_records)
        self._pending_writes: list = []  # 待写入的记录
        self._lock = Lock()
        self._last_flush_time = time.time()
        self._last_cleanup_date: str = ""  # 上次清理日期
        
        # 上一次记录的价格（用于计算变化率）
        self._last_price: Optional[float] = None
        
        # 初始化当天文件
        self._rotate_file_if_needed()
        
        logger.info(f"净值文件记录器已初始化: {self._file_path}, 保留{retention_days}天, {compress_after_days}天后压缩")
    
    def _get_date_str(self) -> str:
        """获取当前日期字符串"""
        return datetime.now().strftime('%Y-%m-%d')
    
    def _get_file_path_for_date(self, date_str: str) -> Path:
        """获取指定日期的文件路径"""
        return self.data_dir / f"{self.strategy_name}_{date_str}.csv"
    
    def _rotate_file_if_needed(self) -> bool:
        """
        检查是否需要轮转文件（日期变化时）
        
        Returns:
            是否发生了轮转
        """
        current_date = self._get_date_str()
        
        if current_date != self._current_date:
            # 先刷新旧文件的数据
            if self._pending_writes and self._file_path:
                self._flush_to_file()
            
            # 更新日期和文件路径
            old_date = self._current_date
            self._current_date = current_date
            self._file_path = self._get_file_path_for_date(current_date)
            
            # 初始化新文件
            self._init_file()
            
            if old_date:
                logger.info(f"净值文件已轮转: {old_date} → {current_date}")
            
            # 执行清理（每天一次）
            if current_date != self._last_cleanup_date:
                self._cleanup_old_files()
                self._last_cleanup_date = current_date
            
            return True
        
        return False
    
    def _init_file(self):
        """初始化CSV文件（写入表头）"""
        if self._file_path and not self._file_path.exists():
            with open(self._file_path, 'w', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                writer.writerow([
                    'timestamp',
                    'net_value',
                    'spot_price',
                    'price_change_rate',
                    'price_detail'  # 格式: p0=xxx → p1=xxx, 变化率=xxx
                ])
            logger.info(f"创建净值记录文件: {self._file_path}")
    
    def _compress_file(self, file_path: Path) -> bool:
        """
        压缩CSV文件为 .gz 格式
        
        Args:
            file_path: 要压缩的文件路径
            
        Returns:
            是否压缩成功
        """
        if not file_path.exists() or file_path.suffix == '.gz':
            return False
        
        gz_path = file_path.with_suffix('.csv.gz')
        
        try:
            with open(file_path, 'rb') as f_in:
                with gzip.open(gz_path, 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            
            # 压缩成功后删除原文件
            file_path.unlink()
            logger.info(f"已压缩净值文件: {file_path.name} → {gz_path.name}")
            return True
            
        except Exception as e:
            logger.error(f"压缩文件失败 {file_path}: {e}")
            # 如果压缩失败，删除可能不完整的 gz 文件
            if gz_path.exists():
                gz_path.unlink()
            return False
    
    def _cleanup_old_files(self):
        """清理过期文件和压缩旧文件"""
        today = datetime.now().date()
        
        # 遍历目录中的所有文件
        for file_path in self.data_dir.glob(f"{self.strategy_name}_*.csv*"):
            try:
                # 从文件名提取日期
                # 格式: strategy_name_YYYY-MM-DD.csv 或 .csv.gz
                name = file_path.name
                if name.endswith('.csv.gz'):
                    date_str = name.replace(f"{self.strategy_name}_", "").replace(".csv.gz", "")
                else:
                    date_str = name.replace(f"{self.strategy_name}_", "").replace(".csv", "")
                
                file_date = datetime.strptime(date_str, '%Y-%m-%d').date()
                days_old = (today - file_date).days
                
                # 删除过期文件（仅当 retention_days > 0 时）
                if self.retention_days > 0 and days_old > self.retention_days:
                    file_path.unlink()
                    logger.info(f"已删除过期净值文件: {file_path.name} ({days_old}天前)")
                
                # 压缩旧文件（未压缩的）
                elif days_old >= self.compress_after_days and file_path.suffix == '.csv':
                    self._compress_file(file_path)
                    
            except (ValueError, IndexError) as e:
                # 文件名格式不匹配，跳过
                logger.debug(f"跳过非标准文件: {file_path.name}")
                continue
            except Exception as e:
                logger.error(f"清理文件时出错 {file_path}: {e}")
    
    @property
    def file_path(self) -> Optional[Path]:
        """当前文件路径（兼容旧代码）"""
        return self._file_path
    
    def record(
        self,
        net_value: float,
        spot_price: float,
        price_change_rate: Optional[float] = None,
        old_price: Optional[float] = None,
    ):
        """
        记录一条净值数据
        
        Args:
            net_value: 当前净值
            spot_price: 现货价格
            price_change_rate: 价格变化率（可选，会自动计算）
            old_price: 旧价格（可选，用于详情显示）
        """
        timestamp = datetime.now()
        
        # 检查是否需要轮转文件
        self._rotate_file_if_needed()
        
        # 计算价格变化率（如果未提供）
        if price_change_rate is None and self._last_price is not None:
            price_change_rate = (spot_price - self._last_price) / self._last_price
        elif price_change_rate is None:
            price_change_rate = 0.0
        
        # 构建价格详情字符串
        if old_price is not None:
            price_detail = f"p0={old_price:.4f} → p1={spot_price:.4f}, 变化率={price_change_rate:.6f}"
        elif self._last_price is not None:
            price_detail = f"p0={self._last_price:.4f} → p1={spot_price:.4f}, 变化率={price_change_rate:.6f}"
        else:
            price_detail = f"p0=N/A → p1={spot_price:.4f}, 变化率={price_change_rate:.6f}"
        
        record = {
            'timestamp': timestamp.strftime('%Y-%m-%d %H:%M:%S'),
            'net_value': f"{net_value:.6f}",
            'spot_price': f"{spot_price:.4f}",
            'price_change_rate': f"{price_change_rate:.6f}",
            'price_detail': price_detail,
        }
        
        with self._lock:
            # 添加到内存缓存
            self._buffer.append(record)
            # 添加到待写入队列
            self._pending_writes.append(record)
            # 更新上一次价格
            self._last_price = spot_price
            
            # 检查是否需要刷新到文件
            if time.time() - self._last_flush_time >= self.flush_interval:
                self._flush_to_file()
    
    def _flush_to_file(self):
        """将待写入的记录刷新到文件"""
        if not self._pending_writes or not self._file_path:
            return
        
        try:
            with open(self._file_path, 'a', newline='', encoding='utf-8') as f:
                writer = csv.writer(f)
                for record in self._pending_writes:
                    writer.writerow([
                        record['timestamp'],
                        record['net_value'],
                        record['spot_price'],
                        record['price_change_rate'],
                        record['price_detail'],
                    ])
            
            count = len(self._pending_writes)
            self._pending_writes.clear()
            self._last_flush_time = time.time()
            
            logger.debug(f"已写入 {count} 条净值记录到文件: {self._file_path}")
            
        except Exception as e:
            logger.error(f"写入净值文件失败: {e}")
    
    def flush(self):
        """强制刷新到文件（用于程序退出时）"""
        with self._lock:
            self._flush_to_file()
        logger.info(f"净值记录器已刷新: {self._file_path}")
    
    def get_recent_records(self, count: int = 100) -> list:
        """获取最近的记录"""
        with self._lock:
            records = list(self._buffer)
            return records[-count:] if len(records) > count else records
    
    def get_last_record(self) -> Optional[Dict]:
        """获取最后一条记录"""
        with self._lock:
            if self._buffer:
                return self._buffer[-1]
            return None
    
    def get_file_stats(self) -> Dict:
        """
        获取文件统计信息
        
        Returns:
            包含文件数量、总大小等信息的字典
        """
        stats = {
            'current_file': str(self._file_path) if self._file_path else None,
            'csv_files': 0,
            'gz_files': 0,
            'total_size_bytes': 0,
            'oldest_date': None,
            'newest_date': None,
        }
        
        dates = []
        for file_path in self.data_dir.glob(f"{self.strategy_name}_*.csv*"):
            stats['total_size_bytes'] += file_path.stat().st_size
            
            if file_path.suffix == '.gz':
                stats['gz_files'] += 1
            else:
                stats['csv_files'] += 1
            
            # 提取日期
            try:
                name = file_path.name
                if name.endswith('.csv.gz'):
                    date_str = name.replace(f"{self.strategy_name}_", "").replace(".csv.gz", "")
                else:
                    date_str = name.replace(f"{self.strategy_name}_", "").replace(".csv", "")
                dates.append(date_str)
            except:
                pass
        
        if dates:
            dates.sort()
            stats['oldest_date'] = dates[0]
            stats['newest_date'] = dates[-1]
        
        return stats
    
    def close(self):
        """关闭记录器（刷新所有数据）"""
        self.flush()
        logger.info(f"净值文件记录器已关闭: {self.strategy_name}")


# 便捷函数：创建记录器
def create_net_value_recorder(
    strategy_name: str,
    data_dir: str = "data/net_value",
    flush_interval: int = 60,
) -> NetValueFileRecorder:
    """
    创建净值文件记录器
    
    Args:
        strategy_name: 策略名称
        data_dir: 数据目录
        flush_interval: 刷新间隔（秒）
        
    Returns:
        NetValueFileRecorder 实例
    """
    return NetValueFileRecorder(
        strategy_name=strategy_name,
        data_dir=data_dir,
        flush_interval=flush_interval,
    )
