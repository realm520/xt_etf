"""
净值记录器 - 负责将净值数据批量写入PostgreSQL
支持异步批量写入、故障降级、数据恢复
"""

import logging
import asyncio
import time
from datetime import datetime, timezone
from typing import Dict, List, Optional, Any
from decimal import Decimal
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import insert
from sqlalchemy.exc import OperationalError, IntegrityError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
import os
from dotenv import load_dotenv

# 导入数据库模型
from .models import NetValueHistory, NetValueEvent, Base

# 加载环境变量
load_dotenv()

logger = logging.getLogger(__name__)


def to_naive_utc(dt: Any) -> datetime:
    """
    将任意时间格式转换为 naive UTC datetime（无时区信息）
    用于插入 PostgreSQL 的 TIMESTAMP WITHOUT TIME ZONE 字段
    """
    if dt is None:
        return datetime.now(timezone.utc).replace(tzinfo=None)

    if isinstance(dt, (int, float)):
        return datetime.fromtimestamp(dt, tz=timezone.utc).replace(tzinfo=None)

    if isinstance(dt, datetime):
        if dt.tzinfo is None:
            return dt
        return dt.astimezone(timezone.utc).replace(tzinfo=None)

    return datetime.now(timezone.utc).replace(tzinfo=None)


class NetValueRecorder:
    """净值记录器 - 异步批量写入PostgreSQL"""

    def __init__(
        self,
        strategy_name: str,
        batch_size: int = 40,
        flush_interval: float = 10.0,
        enable_persistence: bool = True,
        database_url: Optional[str] = None,
    ):
        """
        初始化净值记录器

        Args:
            strategy_name: 策略名称（如 stg3l）
            batch_size: 批量大小（默认40，约10秒4个策略的数据）
            flush_interval: 强制刷新间隔（秒）
            enable_persistence: 是否启用数据库持久化
            database_url: 数据库连接URL（可选）
        """
        self.strategy_name = strategy_name
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self.enable_persistence = enable_persistence

        # 内存缓冲区
        self._buffer: List[Dict] = []
        self._event_buffer: List[Dict] = []
        self._last_flush = time.time()
        self._lock = asyncio.Lock()

        # 数据库配置
        if enable_persistence:
            self.database_url = database_url or self._get_database_url()
            self._init_database()
        else:
            self.engine = None
            self.async_session_maker = None
            logger.info(f"NetValueRecorder({strategy_name}): 数据库持久化已禁用")

    def _get_database_url(self) -> str:
        """从环境变量获取数据库URL"""
        db_user = os.getenv("POSTGRES_USER", "postgres")
        db_password = os.getenv("POSTGRES_PASSWORD", "postgres")
        db_host = os.getenv("POSTGRES_HOST", "localhost")
        db_port = os.getenv("POSTGRES_PORT", "5432")
        db_name = os.getenv("POSTGRES_DB", "xt_etf")

        return f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    def _init_database(self):
        """初始化数据库连接"""
        try:
            self.engine = create_async_engine(
                self.database_url,
                echo=False,
                pool_size=5,
                max_overflow=10,
                pool_pre_ping=True,  # 连接池预检
                pool_recycle=3600,   # 1小时回收连接
            )

            self.async_session_maker = sessionmaker(
                self.engine,
                class_=AsyncSession,
                expire_on_commit=False,
            )

            logger.info(f"NetValueRecorder({self.strategy_name}): 数据库连接初始化成功")
        except Exception as e:
            logger.error(f"NetValueRecorder({self.strategy_name}): 数据库初始化失败: {e}")
            self.enable_persistence = False

    async def record_net_value(self, net_value_data: Dict):
        """
        记录净值数据（异步批量写入）

        Args:
            net_value_data: 净值数据字典，包含：
                - net_value: 净值（float/Decimal）
                - underlying_price: 标的价格（可选）
                - change_rate: 变化率（可选）
                - fee_deducted: 扣除的管理费（可选）
                - cumulative_fee: 累计管理费（可选）
                - rebalance_triggered: 是否触发再平衡（可选）
                - recorded_at: 记录时间（timestamp/datetime）
        """
        if not self.enable_persistence:
            return

        async with self._lock:
            self._buffer.append(net_value_data)

            # 触发条件：满批次 或 超过时间间隔
            should_flush = (
                len(self._buffer) >= self.batch_size or
                time.time() - self._last_flush >= self.flush_interval
            )

            if should_flush:
                await self._flush_to_db()

    async def record_event(self, event_data: Dict):
        """
        记录异常事件（异步写入）

        Args:
            event_data: 事件数据字典，包含：
                - event_type: 事件类型（price_spike/long_restart/recovery）
                - severity: 严重程度（low/medium/high/critical）
                - old_price: 旧价格（可选）
                - new_price: 新价格（可选）
                - change_rate: 变化率（可选）
                - gap_seconds: 间隔秒数（可选）
                - event_time: 事件时间（timestamp/datetime）
        """
        if not self.enable_persistence:
            return

        async with self._lock:
            self._event_buffer.append(event_data)

            # 事件立即写入（不等批量）
            await self._flush_events_to_db()

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type((OperationalError, IntegrityError)),
    )
    async def _flush_to_db(self):
        """批量写入净值数据到数据库（带重试）"""
        if not self._buffer:
            return

        records = self._buffer.copy()
        self._buffer.clear()
        self._last_flush = time.time()

        try:
            # 格式化数据
            formatted_records = [self._format_net_value_record(r) for r in records]

            async with self.async_session_maker() as session:
                # 批量插入
                await session.execute(
                    insert(NetValueHistory),
                    formatted_records
                )
                await session.commit()

                logger.debug(f"NetValueRecorder({self.strategy_name}): 成功写入 {len(records)} 条净值记录")

        except Exception as e:
            logger.error(f"NetValueRecorder({self.strategy_name}): 数据库写入失败: {e}")
            # 降级：数据已在Redis，不会丢失
            # 可以选择将失败的数据写入CSV作为备份
            raise

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=1, max=5),
        retry=retry_if_exception_type((OperationalError, IntegrityError)),
    )
    async def _flush_events_to_db(self):
        """写入异常事件到数据库（带重试）"""
        if not self._event_buffer:
            return

        events = self._event_buffer.copy()
        self._event_buffer.clear()

        try:
            # 格式化数据
            formatted_events = [self._format_event_record(e) for e in events]

            async with self.async_session_maker() as session:
                # 批量插入
                await session.execute(
                    insert(NetValueEvent),
                    formatted_events
                )
                await session.commit()

                logger.info(f"NetValueRecorder({self.strategy_name}): 成功写入 {len(events)} 条异常事件")

        except Exception as e:
            logger.error(f"NetValueRecorder({self.strategy_name}): 事件写入失败: {e}")
            raise

    def _format_net_value_record(self, data: Dict) -> Dict:
        """格式化净值记录为数据库格式"""
        # 解析策略信息
        symbol = data.get("symbol", "stg_usdt")
        leverage = data.get("leverage", 3)
        direction = "long" if data.get("long", True) else "short"

        return {
            "strategy_name": self.strategy_name,
            "symbol": symbol,
            "leverage": leverage,
            "direction": direction,
            "net_value": Decimal(str(data["net_value"])),
            "underlying_price": Decimal(str(data.get("underlying_price", 0))) if data.get("underlying_price") else None,
            "change_rate": Decimal(str(data.get("change_rate", 0))) if data.get("change_rate") else None,
            "price_change_rate": Decimal(str(data.get("price_change_rate", 0))) if data.get("price_change_rate") else None,
            "fee_deducted": Decimal(str(data.get("fee_deducted", 0))) if data.get("fee_deducted") else None,
            "cumulative_fee": Decimal(str(data.get("cumulative_fee", 0))) if data.get("cumulative_fee") else None,
            "rebalance_triggered": data.get("rebalance_triggered", False),
            "rebalance_count": data.get("rebalance_count", 0),
            "recorded_at": to_naive_utc(data.get("recorded_at", time.time())),
        }

    def _format_event_record(self, data: Dict) -> Dict:
        """格式化事件记录为数据库格式"""
        symbol = data.get("symbol", "stg_usdt")

        return {
            "strategy_name": self.strategy_name,
            "symbol": symbol,
            "event_type": data["event_type"],
            "severity": data.get("severity", "medium"),
            "old_price": Decimal(str(data.get("old_price", 0))) if data.get("old_price") else None,
            "new_price": Decimal(str(data.get("new_price", 0))) if data.get("new_price") else None,
            "change_rate": Decimal(str(data.get("change_rate", 0))) if data.get("change_rate") else None,
            "gap_seconds": data.get("gap_seconds"),
            "missed_intervals": data.get("missed_intervals"),
            "net_value_id": data.get("net_value_id"),
            "extra_data": data.get("extra_data"),
            "event_time": to_naive_utc(data.get("event_time", time.time())),
        }

    async def flush_all(self):
        """强制刷新所有缓冲数据（用于关闭前）"""
        if not self.enable_persistence:
            return

        async with self._lock:
            try:
                await self._flush_to_db()
                await self._flush_events_to_db()
                logger.info(f"NetValueRecorder({self.strategy_name}): 已刷新所有缓冲数据")
            except Exception as e:
                logger.error(f"NetValueRecorder({self.strategy_name}): 刷新失败: {e}")

    async def close(self):
        """关闭记录器（刷新缓冲并关闭数据库连接）"""
        await self.flush_all()

        if self.engine:
            await self.engine.dispose()
            logger.info(f"NetValueRecorder({self.strategy_name}): 已关闭数据库连接")
