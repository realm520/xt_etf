#!/usr/bin/env python3
"""
数据库初始化脚本
创建ETF交易系统所需的PostgreSQL数据库和表
"""

import os
import sys
import asyncio
import logging
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine
from etf.storage.models import Base

# 使用统一配置加载
from etf.config import init_env, get_db_config
init_env()

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


async def create_database():
    """创建数据库（如果不存在）"""
    # 从环境变量读取配置
    db_user = os.getenv("POSTGRES_USER", "etf_user")
    db_password = os.getenv("POSTGRES_PASSWORD", "etf_password")
    db_name = os.getenv("POSTGRES_DB", "etf_trading")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    # 连接到postgres数据库（默认数据库）
    postgres_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/postgres"

    try:
        engine = create_async_engine(postgres_url, isolation_level="AUTOCOMMIT")

        async with engine.connect() as conn:
            # 检查数据库是否存在
            result = await conn.execute(
                text(f"SELECT 1 FROM pg_database WHERE datname = '{db_name}'")
            )
            exists = result.scalar()

            if exists:
                logger.info(f"✅ 数据库 '{db_name}' 已存在")
            else:
                # 创建数据库
                await conn.execute(text(f'CREATE DATABASE "{db_name}"'))
                logger.info(f"✅ 成功创建数据库 '{db_name}'")

        await engine.dispose()

    except Exception as e:
        logger.error(f"❌ 创建数据库失败: {e}")
        logger.info("提示：请确保PostgreSQL已安装并运行，且用户有创建数据库的权限")
        raise


async def create_tables():
    """创建所有数据表"""
    # 从环境变量读取配置
    db_user = os.getenv("POSTGRES_USER", "etf_user")
    db_password = os.getenv("POSTGRES_PASSWORD", "etf_password")
    db_name = os.getenv("POSTGRES_DB", "etf_trading")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    # 连接到目标数据库
    db_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    try:
        engine = create_async_engine(db_url, echo=True)

        async with engine.begin() as conn:
            # 创建所有表
            await conn.run_sync(Base.metadata.create_all)

        logger.info("✅ 成功创建所有数据表")

        # 显示创建的表
        async with engine.connect() as conn:
            result = await conn.execute(
                text(
                    "SELECT table_name FROM information_schema.tables "
                    "WHERE table_schema = 'public' ORDER BY table_name"
                )
            )
            tables = [row[0] for row in result]

        logger.info(f"📊 创建的表: {', '.join(tables)}")

        await engine.dispose()

    except Exception as e:
        logger.error(f"❌ 创建数据表失败: {e}")
        raise


async def verify_connection():
    """验证数据库连接"""
    db_user = os.getenv("POSTGRES_USER", "etf_user")
    db_password = os.getenv("POSTGRES_PASSWORD", "etf_password")
    db_name = os.getenv("POSTGRES_DB", "etf_trading")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    db_url = f"postgresql+asyncpg://{db_user}:{db_password}@{db_host}:{db_port}/{db_name}"

    try:
        engine = create_async_engine(db_url)

        async with engine.connect() as conn:
            result = await conn.execute(text("SELECT version()"))
            version = result.scalar()

        logger.info(f"✅ PostgreSQL 连接成功")
        logger.info(f"📌 版本: {version.split(',')[0]}")

        await engine.dispose()
        return True

    except Exception as e:
        logger.error(f"❌ 数据库连接失败: {e}")
        return False


def print_summary():
    """打印配置摘要"""
    db_user = os.getenv("POSTGRES_USER", "etf_user")
    db_name = os.getenv("POSTGRES_DB", "etf_trading")
    db_host = os.getenv("POSTGRES_HOST", "localhost")
    db_port = os.getenv("POSTGRES_PORT", "5432")

    print("\n" + "=" * 60)
    print("PostgreSQL 数据库初始化完成")
    print("=" * 60)
    print(f"主机: {db_host}:{db_port}")
    print(f"数据库: {db_name}")
    print(f"用户: {db_user}")
    print("\n创建的表:")
    print("  - orders           订单表")
    print("  - trades           成交表")
    print("  - market_snapshots 市场快照表")
    print("  - strategy_metrics 策略指标表")
    print("  - pnl_records      盈亏记录表")
    print("  - system_logs      系统日志表")
    print("\n下一步:")
    print("  1. 启动交易系统: python run_etf.py --strategy stg3l")
    print("  2. 查看订单记录: python scripts/query_orders.py")
    print("=" * 60 + "\n")


async def main():
    """主函数"""
    logger.info("开始初始化PostgreSQL数据库...")

    try:
        # 步骤1: 验证连接
        logger.info("\n📡 步骤 1/3: 验证PostgreSQL连接...")
        if not await verify_connection():
            # 如果连接失败，尝试创建数据库
            logger.info("尝试创建数据库...")
            await create_database()

            # 再次验证
            if not await verify_connection():
                raise Exception("数据库连接失败，请检查配置")

        # 步骤2: 创建数据库（如果需要）
        logger.info("\n📦 步骤 2/3: 确保数据库存在...")
        await create_database()

        # 步骤3: 创建表
        logger.info("\n📊 步骤 3/3: 创建数据表...")
        await create_tables()

        # 打印摘要
        print_summary()

        return True

    except Exception as e:
        logger.error(f"\n❌ 初始化失败: {e}")
        logger.info("\n故障排查:")
        logger.info("  1. 确认PostgreSQL已安装并运行:")
        logger.info("     brew services list | grep postgresql  # macOS")
        logger.info("     systemctl status postgresql           # Linux")
        logger.info("  2. 检查.env配置文件中的数据库连接信息")
        logger.info("  3. 确认用户有创建数据库和表的权限")
        logger.info("  4. 安装所需依赖: uv pip install asyncpg")
        return False


if __name__ == "__main__":
    success = asyncio.run(main())
    sys.exit(0 if success else 1)
