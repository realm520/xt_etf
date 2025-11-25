#!/usr/bin/env python3
"""
PostgreSQL集成测试脚本
验证订单记录器是否正常工作
"""

import os
import sys
import asyncio
import logging
from pathlib import Path
from datetime import datetime, timezone

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from dotenv import load_dotenv
from etf.storage import get_order_recorder

# 加载环境变量
load_dotenv()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def test_order_recording():
    """测试订单记录功能"""
    logger.info("=" * 60)
    logger.info("开始测试订单记录功能")
    logger.info("=" * 60)

    # 获取订单记录器
    recorder = get_order_recorder()

    # 等待初始化完成
    await asyncio.sleep(2)

    # 测试订单数据
    test_orders = [
        {
            "symbol": "BTC5L_USDT",
            "order_id": f"TEST_ORDER_{i}",
            "side": "BUY" if i % 2 == 0 else "SELL",
            "price": 20000.0 + i * 100,
            "quantity": 1.0 + i * 0.1,
            "status": "NEW",
            "strategy_name": "stg5l",
            "is_wash_trading": i % 3 == 0,  # 每3个订单中有1个是刷量订单
            "timestamp": datetime.now(timezone.utc),
        }
        for i in range(10)
    ]

    # 记录订单
    logger.info(f"\n📝 正在记录 {len(test_orders)} 条测试订单...")
    for order in test_orders:
        await recorder.record_order(order)

    # 等待批量写入完成
    await asyncio.sleep(3)

    # 获取统计信息
    stats = recorder.get_stats()

    logger.info("\n📊 订单记录器统计:")
    logger.info(f"  总订单数: {stats['total_orders']}")
    logger.info(f"  真实订单: {stats.get('real_orders', 'N/A')}")
    logger.info(f"  刷量订单: {stats.get('wash_orders', 'N/A')}")
    logger.info(f"  数据库写入成功: {stats['db_write_success']}")
    logger.info(f"  数据库写入失败: {stats['db_write_failed']}")
    logger.info(f"  数据库可用: {'✅ 是' if stats['db_available'] else '❌ 否'}")
    logger.info(f"  队列状态: 订单队列={stats['queue_sizes']['orders']}, 成交队列={stats['queue_sizes']['trades']}")

    return stats


async def test_trade_recording():
    """测试成交记录功能"""
    logger.info("\n" + "=" * 60)
    logger.info("开始测试成交记录功能")
    logger.info("=" * 60)

    recorder = get_order_recorder()

    # 测试成交数据
    test_trades = [
        {
            "symbol": "BTC5L_USDT",
            "trade_id": f"TEST_TRADE_{i}",
            "orderId": f"TEST_ORDER_{i}",
            "price": 20000.0 + i * 100,
            "quantity": 0.5 + i * 0.05,
            "fee": 0.1,
            "feeCurrency": "USDT",
            "is_maker": i % 2 == 0,
            "strategy_name": "stg5l",
            "is_wash_trading": i % 3 == 0,
            "timestamp": datetime.now(timezone.utc),
        }
        for i in range(5)
    ]

    # 记录成交
    logger.info(f"\n💰 正在记录 {len(test_trades)} 条测试成交...")
    for trade in test_trades:
        await recorder.record_trade(trade)

    # 等待批量写入完成
    await asyncio.sleep(3)

    # 获取统计信息
    stats = recorder.get_stats()

    logger.info("\n📊 成交记录器统计:")
    logger.info(f"  总成交数: {stats['total_trades']}")
    logger.info(f"  真实成交额: {stats['real_volume']:.2f} USDT")
    logger.info(f"  刷量成交额: {stats['wash_volume']:.2f} USDT")

    return stats


async def verify_database_content():
    """验证数据库中的内容"""
    logger.info("\n" + "=" * 60)
    logger.info("验证数据库内容")
    logger.info("=" * 60)

    try:
        from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession
        from sqlalchemy.orm import sessionmaker
        from sqlalchemy import select, func
        from etf.storage.models import Order, Trade

        # 构建数据库URL
        db_user = os.getenv("POSTGRES_USER", "etf_user")
        db_password = os.getenv("POSTGRES_PASSWORD", "etf_password")
        db_name = os.getenv("POSTGRES_DB", "etf_trading")
        db_host = os.getenv("POSTGRES_HOST", "localhost")
        db_port = os.getenv("POSTGRES_PORT", "5432")

        db_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

        engine = create_async_engine(db_url, echo=False)
        async_session = sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

        async with async_session() as session:
            # 查询订单总数
            result = await session.execute(
                select(func.count(Order.id))
            )
            order_count = result.scalar()

            # 查询成交总数
            result = await session.execute(
                select(func.count(Trade.id))
            )
            trade_count = result.scalar()

            # 查询最近5条订单
            result = await session.execute(
                select(Order)
                .where(Order.order_id.like("TEST_ORDER_%"))
                .limit(5)
            )
            recent_orders = result.scalars().all()

            logger.info(f"\n✅ 数据库查询成功:")
            logger.info(f"  数据库中订单总数: {order_count}")
            logger.info(f"  数据库中成交总数: {trade_count}")

            if recent_orders:
                logger.info(f"\n📋 最近的测试订单:")
                for order in recent_orders:
                    logger.info(
                        f"  - {order.order_id}: {order.side} {order.quantity} @ {order.price} "
                        f"({'刷量' if order.is_wash_trading else '真实'})"
                    )

        await engine.dispose()

        return {"orders": order_count, "trades": trade_count}

    except Exception as e:
        logger.error(f"❌ 数据库查询失败: {e}")
        return None


async def main():
    """主测试函数"""
    logger.info("\n")
    logger.info("🧪" * 30)
    logger.info("PostgreSQL 集成测试")
    logger.info("🧪" * 30)

    try:
        # 测试1: 订单记录
        stats1 = await test_order_recording()

        # 测试2: 成交记录
        stats2 = await test_trade_recording()

        # 测试3: 数据库验证
        db_stats = await verify_database_content()

        # 总结
        logger.info("\n" + "=" * 60)
        logger.info("测试结果总结")
        logger.info("=" * 60)

        if stats1["db_available"]:
            logger.info("✅ PostgreSQL连接: 成功")
        else:
            logger.info("❌ PostgreSQL连接: 失败")

        if stats1["db_write_success"] > 0:
            logger.info(f"✅ 数据库写入: 成功 ({stats1['db_write_success']} 条记录)")
        else:
            logger.info("❌ 数据库写入: 失败")

        if db_stats:
            logger.info(f"✅ 数据库查询: 成功 ({db_stats['orders']} 订单, {db_stats['trades']} 成交)")
        else:
            logger.info("❌ 数据库查询: 失败")

        logger.info("\n💡 提示:")
        if stats1["db_available"]:
            logger.info("  - PostgreSQL集成工作正常")
            logger.info("  - 使用 'python scripts/query_orders.py --stats' 查看完整统计")
        else:
            logger.info("  - PostgreSQL连接失败，请检查配置")
            logger.info("  - 运行 'python scripts/init_database.py' 初始化数据库")

        logger.info("=" * 60 + "\n")

        return stats1["db_available"]

    except Exception as e:
        logger.error(f"\n❌ 测试失败: {e}")
        import traceback
        traceback.print_exc()
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
