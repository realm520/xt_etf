"""
数据库模型定义
使用SQLAlchemy定义所有交易相关的数据表
"""

from sqlalchemy import (
    Column,
    String,
    Float,
    Integer,
    Boolean,
    DateTime,
    Index,
    JSON,
    Numeric,
)
from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy.sql import func
from datetime import datetime

Base = declarative_base()


class Order(Base):
    """订单表 - 记录所有订单信息"""

    __tablename__ = "orders"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 订单基本信息
    symbol = Column(String(20), nullable=False, index=True)
    order_id = Column(String(50), unique=True, nullable=False, index=True)
    client_order_id = Column(String(50), index=True)

    # 订单详情
    side = Column(String(10), nullable=False)  # BUY/SELL
    order_type = Column(String(20), default="LIMIT")
    price = Column(Numeric(20, 8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)

    # 订单状态
    status = Column(
        String(20), nullable=False, index=True
    )  # NEW/FILLED/CANCELED/REJECTED
    filled_quantity = Column(Numeric(20, 8), default=0)

    # 策略相关
    strategy_name = Column(String(20), index=True)  # stg3l/stg3s/stg5l/stg5s
    is_wash_trading = Column(Boolean, default=False, index=True)

    # 市场状态（下单时）
    net_value = Column(Numeric(20, 8))
    bid_ask_spread = Column(Numeric(10, 6))
    best_bid = Column(Numeric(20, 8))
    best_ask = Column(Numeric(20, 8))

    # 时间戳
    created_at = Column(DateTime, default=func.now(), index=True)
    updated_at = Column(DateTime, default=func.now(), onupdate=func.now())
    exchange_timestamp = Column(DateTime)

    # 额外信息
    extra_info = Column(JSON)

    # 索引
    __table_args__ = (
        Index("idx_symbol_created", "symbol", "created_at"),
        Index("idx_strategy_wash", "strategy_name", "is_wash_trading"),
    )


class Trade(Base):
    """成交表 - 记录所有成交信息"""

    __tablename__ = "trades"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 成交基本信息
    symbol = Column(String(20), nullable=False, index=True)
    trade_id = Column(String(50), unique=True, nullable=False, index=True)
    order_id = Column(String(50), nullable=False, index=True)

    # 成交详情
    price = Column(Numeric(20, 8), nullable=False)
    quantity = Column(Numeric(20, 8), nullable=False)
    quote_quantity = Column(Numeric(20, 8))  # 成交额

    # 手续费
    fee = Column(Numeric(20, 8), default=0)
    fee_asset = Column(String(10))

    # 成交角色
    is_maker = Column(Boolean, default=False)
    is_buyer = Column(Boolean)

    # 策略相关
    strategy_name = Column(String(20), index=True)
    is_wash_trading = Column(Boolean, default=False, index=True)

    # 时间戳
    traded_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    # 额外信息
    extra_info = Column(JSON)

    # 索引
    __table_args__ = (
        Index("idx_symbol_traded", "symbol", "traded_at"),
        Index("idx_order_trades", "order_id"),
    )


class MarketSnapshot(Base):
    """市场快照表 - 定期记录市场状态"""

    __tablename__ = "market_snapshots"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 市场信息
    symbol = Column(String(20), nullable=False, index=True)

    # 价格信息
    net_value = Column(Numeric(20, 8), nullable=False)
    market_price = Column(Numeric(20, 8))
    premium_rate = Column(Numeric(10, 6))  # 溢价率

    # 订单簿
    best_bid = Column(Numeric(20, 8))
    best_ask = Column(Numeric(20, 8))
    bid_volume = Column(Numeric(20, 8))
    ask_volume = Column(Numeric(20, 8))
    spread = Column(Numeric(10, 6))

    # 深度信息（JSON格式存储）
    order_book = Column(JSON)  # 完整订单簿

    # 时间戳
    snapshot_time = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    # 索引
    __table_args__ = (Index("idx_symbol_time", "symbol", "snapshot_time"),)


class StrategyMetrics(Base):
    """策略指标表 - 记录策略运行指标"""

    __tablename__ = "strategy_metrics"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 策略信息
    strategy_name = Column(String(20), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)

    # 时间段
    period_start = Column(DateTime, nullable=False, index=True)
    period_end = Column(DateTime, nullable=False)
    period_type = Column(String(10))  # HOUR/DAY/WEEK

    # 交易统计
    total_orders = Column(Integer, default=0)
    filled_orders = Column(Integer, default=0)
    canceled_orders = Column(Integer, default=0)

    # 成交统计
    total_trades = Column(Integer, default=0)
    buy_trades = Column(Integer, default=0)
    sell_trades = Column(Integer, default=0)

    # 交易量统计
    total_volume = Column(Numeric(20, 8), default=0)
    real_volume = Column(Numeric(20, 8), default=0)
    wash_volume = Column(Numeric(20, 8), default=0)
    real_volume_ratio = Column(Numeric(10, 6))

    # 收益统计
    gross_pnl = Column(Numeric(20, 8), default=0)
    fee_cost = Column(Numeric(20, 8), default=0)
    net_pnl = Column(Numeric(20, 8), default=0)

    # 价差收益
    spread_revenue = Column(Numeric(20, 8), default=0)

    # 库存统计
    avg_inventory = Column(Numeric(20, 8))
    max_inventory = Column(Numeric(20, 8))
    min_inventory = Column(Numeric(20, 8))

    # 创建时间
    created_at = Column(DateTime, default=func.now())

    # 索引
    __table_args__ = (
        Index("idx_strategy_period", "strategy_name", "period_start"),
        Index("idx_symbol_period", "symbol", "period_start"),
    )


class PnLRecord(Base):
    """盈亏记录表 - 实时记录盈亏情况"""

    __tablename__ = "pnl_records"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 策略信息
    strategy_name = Column(String(20), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)

    # 盈亏类型
    pnl_type = Column(String(20))  # REALIZED/UNREALIZED/FEE/SPREAD

    # 盈亏金额
    amount = Column(Numeric(20, 8), nullable=False)

    # 相关交易
    trade_id = Column(String(50))
    order_id = Column(String(50))

    # 持仓信息
    position = Column(Numeric(20, 8))
    avg_cost = Column(Numeric(20, 8))
    market_price = Column(Numeric(20, 8))

    # 时间戳
    recorded_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    # 索引
    __table_args__ = (
        Index("idx_strategy_time", "strategy_name", "recorded_at"),
        Index("idx_pnl_type", "pnl_type", "recorded_at"),
    )


class SystemLog(Base):
    """系统日志表 - 记录重要系统事件"""

    __tablename__ = "system_logs"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 日志信息
    log_level = Column(String(10), nullable=False, index=True)  # INFO/WARN/ERROR
    log_type = Column(String(30), index=True)  # STRATEGY/ORDER/RISK/SYSTEM
    message = Column(String(500), nullable=False)

    # 相关信息
    strategy_name = Column(String(20))
    symbol = Column(String(20))

    # 详细信息
    details = Column(JSON)

    # 时间戳
    logged_at = Column(DateTime, default=func.now(), index=True)

    # 索引
    __table_args__ = (
        Index("idx_level_time", "log_level", "logged_at"),
        Index("idx_type_time", "log_type", "logged_at"),
    )


class NetValueHistory(Base):
    """净值历史表 - 记录净值时间序列数据"""

    __tablename__ = "net_value_history"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 策略信息
    strategy_name = Column(String(20), nullable=False, index=True)  # stg3l/stg3s/stg5l/stg5s
    symbol = Column(String(20), nullable=False, index=True)  # stg_usdt/ton_usdt
    leverage = Column(Integer, nullable=False)  # 3 or 5
    direction = Column(String(5), nullable=False)  # long/short

    # 净值数据
    net_value = Column(Numeric(20, 8), nullable=False)
    underlying_price = Column(Numeric(20, 8))  # 标的资产价格

    # 变化信息
    change_rate = Column(Numeric(10, 6))  # 净值变化率
    price_change_rate = Column(Numeric(10, 6))  # 价格变化率
    fee_deducted = Column(Numeric(20, 8))  # 本次扣除的管理费
    cumulative_fee = Column(Numeric(20, 8))  # 累计管理费

    # 再平衡标记
    rebalance_triggered = Column(Boolean, default=False)
    rebalance_count = Column(Integer, default=0)

    # 时间戳
    recorded_at = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    # 索引（使用 nv_ 前缀避免与其他表的索引名称冲突）
    __table_args__ = (
        Index("idx_nv_strategy_time", "strategy_name", "recorded_at"),
        Index("idx_nv_symbol_time", "symbol", "recorded_at"),
        Index("idx_nv_recorded_at", "recorded_at"),
    )


class NetValueEvent(Base):
    """净值异常事件表 - 记录价格突变、断线恢复等异常事件"""

    __tablename__ = "net_value_events"

    # 主键
    id = Column(Integer, primary_key=True, autoincrement=True)

    # 策略信息
    strategy_name = Column(String(20), nullable=False, index=True)
    symbol = Column(String(20), nullable=False, index=True)

    # 事件类型
    event_type = Column(
        String(20), nullable=False, index=True
    )  # price_spike/long_restart/recovery
    severity = Column(String(10))  # low/medium/high/critical

    # 事件详情
    old_price = Column(Numeric(20, 8))
    new_price = Column(Numeric(20, 8))
    change_rate = Column(Numeric(10, 6))
    gap_seconds = Column(Integer)
    missed_intervals = Column(Integer)

    # 关联净值记录
    net_value_id = Column(Integer)  # 外键关联到net_value_history.id

    # 额外信息（JSON格式）
    extra_data = Column(JSON)

    # 时间戳
    event_time = Column(DateTime, nullable=False, index=True)
    created_at = Column(DateTime, default=func.now())

    # 索引（使用 nv_event_ 前缀避免与其他表的索引名称冲突）
    __table_args__ = (
        Index("idx_nv_event_type_time", "event_type", "event_time"),
        Index("idx_nv_event_strategy", "strategy_name", "event_time"),
        Index("idx_nv_event_severity", "severity", "event_time"),
    )


# 创建所有表的函数
def create_tables(engine):
    """创建所有数据表"""
    Base.metadata.create_all(bind=engine)


# 删除所有表的函数
def drop_tables(engine):
    """删除所有数据表（谨慎使用）"""
    Base.metadata.drop_all(bind=engine)
