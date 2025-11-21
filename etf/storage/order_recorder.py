"""
订单记录器 - 负责记录所有订单和交易数据
支持异步写入PostgreSQL，带重试和CSV降级机制
"""

import logging
import json
import time
import asyncio
import pandas as pd
import os
from datetime import datetime, timezone, timedelta
from pathlib import Path
import aiofiles
import redis.asyncio as aioredis
from typing import Dict, List, Optional, Any
import threading
from queue import Queue
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update, insert
from sqlalchemy.exc import OperationalError, IntegrityError
from tenacity import (
    retry,
    stop_after_attempt,
    wait_exponential,
    retry_if_exception_type,
)
from dotenv import load_dotenv

# 导入数据库模型
from .models import Order as OrderModel, Trade as TradeModel, Base

# 加载环境变量
load_dotenv()

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


def ensure_utc_timezone(dt: Any) -> datetime:
    """
    确保 datetime 对象带有 UTC 时区
    Args:
        dt: datetime 对象或时间戳（可能是 str, int, float, datetime）
    Returns:
        带 UTC 时区的 datetime 对象
    """
    if dt is None:
        return datetime.now(timezone.utc)

    # 如果是字符串，尝试解析
    if isinstance(dt, str):
        try:
            # 尝试解析 ISO 格式
            parsed_dt = datetime.fromisoformat(dt.replace('Z', '+00:00'))
            if parsed_dt.tzinfo is None:
                return parsed_dt.replace(tzinfo=timezone.utc)
            return parsed_dt
        except:
            return datetime.now(timezone.utc)

    # 如果是时间戳数字
    if isinstance(dt, (int, float)):
        return datetime.fromtimestamp(dt, tz=timezone.utc)

    # 如果是 datetime 对象
    if isinstance(dt, datetime):
        # 如果没有时区信息，添加 UTC 时区
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        # 如果有时区信息，转换为 UTC
        return dt.astimezone(timezone.utc)

    # 其他情况返回当前时间
    return datetime.now(timezone.utc)


def to_naive_utc(dt: Any) -> datetime:
    """
    将任意时间格式转换为 naive UTC datetime（无时区信息）
    用于插入 PostgreSQL 的 TIMESTAMP WITHOUT TIME ZONE 字段
    
    Args:
        dt: datetime 对象或时间戳（可能是 str, int, float, datetime）
    Returns:
        naive UTC datetime 对象（无时区信息）
    """
    # 先确保带有UTC时区
    utc_dt = ensure_utc_timezone(dt)
    # 移除时区信息（保持UTC时间不变）
    return utc_dt.replace(tzinfo=None)


class OrderRecorder:
    """订单记录器 - 异步记录所有交易数据到PostgreSQL"""

    def __init__(
        self,
        db_url: Optional[str] = None,
        redis_url: Optional[str] = None,
    ):
        """
        初始化订单记录器
        Args:
            db_url: PostgreSQL数据库连接URL（可选，优先从环境变量读取）
            redis_url: Redis连接URL（可选，优先从环境变量读取）
        """
        # 从环境变量构建数据库URL
        if db_url is None:
            db_user = os.getenv("POSTGRES_USER", "etf_user")
            db_password = os.getenv("POSTGRES_PASSWORD", "etf_password")
            db_name = os.getenv("POSTGRES_DB", "etf_trading")
            db_host = os.getenv("POSTGRES_HOST", "localhost")
            db_port = os.getenv("POSTGRES_PORT", "5432")

            db_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

        self.db_url = db_url
        self.redis_url = redis_url or os.getenv("REDIS_URL", "redis://localhost:6379/0")

        # 异步队列用于批量写入
        self.order_queue = Queue(maxsize=10000)
        self.trade_queue = Queue(maxsize=10000)

        # 统计信息
        self.stats = {
            "total_orders": 0,
            "total_trades": 0,
            "real_orders": 0,
            "wash_orders": 0,
            "real_volume": 0.0,
            "wash_volume": 0.0,
            "db_write_success": 0,
            "db_write_failed": 0,
            "csv_fallback_count": 0,
        }

        # 启动标志
        self._running = False
        self._worker_thread = None

        # 数据库连接状态
        self.engine = None
        self.async_session = None
        self.redis = None
        self._db_available = False

        # CSV降级路径
        self.csv_dir = Path("logs/order_records")
        self.csv_dir.mkdir(parents=True, exist_ok=True)

    async def init_db(self):
        """初始化数据库连接"""
        try:
            # 创建异步数据库引擎
            self.engine = create_async_engine(
                self.db_url,
                echo=False,
                pool_size=20,
                max_overflow=10,
                pool_pre_ping=True,
                pool_recycle=3600,  # 1小时回收连接
            )

            # 创建异步会话工厂
            self.async_session = sessionmaker(
                self.engine, class_=AsyncSession, expire_on_commit=False
            )

            # 测试连接
            async with self.engine.begin() as conn:
                await conn.run_sync(Base.metadata.create_all)

            self._db_available = True
            logging.info(f"PostgreSQL连接成功: {self.db_url.split('@')[1]}")

        except Exception as e:
            self._db_available = False
            logging.error(f"PostgreSQL连接失败: {e}, 将使用CSV降级方案")

        # 注意：Redis连接现在在后台线程中初始化（通过initialize_in_loop方法）
        # 不在主线程初始化，避免事件循环冲突

    async def initialize_in_loop(self):
        """
        在后台事件循环中初始化Redis连接
        
        注意：此方法必须在后台线程的事件循环中调用，
        不能在主线程中调用，否则会导致事件循环冲突
        """
        try:
            self.redis = await aioredis.from_url(
                self.redis_url, encoding="utf-8", decode_responses=True
            )
            await self.redis.ping()
            logging.info("后台线程Redis连接成功")
        except Exception as e:
            logging.error(f"后台线程Redis连接失败: {e}, Redis缓存功能将被禁用")
            self.redis = None

    async def record_order(self, order_data: Dict[str, Any]):
        """
        记录订单数据
        Args:
            order_data: 订单数据字典
        """
        try:
            # 添加记录时间
            order_data["recorded_at"] = datetime.now(timezone.utc)

            # 更新统计
            self.stats["total_orders"] += 1
            if order_data.get("is_wash_trading", False):
                self.stats["wash_orders"] += 1
            else:
                self.stats["real_orders"] += 1

            # 放入队列等待批量写入
            self.order_queue.put_nowait(order_data)

            # 同时更新Redis缓存（实时数据）
            if self.redis:
                await self._update_redis_cache(order_data)

        except Exception as e:
            logging.error(f"记录订单失败: {e}, 订单数据: {order_data}")

    async def record_trade(self, trade_data: Dict[str, Any]):
        """
        记录成交数据
        Args:
            trade_data: 成交数据字典
        """
        try:
            # 添加记录时间
            trade_data["recorded_at"] = datetime.now(timezone.utc)

            # 更新统计
            self.stats["total_trades"] += 1
            volume = float(trade_data.get("quantity", 0)) * float(
                trade_data.get("price", 0)
            )

            if trade_data.get("is_wash_trading", False):
                self.stats["wash_volume"] += volume
            else:
                self.stats["real_volume"] += volume

            # 放入队列等待批量写入
            self.trade_queue.put_nowait(trade_data)

            # 更新Redis缓存
            if self.redis:
                await self._update_trade_cache(trade_data)

        except Exception as e:
            logging.error(f"记录成交失败: {e}, 成交数据: {trade_data}")

    async def _update_redis_cache(self, order_data: Dict[str, Any]):
        """更新Redis中的订单缓存"""
        if not self.redis:
            return

        try:
            # 存储最新订单信息
            order_id = order_data.get('order_id') or order_data.get('orderId', '')
            key = f"order:{order_data['symbol']}:{order_id}"
            await self.redis.hset(
                key,
                mapping={
                    k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    for k, v in order_data.items()
                },
            )
            await self.redis.expire(key, 86400)  # 1天过期

            # 更新统计信息
            stats_key = f"stats:{order_data['symbol']}:orders"
            await self.redis.hincrby(stats_key, "total", 1)
            if order_data.get("is_wash_trading", False):
                await self.redis.hincrby(stats_key, "wash", 1)
            else:
                await self.redis.hincrby(stats_key, "real", 1)

        except Exception as e:
            logging.error(f"更新Redis缓存失败: {e}")

    async def _update_trade_cache(self, trade_data: Dict[str, Any]):
        """更新Redis中的成交缓存"""
        if not self.redis:
            return

        try:
            # 存储最新成交信息
            key = f"trade:{trade_data['symbol']}:{trade_data['tradeId']}"
            await self.redis.hset(
                key,
                mapping={
                    k: json.dumps(v) if isinstance(v, (dict, list)) else str(v)
                    for k, v in trade_data.items()
                },
            )
            await self.redis.expire(key, 86400)

            # 更新成交量统计
            volume = float(trade_data.get("quantity", 0)) * float(
                trade_data.get("price", 0)
            )
            stats_key = f"stats:{trade_data['symbol']}:trades"

            await self.redis.hincrbyfloat(stats_key, "total_volume", volume)
            if trade_data.get("is_wash_trading", False):
                await self.redis.hincrbyfloat(stats_key, "wash_volume", volume)
            else:
                await self.redis.hincrbyfloat(stats_key, "real_volume", volume)

        except Exception as e:
            logging.error(f"更新成交缓存失败: {e}")

    async def get_real_volume_ratio(
        self, symbol: str, period_minutes: int = 60
    ) -> float:
        """
        获取真实交易量占比
        Args:
            symbol: 交易对
            period_minutes: 统计周期（分钟）
        Returns:
            真实交易量占总交易量的比例
        """
        if not self.redis:
            return 0.0

        try:
            stats_key = f"stats:{symbol}:trades"
            stats = await self.redis.hgetall(stats_key)

            total_volume = float(stats.get("total_volume", 0))
            real_volume = float(stats.get("real_volume", 0))

            if total_volume > 0:
                return real_volume / total_volume
            return 0.0

        except Exception as e:
            logging.error(f"获取真实交易量占比失败: {e}")
            return 0.0

    async def get_order_stats(self, symbol: str) -> Dict[str, Any]:
        """获取订单统计信息"""
        if not self.redis:
            return {}

        try:
            stats_key = f"stats:{symbol}:orders"
            stats = await self.redis.hgetall(stats_key)

            return {
                "total_orders": int(stats.get("total", 0)),
                "real_orders": int(stats.get("real", 0)),
                "wash_orders": int(stats.get("wash", 0)),
                "real_order_ratio": float(stats.get("real", 0))
                / max(1, int(stats.get("total", 1))),
            }

        except Exception as e:
            logging.error(f"获取订单统计失败: {e}")
            return {}

    def start(self):
        """启动后台工作线程"""
        if not self._running:
            self._running = True
            self._worker_thread = threading.Thread(target=self._run_worker, daemon=True)
            self._worker_thread.start()
            logging.info("订单记录器启动成功")

    def stop(self):
        """停止后台工作线程"""
        self._running = False
        if self._worker_thread:
            self._worker_thread.join(timeout=5)
        logging.info("订单记录器已停止")

    def _run_worker(self):
        """后台工作线程 - 批量写入数据"""
        asyncio.run(self._async_worker())

    async def _async_worker(self):
        """异步工作协程"""
        await self.init_db()

        while self._running:
            try:
                # 批量处理订单
                await self._batch_write_orders()

                # 批量处理成交
                await self._batch_write_trades()

                # 短暂休眠
                await asyncio.sleep(1)

            except Exception as e:
                logging.error(f"批量写入失败: {e}")
                await asyncio.sleep(5)

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OperationalError),
    )
    async def _batch_write_orders(self):
        """批量写入订单数据到PostgreSQL（带重试）"""
        orders = []

        # 从队列中获取订单（最多100条）
        while not self.order_queue.empty() and len(orders) < 100:
            try:
                order = self.order_queue.get_nowait()
                orders.append(order)
            except:
                break

        if not orders:
            return

        # 尝试写入PostgreSQL
        if self._db_available and self.async_session:
            try:
                async with self.async_session() as session:
                    # 转换为数据库模型格式
                    order_records = []
                    for order in orders:
                        # 获取时间戳并转换为naive UTC（用于PostgreSQL TIMESTAMP WITHOUT TIME ZONE）
                        timestamp = order.get("timestamp") or order.get("created_at")
                        created_at = to_naive_utc(timestamp)

                        record = {
                            "symbol": order.get("symbol"),
                            "order_id": order.get("order_id") or order.get("orderId", ""),
                            "client_order_id": order.get("client_order_id") or order.get("clientOrderId"),
                            "side": order.get("side"),
                            "order_type": order.get("order_type", "LIMIT"),
                            "price": float(order.get("price", 0)),
                            "quantity": float(order.get("quantity", 0)),
                            "status": order.get("status", "NEW"),
                            "filled_quantity": float(order.get("filled_quantity", 0)),
                            "strategy_name": order.get("strategy_name"),
                            "is_wash_trading": order.get("is_wash_trading", False),
                            "net_value": float(order.get("net_value")) if order.get("net_value") else None,
                            "bid_ask_spread": float(order.get("bid_ask_spread")) if order.get("bid_ask_spread") else None,
                            "best_bid": float(order.get("best_bid")) if order.get("best_bid") else None,
                            "best_ask": float(order.get("best_ask")) if order.get("best_ask") else None,
                            "created_at": created_at,
                        }
                        order_records.append(record)

                    # 使用bulk_insert_mappings提高性能
                    await session.execute(
                        insert(OrderModel).values(order_records)
                    )
                    await session.commit()

                    self.stats["db_write_success"] += len(orders)
                    logging.info(f"✅ 成功写入 {len(orders)} 条订单记录到PostgreSQL")
                    return

            except IntegrityError as e:
                # 唯一性约束冲突，尝试逐条插入
                logging.warning(f"批量插入订单遇到重复数据，尝试逐条插入: {e}")
                await self._insert_orders_one_by_one(orders)
                return

            except Exception as e:
                self.stats["db_write_failed"] += len(orders)
                logging.error(f"❌ PostgreSQL写入订单失败: {e}")
                # 标记数据库不可用，降级到CSV
                self._db_available = False

        # 降级到CSV文件
        await self._write_orders_to_csv(orders)

    async def _insert_orders_one_by_one(self, orders: List[Dict]):
        """逐条插入订单（处理重复数据）"""
        success_count = 0
        async with self.async_session() as session:
            for order in orders:
                try:
                    # 获取时间戳并转换为naive UTC（用于PostgreSQL TIMESTAMP WITHOUT TIME ZONE）
                    timestamp = order.get("timestamp") or order.get("created_at")
                    created_at = to_naive_utc(timestamp)

                    record = {
                        "symbol": order.get("symbol"),
                        "order_id": order.get("order_id") or order.get("orderId", ""),
                        "client_order_id": order.get("client_order_id") or order.get("clientOrderId"),
                        "side": order.get("side"),
                        "order_type": order.get("order_type", "LIMIT"),
                        "price": float(order.get("price", 0)),
                        "quantity": float(order.get("quantity", 0)),
                        "status": order.get("status", "NEW"),
                        "strategy_name": order.get("strategy_name"),
                        "is_wash_trading": order.get("is_wash_trading", False),
                        "created_at": created_at,
                    }
                    await session.execute(insert(OrderModel).values(record))
                    await session.commit()
                    success_count += 1
                except IntegrityError:
                    # 跳过重复数据
                    await session.rollback()
                    continue
                except Exception as e:
                    await session.rollback()
                    logging.error(f"插入单条订单失败: {e}")

        if success_count > 0:
            logging.info(f"✅ 逐条插入成功 {success_count}/{len(orders)} 条订单")

    async def _write_orders_to_csv(self, orders: List[Dict]):
        """降级方案：写入CSV文件"""
        try:
            df = pd.DataFrame(orders)
            csv_file = self.csv_dir / f"orders_{datetime.now().strftime('%Y%m%d')}.csv"

            if csv_file.exists():
                df.to_csv(csv_file, mode="a", header=False, index=False)
            else:
                df.to_csv(csv_file, index=False)

            self.stats["csv_fallback_count"] += len(orders)
            logging.info(f"📝 降级写入 {len(orders)} 条订单记录到CSV: {csv_file.name}")

        except Exception as e:
            logging.error(f"CSV写入订单失败: {e}")

    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10),
        retry=retry_if_exception_type(OperationalError),
    )
    async def _batch_write_trades(self):
        """批量写入成交数据到PostgreSQL（带重试）"""
        trades = []

        # 从队列中获取成交（最多100条）
        while not self.trade_queue.empty() and len(trades) < 100:
            try:
                trade = self.trade_queue.get_nowait()
                trades.append(trade)
            except:
                break

        if not trades:
            return

        # 尝试写入PostgreSQL
        if self._db_available and self.async_session:
            try:
                async with self.async_session() as session:
                    # 转换为数据库模型格式
                    trade_records = []
                    for trade in trades:
                        # 获取时间戳并转换为naive UTC（用于PostgreSQL TIMESTAMP WITHOUT TIME ZONE）
                        timestamp = trade.get("timestamp") or trade.get("traded_at")
                        traded_at = to_naive_utc(timestamp)

                        record = {
                            "symbol": trade.get("symbol"),
                            "trade_id": trade.get("tradeId") or trade.get("trade_id", ""),
                            "order_id": trade.get("orderId") or trade.get("order_id", ""),
                            "price": float(trade.get("price", 0)),
                            "quantity": float(trade.get("quantity", 0)),
                            "quote_quantity": float(trade.get("quoteQty", 0)) if trade.get("quoteQty") else None,
                            "fee": float(trade.get("fee", 0)),
                            "fee_asset": trade.get("fee_asset") or trade.get("feeCurrency"),
                            "is_maker": trade.get("is_maker", False),
                            "is_buyer": trade.get("is_buyer"),
                            "strategy_name": trade.get("strategy_name"),
                            "is_wash_trading": trade.get("is_wash_trading", False),
                            "traded_at": traded_at,
                        }
                        trade_records.append(record)

                    # 批量插入
                    await session.execute(
                        insert(TradeModel).values(trade_records)
                    )
                    await session.commit()

                    self.stats["db_write_success"] += len(trades)
                    logging.info(f"✅ 成功写入 {len(trades)} 条成交记录到PostgreSQL")
                    return

            except IntegrityError as e:
                logging.warning(f"批量插入成交遇到重复数据，尝试逐条插入: {e}")
                await self._insert_trades_one_by_one(trades)
                return

            except Exception as e:
                self.stats["db_write_failed"] += len(trades)
                logging.error(f"❌ PostgreSQL写入成交失败: {e}")
                self._db_available = False

        # 降级到CSV文件
        await self._write_trades_to_csv(trades)

    async def _insert_trades_one_by_one(self, trades: List[Dict]):
        """逐条插入成交（处理重复数据）"""
        success_count = 0
        async with self.async_session() as session:
            for trade in trades:
                try:
                    # 获取时间戳并转换为naive UTC（用于PostgreSQL TIMESTAMP WITHOUT TIME ZONE）
                    timestamp = trade.get("timestamp") or trade.get("traded_at")
                    traded_at = to_naive_utc(timestamp)

                    record = {
                        "symbol": trade.get("symbol"),
                        "trade_id": trade.get("tradeId") or trade.get("trade_id", ""),
                        "order_id": trade.get("orderId") or trade.get("order_id", ""),
                        "price": float(trade.get("price", 0)),
                        "quantity": float(trade.get("quantity", 0)),
                        "fee": float(trade.get("fee", 0)),
                        "strategy_name": trade.get("strategy_name"),
                        "is_wash_trading": trade.get("is_wash_trading", False),
                        "traded_at": traded_at,
                    }
                    await session.execute(insert(TradeModel).values(record))
                    await session.commit()
                    success_count += 1
                except IntegrityError:
                    await session.rollback()
                    continue
                except Exception as e:
                    await session.rollback()
                    logging.error(f"插入单条成交失败: {e}")

        if success_count > 0:
            logging.info(f"✅ 逐条插入成功 {success_count}/{len(trades)} 条成交")

    async def _write_trades_to_csv(self, trades: List[Dict]):
        """降级方案：写入CSV文件"""
        try:
            df = pd.DataFrame(trades)
            csv_file = self.csv_dir / f"trades_{datetime.now().strftime('%Y%m%d')}.csv"

            if csv_file.exists():
                df.to_csv(csv_file, mode="a", header=False, index=False)
            else:
                df.to_csv(csv_file, index=False)

            self.stats["csv_fallback_count"] += len(trades)
            logging.info(f"📝 降级写入 {len(trades)} 条成交记录到CSV: {csv_file.name}")

        except Exception as e:
            logging.error(f"CSV写入成交失败: {e}")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self.stats.copy()
        stats["db_available"] = self._db_available
        stats["queue_sizes"] = {
            "orders": self.order_queue.qsize(),
            "trades": self.trade_queue.qsize(),
        }
        return stats


# 全局单例
_recorder_instance = None


def get_order_recorder() -> OrderRecorder:
    """获取订单记录器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = OrderRecorder()
        _recorder_instance.start()
    return _recorder_instance
