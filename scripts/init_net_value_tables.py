#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
初始化净值数据库表

用法:
    python scripts/init_net_value_tables.py              # 创建表
    python scripts/init_net_value_tables.py --drop       # 删除后重建（危险！）
    python scripts/init_net_value_tables.py --check      # 检查表状态
"""

import sys
import os
import argparse
import asyncio
from pathlib import Path

# 添加项目根目录到 Python 路径
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from sqlalchemy import create_engine, inspect, text
from sqlalchemy.ext.asyncio import create_async_engine

# 使用统一配置加载
from etf.config import init_env, get_db_url
init_env()

# 导入数据库模型
from etf.storage.models import Base, NetValueHistory, NetValueEvent


def get_database_url(async_mode=False):
    """获取数据库连接URL（使用统一配置）"""
    return get_db_url(async_driver=async_mode)


def check_tables_exist(engine):
    """检查表是否已存在"""
    inspector = inspect(engine)
    existing_tables = inspector.get_table_names()

    net_value_history_exists = "net_value_history" in existing_tables
    net_value_events_exists = "net_value_events" in existing_tables

    print("\n📊 数据库表状态:")
    print(f"  net_value_history: {'✅ 已存在' if net_value_history_exists else '❌ 不存在'}")
    print(f"  net_value_events:  {'✅ 已存在' if net_value_events_exists else '❌ 不存在'}")

    if net_value_history_exists:
        # 检查表结构
        columns = [col["name"] for col in inspector.get_columns("net_value_history")]
        indexes = [idx["name"] for idx in inspector.get_indexes("net_value_history")]
        print(f"\n  net_value_history 字段数: {len(columns)}")
        print(f"  net_value_history 索引数: {len(indexes)}")

    if net_value_events_exists:
        columns = [col["name"] for col in inspector.get_columns("net_value_events")]
        indexes = [idx["name"] for idx in inspector.get_indexes("net_value_events")]
        print(f"\n  net_value_events 字段数: {len(columns)}")
        print(f"  net_value_events 索引数: {len(indexes)}")

    return net_value_history_exists and net_value_events_exists


def create_tables(drop_existing=False):
    """创建数据库表"""
    print("\n🔧 开始初始化净值数据库表...")

    try:
        # 创建同步引擎（用于表创建）
        engine = create_engine(get_database_url(async_mode=False))

        # 测试连接
        with engine.connect() as conn:
            result = conn.execute(text("SELECT version()"))
            version = result.scalar()
            print(f"✅ 数据库连接成功")
            print(f"   PostgreSQL 版本: {version.split(',')[0]}")

        # 检查表是否已存在
        if check_tables_exist(engine):
            if not drop_existing:
                print("\n⚠️  表已存在！使用 --drop 参数强制重建（会删除所有数据）")
                return False

            print("\n⚠️  删除现有表...")
            # 只删除净值相关的表
            with engine.connect() as conn:
                conn.execute(text("DROP TABLE IF EXISTS net_value_events CASCADE"))
                conn.execute(text("DROP TABLE IF EXISTS net_value_history CASCADE"))
                conn.commit()
            print("✅ 现有表已删除")

        # 创建表
        print("\n🔨 创建数据库表...")
        Base.metadata.create_all(
            engine,
            tables=[NetValueHistory.__table__, NetValueEvent.__table__],
        )

        print("✅ 表创建成功")

        # 验证表结构
        print("\n🔍 验证表结构...")
        check_tables_exist(engine)

        # 创建分区（可选）
        # create_partitions(engine)

        engine.dispose()
        return True

    except Exception as e:
        print(f"\n❌ 错误: {e}")
        import traceback
        traceback.print_exc()
        return False


def create_partitions(engine, months=12):
    """
    创建按月分区的表（PostgreSQL 10+）

    注意: 这需要将现有表转换为分区表，生产环境需谨慎操作
    """
    print(f"\n📅 创建月度分区（未来 {months} 个月）...")

    from datetime import datetime, timedelta

    current_date = datetime.now()

    with engine.connect() as conn:
        for i in range(months):
            # 计算分区日期范围
            start_date = (current_date + timedelta(days=30 * i)).replace(day=1)
            end_date = (start_date + timedelta(days=32)).replace(day=1)

            partition_name = f"net_value_history_{start_date.strftime('%Y_%m')}"

            # 检查分区是否存在
            result = conn.execute(text(f"""
                SELECT EXISTS (
                    SELECT 1 FROM pg_tables
                    WHERE tablename = '{partition_name}'
                )
            """))

            if result.scalar():
                print(f"  {partition_name}: 已存在")
                continue

            # 创建分区
            try:
                conn.execute(text(f"""
                    CREATE TABLE {partition_name} PARTITION OF net_value_history
                    FOR VALUES FROM ('{start_date.strftime('%Y-%m-%d')}')
                    TO ('{end_date.strftime('%Y-%m-%d')}')
                """))
                conn.commit()
                print(f"  {partition_name}: ✅ 创建成功")
            except Exception as e:
                print(f"  {partition_name}: ❌ 创建失败 - {e}")

    print("✅ 分区创建完成")


def show_sample_queries():
    """显示示例查询"""
    print("\n📝 示例查询:")
    print("""
-- 1. 查询某策略最近24小时净值
SELECT recorded_at, net_value, change_rate
FROM net_value_history
WHERE strategy_name = 'stg3l'
  AND recorded_at > NOW() - INTERVAL '24 hours'
ORDER BY recorded_at DESC
LIMIT 100;

-- 2. 按小时聚合统计
SELECT
    date_trunc('hour', recorded_at) AS hour,
    AVG(net_value) AS avg_net_value,
    MAX(net_value) AS max_net_value,
    MIN(net_value) AS min_net_value
FROM net_value_history
WHERE strategy_name = 'stg3l'
  AND recorded_at > NOW() - INTERVAL '7 days'
GROUP BY hour
ORDER BY hour DESC;

-- 3. 查询异常事件统计
SELECT event_type, severity, COUNT(*) as count
FROM net_value_events
WHERE strategy_name = 'stg3l'
  AND event_time > NOW() - INTERVAL '7 days'
GROUP BY event_type, severity
ORDER BY count DESC;
    """)


def main():
    parser = argparse.ArgumentParser(
        description="初始化净值数据库表",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "--drop",
        action="store_true",
        help="删除现有表后重建（⚠️ 危险！会删除所有数据）",
    )

    parser.add_argument(
        "--check",
        action="store_true",
        help="仅检查表状态，不创建",
    )

    parser.add_argument(
        "--create-partitions",
        action="store_true",
        help="创建月度分区表（可选）",
    )

    parser.add_argument(
        "--show-queries",
        action="store_true",
        help="显示示例查询",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("🗄️  净值数据库表初始化工具")
    print("=" * 70)

    if args.show_queries:
        show_sample_queries()
        return

    if args.check:
        engine = create_engine(get_database_url(async_mode=False))
        check_tables_exist(engine)
        engine.dispose()
        return

    # 创建表
    success = create_tables(drop_existing=args.drop)

    if success and args.create_partitions:
        engine = create_engine(get_database_url(async_mode=False))
        create_partitions(engine)
        engine.dispose()

    if success:
        print("\n" + "=" * 70)
        print("✅ 初始化完成！")
        print("=" * 70)
        print("\n💡 后续步骤:")
        print("1. 在 config/strategies.yaml 中启用数据库持久化:")
        print("   database.net_value_persistence.enabled: true")
        print("\n2. 在 run_net_value.py 中传递 enable_db_persistence=True")
        print("\n3. 使用 --show-queries 查看示例查询")
    else:
        print("\n" + "=" * 70)
        print("❌ 初始化失败，请检查错误信息")
        print("=" * 70)
        sys.exit(1)


if __name__ == "__main__":
    main()
