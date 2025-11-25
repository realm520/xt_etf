"""
订单记录器 - 负责记录所有订单和交易数据
支持异步写入PostgreSQL，带重试机制
"""

import logging
import json
import time
import asyncio
import os
from datetime import datetime, timezone, timedelta
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

        # 统计信息（按订单用途分类）
        self.stats = {
            "total_orders": 0,
            "total_trades": 0,
            "market_making_orders": 0,
            "anti_pin_orders": 0,
            "wash_trading_orders": 0,
            "hedging_orders": 0,
            "market_making_volume": 0.0,
            "anti_pin_volume": 0.0,
            "wash_trading_volume": 0.0,
            "hedging_volume": 0.0,
            "db_write_success": 0,
            "db_write_failed": 0,
        }

        # 启动标志
        self._running = False
        self._worker_thread = None

        # 数据库连接状态
        self.engine = None
        self.async_session = None
        self.redis = None
        self._db_available = False

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
            logging.error(f"PostgreSQL连接失败: {e}, 订单数据将暂存于内存队列")

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
            
            # 根据订单用途更新统计
            order_purpose = order_data.get("order_purpose", "market_making")
            purpose_key = f"{order_purpose}_orders"
            if purpose_key in self.stats:
                self.stats[purpose_key] += 1

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

            # 根据交易用途更新统计
            trade_purpose = trade_data.get("trade_purpose", "market_making")
            volume_key = f"{trade_purpose}_volume"
            if volume_key in self.stats:
                self.stats[volume_key] += volume

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
            
            # 根据订单用途更新Redis统计
            order_purpose = order_data.get("order_purpose", "market_making")
            await self.redis.hincrby(stats_key, order_purpose, 1)

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
            
            # 根据交易用途更新Redis成交量统计
            trade_purpose = trade_data.get("trade_purpose", "market_making")
            volume_key = f"{trade_purpose}_volume"
            await self.redis.hincrbyfloat(stats_key, volume_key, volume)

        except Exception as e:
            logging.error(f"更新成交缓存失败: {e}")

    async def get_trade_volume_stats(self, symbol: str) -> Dict[str, Any]:
        """
        获取成交量统计信息（按交易用途分类）
        Args:
            symbol: 交易对
        Returns:
            按交易用途分类的成交量统计
        """
        if not self.redis:
            return {}

        try:
            stats_key = f"stats:{symbol}:trades"
            stats = await self.redis.hgetall(stats_key)

            total_volume = float(stats.get("total_volume", 0))
            
            return {
                "total_volume": total_volume,
                "market_making_volume": float(stats.get("market_making_volume", 0)),
                "anti_pin_volume": float(stats.get("anti_pin_volume", 0)),
                "wash_trading_volume": float(stats.get("wash_trading_volume", 0)),
                "hedging_volume": float(stats.get("hedging_volume", 0)),
                "market_making_ratio": float(stats.get("market_making_volume", 0)) / max(0.01, total_volume),
                "wash_trading_ratio": float(stats.get("wash_trading_volume", 0)) / max(0.01, total_volume),
            }

        except Exception as e:
            logging.error(f"获取成交量统计失败: {e}")
            return {}

    async def get_order_stats(self, symbol: str) -> Dict[str, Any]:
        """获取订单统计信息（按订单用途分类）"""
        if not self.redis:
            return {}

        try:
            stats_key = f"stats:{symbol}:orders"
            stats = await self.redis.hgetall(stats_key)

            total = int(stats.get("total", 0))
            
            return {
                "total_orders": total,
                "market_making_orders": int(stats.get("market_making", 0)),
                "anti_pin_orders": int(stats.get("anti_pin", 0)),
                "wash_trading_orders": int(stats.get("wash_trading", 0)),
                "hedging_orders": int(stats.get("hedging", 0)),
                "market_making_ratio": int(stats.get("market_making", 0)) / max(1, total),
                "wash_trading_ratio": int(stats.get("wash_trading", 0)) / max(1, total),
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
                            "order_purpose": order.get("order_purpose", "market_making"),
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
                # 标记数据库不可用
                self._db_available = False

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
                        "order_purpose": order.get("order_purpose", "market_making"),
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
                            "trade_purpose": trade.get("trade_purpose", "market_making"),
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
                        "trade_purpose": trade.get("trade_purpose", "market_making"),
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

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        stats = self.stats.copy()
        stats["db_available"] = self._db_available
        stats["queue_sizes"] = {
            "orders": self.order_queue.qsize(),
            "trades": self.trade_queue.qsize(),
        }
        return stats

    async def sync_order_status_from_exchange(
        self,
        exchange_orders: List[Dict[str, Any]],
        symbol: str,
        strategy_name: str
    ) -> Dict[str, int]:
        """
        从交易所同步订单状态到数据库
        
        用途：
        1. 启动时同步 - 确保数据库状态与交易所一致
        2. 定期轮询 - 补充WebSocket可能遗漏的更新
        
        Args:
            exchange_orders: 交易所返回的订单列表
            symbol: 交易对
            strategy_name: 策略名称
            
        Returns:
            统计信息 {
                "synced": 同步成功数量,
                "created": 新创建数量,
                "updated": 更新状态数量,
                "skipped": 跳过数量
            }
        """
        from .order_states import OrderStatusManager
        
        stats = {"synced": 0, "created": 0, "updated": 0, "skipped": 0}
        
        if not self._db_available or not self.async_session:
            logging.warning("数据库不可用，无法同步订单状态")
            return stats
            
        try:
            async with self.async_session() as session:
                for order in exchange_orders:
                    order_id = order.get("orderId")
                    exchange_status = order.get("state")  # XT交易所使用state字段
                    
                    # 查询数据库中的订单
                    result = await session.execute(
                        select(OrderModel).where(OrderModel.order_id == order_id)
                    )
                    db_order = result.scalar_one_or_none()
                    
                    if db_order is None:
                        # 数据库中不存在，创建新记录（可能是启动前创建的）
                        created_at = to_naive_utc(order.get("time") / 1000 if order.get("time") else None)
                        
                        new_order = OrderModel(
                            symbol=symbol,
                            order_id=order_id,
                            client_order_id=order.get("clientOrderId"),
                            side=order.get("side"),
                            order_type=order.get("type", "LIMIT"),
                            price=float(order.get("price", 0)),
                            quantity=float(order.get("origQty", 0)),
                            status=exchange_status,
                            filled_quantity=float(order.get("executedQty", 0)),
                            strategy_name=strategy_name,
                            order_purpose="market_making",  # 默认值
                            created_at=created_at,
                        )
                        session.add(new_order)
                        stats["created"] += 1
                        
                    else:
                        # 数据库中存在，检查是否需要更新
                        current_status = db_order.status
                        
                        # 检查状态转换是否合法
                        is_valid, error_msg = OrderStatusManager.validate_transition(
                            current_status, exchange_status
                        )
                        
                        if current_status == exchange_status:
                            stats["skipped"] += 1
                            continue
                            
                        if not is_valid:
                            # 状态转换不合法，但交易所已经变更了
                            # 这种情况可能是：
                            # 1. 数据库状态是PENDING，交易所已经是NEW（正常）
                            # 2. 数据库状态是PENDING_CANCEL，交易所已经是CANCELED（正常）
                            # 3. WebSocket遗漏了中间状态
                            
                            if current_status in ("PENDING", "PENDING_CANCEL"):
                                # PENDING状态允许强制同步
                                logging.info(
                                    f"订单 {order_id} 从 {current_status} 强制同步到 {exchange_status}"
                                )
                            else:
                                logging.warning(
                                    f"订单 {order_id} 状态转换异常: {current_status} -> {exchange_status}, "
                                    f"原因: {error_msg}，强制同步"
                                )
                        
                        # 更新订单状态
                        await session.execute(
                            update(OrderModel)
                            .where(OrderModel.order_id == order_id)
                            .values(
                                status=exchange_status,
                                filled_quantity=float(order.get("executedQty", 0)),
                                updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
                            )
                        )
                        stats["updated"] += 1
                
                await session.commit()
                stats["synced"] = stats["created"] + stats["updated"]
                
                if stats["synced"] > 0:
                    logging.info(
                        f"✅ 订单状态同步完成: symbol={symbol}, "
                        f"新建={stats['created']}, 更新={stats['updated']}, 跳过={stats['skipped']}"
                    )
                    
        except Exception as e:
            logging.error(f"❌ 订单状态同步失败: {e}", exc_info=True)
            
        return stats

    async def record_order_cancellation(
        self,
        order_ids: List[str],
        symbol: str,
        cancellation_reason: str,
        metadata: Optional[Dict[str, Any]] = None
    ):
        """
        记录订单撤销操作（第一阶段：PENDING_CANCEL）
        
        Args:
            order_ids: 被撤销的订单ID列表
            symbol: 交易对
            cancellation_reason: 撤销原因
                - "stop_loss_fixed": 固定止损触发
                - "stop_loss_trailing": 移动止损触发
                - "stop_loss_time": 时间止损触发
                - "risk_level_1": 风险等级1（极高风险）
                - "risk_level_2": 风险等级2（中等风险）
                - "manual": 手动撤销
                - "strategy_adjustment": 策略调整
            metadata: 额外元数据（止损参数、风险评分等）
        """
        from .order_states import OrderStatusManager
        
        if not self._db_available or not self.async_session:
            logging.warning("数据库不可用，无法记录撤单操作")
            return
            
        try:
            async with self.async_session() as session:
                for order_id in order_ids:
                    # 查询当前订单状态
                    result = await session.execute(
                        select(OrderModel).where(OrderModel.order_id == order_id)
                    )
                    order = result.scalar_one_or_none()
                    
                    if order is None:
                        logging.warning(f"订单 {order_id} 不存在，无法记录撤单")
                        continue
                    
                    # 检查是否可以撤单
                    if not OrderStatusManager.can_cancel(order.status):
                        logging.warning(
                            f"订单 {order_id} 当前状态 {order.status} 不可撤单，跳过"
                        )
                        continue
                    
                    # 更新为PENDING_CANCEL状态
                    extra_info = order.extra_info or {}
                    extra_info.update({
                        "cancellation_reason": cancellation_reason,
                        "cancellation_metadata": metadata,
                        "cancel_requested_at": datetime.now(timezone.utc).isoformat()
                    })
                    
                    await session.execute(
                        update(OrderModel)
                        .where(OrderModel.order_id == order_id)
                        .values(
                            status="PENDING_CANCEL",
                            extra_info=extra_info,
                            updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
                        )
                    )
                
                await session.commit()
                logging.info(
                    f"✅ 记录撤单操作: {len(order_ids)} 个订单 → PENDING_CANCEL, "
                    f"原因: {cancellation_reason}"
                )
                
        except Exception as e:
            logging.error(f"❌ 记录撤单操作失败: {e}", exc_info=True)

    async def confirm_order_cancellation(
        self,
        order_ids: List[str],
        success: bool = True
    ):
        """
        确认订单撤销结果（第二阶段：PENDING_CANCEL → CANCELED/CANCEL_REJECTED）
        
        Args:
            order_ids: 订单ID列表
            success: 撤单是否成功
        """
        if not self._db_available or not self.async_session:
            return
            
        try:
            final_status = "CANCELED" if success else "CANCEL_REJECTED"
            
            async with self.async_session() as session:
                await session.execute(
                    update(OrderModel)
                    .where(OrderModel.order_id.in_(order_ids))
                    .where(OrderModel.status == "PENDING_CANCEL")
                    .values(
                        status=final_status,
                        updated_at=datetime.now(timezone.utc).replace(tzinfo=None)
                    )
                )
                await session.commit()
                
                logging.info(
                    f"✅ 撤单结果确认: {len(order_ids)} 个订单 → {final_status}"
                )
                
        except Exception as e:
            logging.error(f"❌ 确认撤单结果失败: {e}", exc_info=True)

    async def get_active_orders_from_db(
        self,
        symbol: str,
        strategy_name: Optional[str] = None
    ) -> List[Dict[str, Any]]:
        """
        从数据库查询活跃订单
        
        活跃订单包括：NEW, PARTIALLY_FILLED, PENDING_CANCEL
        
        Args:
            symbol: 交易对
            strategy_name: 策略名称（可选）
            
        Returns:
            订单列表
        """
        if not self._db_available or not self.async_session:
            return []
            
        try:
            async with self.async_session() as session:
                query = select(OrderModel).where(
                    OrderModel.symbol == symbol,
                    OrderModel.status.in_(["NEW", "PARTIALLY_FILLED", "PENDING_CANCEL"])
                )
                
                if strategy_name:
                    query = query.where(OrderModel.strategy_name == strategy_name)
                
                result = await session.execute(query)
                orders = result.scalars().all()
                
                return [
                    {
                        "order_id": order.order_id,
                        "client_order_id": order.client_order_id,
                        "side": order.side,
                        "price": float(order.price),
                        "quantity": float(order.quantity),
                        "status": order.status,
                        "filled_quantity": float(order.filled_quantity or 0),
                        "created_at": order.created_at,
                    }
                    for order in orders
                ]
                
        except Exception as e:
            logging.error(f"❌ 查询活跃订单失败: {e}")
            return []


# 全局单例
_recorder_instance = None


def get_order_recorder() -> OrderRecorder:
    """获取订单记录器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = OrderRecorder()
        _recorder_instance.start()
    return _recorder_instance
