"""
订单记录器 - 负责记录所有订单和交易数据
支持异步写入，避免影响交易性能
"""

import logging
import json
import time
import asyncio
import pandas as pd
from datetime import datetime, timezone, timedelta
from pathlib import Path
import aiofiles
import redis.asyncio as aioredis
from typing import Dict, List, Optional, Any
import threading
from queue import Queue
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
from sqlalchemy.orm import sessionmaker
from sqlalchemy import select, update

# 设置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(filename)s:%(lineno)d - %(message)s",
)


class OrderRecorder:
    """订单记录器 - 异步记录所有交易数据"""

    def __init__(
        self,
        db_url: str = "postgresql+asyncpg://user:password@localhost/etf_trading",
        redis_url: str = "redis://localhost:6379/0",
    ):
        """
        初始化订单记录器
        Args:
            db_url: PostgreSQL数据库连接URL
            redis_url: Redis连接URL
        """
        self.db_url = db_url
        self.redis_url = redis_url

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
        }

        # 启动标志
        self._running = False
        self._worker_thread = None

    async def init_db(self):
        """初始化数据库连接"""
        # 创建异步数据库引擎
        self.engine = create_async_engine(
            self.db_url, echo=False, pool_size=20, max_overflow=10, pool_pre_ping=True
        )

        # 创建异步会话工厂
        self.async_session = sessionmaker(
            self.engine, class_=AsyncSession, expire_on_commit=False
        )

        # 初始化Redis连接
        self.redis = await aioredis.from_url(
            self.redis_url, encoding="utf-8", decode_responses=True
        )

        logging.info("数据库和Redis连接初始化完成")

    async def record_order(self, order_data: Dict[str, Any]):
        """
        记录订单数据
        Args:
            order_data: 订单数据字典，包含：
                - symbol: 交易对
                - orderId: 订单ID
                - clientOrderId: 客户端订单ID
                - side: 买卖方向 (BUY/SELL)
                - price: 价格
                - quantity: 数量
                - status: 订单状态
                - is_wash_trading: 是否为洗盘订单
                - timestamp: 时间戳
                - net_value: 当时的净值
                - spread: 当时的价差设置
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
            await self._update_redis_cache(order_data)

        except Exception as e:
            logging.error(f"记录订单失败: {e}, 订单数据: {order_data}")

    async def record_trade(self, trade_data: Dict[str, Any]):
        """
        记录成交数据
        Args:
            trade_data: 成交数据字典，包含：
                - symbol: 交易对
                - orderId: 订单ID
                - tradeId: 成交ID
                - price: 成交价格
                - quantity: 成交数量
                - fee: 手续费
                - timestamp: 成交时间
                - is_maker: 是否为maker
                - is_wash_trading: 是否为洗盘成交
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
            await self._update_trade_cache(trade_data)

        except Exception as e:
            logging.error(f"记录成交失败: {e}, 成交数据: {trade_data}")

    async def _update_redis_cache(self, order_data: Dict[str, Any]):
        """更新Redis中的订单缓存"""
        try:
            # 存储最新订单信息
            # 支持两种键名：order_id（下划线）和 orderId（驼峰）
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
            self._worker_thread = threading.Thread(target=self._run_worker)
            self._worker_thread.daemon = True
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

    async def _batch_write_orders(self):
        """批量写入订单数据"""
        orders = []

        # 从队列中获取订单（最多100条）
        while not self.order_queue.empty() and len(orders) < 100:
            try:
                order = self.order_queue.get_nowait()
                orders.append(order)
            except:
                break

        if orders:
            # TODO: 实际写入数据库
            # async with self.async_session() as session:
            #     await session.bulk_insert(orders)
            #     await session.commit()

            # 暂时写入CSV文件
            df = pd.DataFrame(orders)
            csv_file = Path(f"orders_{datetime.now().strftime('%Y%m%d')}.csv")

            if csv_file.exists():
                df.to_csv(csv_file, mode="a", header=False, index=False)
            else:
                df.to_csv(csv_file, index=False)

            logging.info(f"批量写入 {len(orders)} 条订单记录")

    async def _batch_write_trades(self):
        """批量写入成交数据"""
        trades = []

        # 从队列中获取成交（最多100条）
        while not self.trade_queue.empty() and len(trades) < 100:
            try:
                trade = self.trade_queue.get_nowait()
                trades.append(trade)
            except:
                break

        if trades:
            # TODO: 实际写入数据库
            # async with self.async_session() as session:
            #     await session.bulk_insert(trades)
            #     await session.commit()

            # 暂时写入CSV文件
            df = pd.DataFrame(trades)
            csv_file = Path(f"trades_{datetime.now().strftime('%Y%m%d')}.csv")

            if csv_file.exists():
                df.to_csv(csv_file, mode="a", header=False, index=False)
            else:
                df.to_csv(csv_file, index=False)

            logging.info(f"批量写入 {len(trades)} 条成交记录")

    def get_stats(self) -> Dict[str, Any]:
        """获取统计信息"""
        return self.stats.copy()


# 全局单例
_recorder_instance = None


def get_order_recorder() -> OrderRecorder:
    """获取订单记录器单例"""
    global _recorder_instance
    if _recorder_instance is None:
        _recorder_instance = OrderRecorder()
        _recorder_instance.start()
    return _recorder_instance
