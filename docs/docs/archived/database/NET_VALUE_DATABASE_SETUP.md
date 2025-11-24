# 净值数据库持久化部署指南

## 📋 概述

本文档说明如何部署和使用净值数据库持久化功能。

**功能特性**：
- ✅ 无限历史记录存储（PostgreSQL）
- ✅ 实时查询（Redis）
- ✅ 异常事件追踪
- ✅ 高性能异步批量写入（40条/批，10秒刷新）
- ✅ 优雅降级（数据库失败不影响主流程）

---

## 🚀 快速开始

### 1. 安装依赖

```bash
# 安装 PostgreSQL 驱动
uv pip install asyncpg psycopg2-binary
```

### 2. 配置环境变量

编辑 `.env` 文件，添加 PostgreSQL 配置：

```bash
# PostgreSQL 数据库配置
POSTGRES_USER=xtetf
POSTGRES_PASSWORD=12345678
POSTGRES_DB=xtetf
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
```

### 3. 初始化数据库表

```bash
# 检查数据库连接
uv run python scripts/init_net_value_tables.py --check

# 创建表
uv run python scripts/init_net_value_tables.py

# 查看示例查询
uv run python scripts/init_net_value_tables.py --show-queries
```

### 4. 启用持久化

编辑 `config/strategies.yaml`：

```yaml
database:
  net_value_persistence:
    enabled: true  # 改为 true
    batch_size: 40
    flush_interval: 10
```

### 5. 启动服务

```bash
# 使用统一脚本
uv run python run_net_value.py --strategy ton3l --env qa

# 或使用 PM2 管理
pm2 start ecosystem.config.js --only net-value-ton3l
```

### 6. 验证功能

```bash
# 检查日志
tail -f logs/ton3l/net_value.log

# 查询数据库
psql -U xtetf -d xtetf -c "SELECT COUNT(*) FROM net_value_history WHERE strategy_name='ton3l';"
```

---

## 📊 数据库架构

### 表结构

#### 1. **net_value_history** - 净值历史表

存储每秒的净值数据：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| strategy_name | String(20) | 策略名称（stg3l/stg3s/stg5l/stg5s/ton3l） |
| symbol | String(20) | 交易对（stg_usdt/ton_usdt） |
| leverage | Integer | 杠杆倍数（3 或 5） |
| direction | String(5) | 方向（long/short） |
| net_value | Numeric(20,8) | 净值 |
| underlying_price | Numeric(20,8) | 标的价格 |
| change_rate | Numeric(10,6) | 净值变化率 |
| price_change_rate | Numeric(10,6) | 价格变化率 |
| fee_deducted | Numeric(20,8) | 本次扣除的管理费 |
| cumulative_fee | Numeric(20,8) | 累计管理费 |
| rebalance_triggered | Boolean | 是否触发再平衡 |
| rebalance_count | Integer | 再平衡次数 |
| recorded_at | DateTime | 业务时间（UTC） |
| created_at | DateTime | 创建时间 |

**索引**：
- `idx_nv_strategy_time (strategy_name, recorded_at)` - 按策略查询
- `idx_nv_symbol_time (symbol, recorded_at)` - 按标的查询
- `idx_nv_recorded_at (recorded_at)` - 时间范围查询

#### 2. **net_value_events** - 异常事件表

存储价格突变、断线恢复等异常事件：

| 字段 | 类型 | 说明 |
|------|------|------|
| id | Integer | 主键 |
| strategy_name | String(20) | 策略名称 |
| symbol | String(20) | 交易对 |
| event_type | String(20) | 事件类型（price_spike/long_restart/recovery） |
| severity | String(10) | 严重程度（low/medium/high/critical） |
| old_price | Numeric(20,8) | 旧价格 |
| new_price | Numeric(20,8) | 新价格 |
| change_rate | Numeric(10,6) | 变化率 |
| gap_seconds | Integer | 间隔秒数 |
| missed_intervals | Integer | 遗漏周期数 |
| net_value_id | Integer | 关联净值记录ID |
| extra_data | JSON | 额外信息 |
| event_time | DateTime | 事件时间（UTC） |
| created_at | DateTime | 创建时间 |

**索引**：
- `idx_nv_event_type_time (event_type, event_time)` - 按类型查询
- `idx_nv_event_strategy (strategy_name, event_time)` - 按策略查询
- `idx_nv_event_severity (severity, event_time)` - 按严重程度查询

---

## 📈 数据量预估

### 存储容量

**日常数据量**（4个策略）：
- 日: 345,600 条 / 52 MB
- 周: 2,419,200 条 / 364 MB
- 月: 10,368,000 条 / 1.5 GB
- 年: 126,144,000 条 / 18 GB

### 性能特性

- **写入性能**: 异步批量写入，不阻塞主循环
- **查询性能**: 复合索引，毫秒级响应
- **资源占用**: 单线程池，低CPU/内存占用

---

## 🔍 常用查询

### 1. 查询最近净值

```sql
-- 查询某策略最近24小时净值
SELECT recorded_at, net_value, change_rate
FROM net_value_history
WHERE strategy_name = 'ton3l'
  AND recorded_at > NOW() - INTERVAL '24 hours'
ORDER BY recorded_at DESC
LIMIT 100;
```

### 2. 按小时聚合

```sql
-- 按小时聚合统计
SELECT
    date_trunc('hour', recorded_at) AS hour,
    AVG(net_value) AS avg_net_value,
    MAX(net_value) AS max_net_value,
    MIN(net_value) AS min_net_value,
    COUNT(*) AS data_points
FROM net_value_history
WHERE strategy_name = 'ton3l'
  AND recorded_at > NOW() - INTERVAL '7 days'
GROUP BY hour
ORDER BY hour DESC;
```

### 3. 查询异常事件

```sql
-- 查询异常事件统计
SELECT
    event_type,
    severity,
    COUNT(*) as count,
    AVG(gap_seconds) as avg_gap
FROM net_value_events
WHERE strategy_name = 'ton3l'
  AND event_time > NOW() - INTERVAL '7 days'
GROUP BY event_type, severity
ORDER BY count DESC;
```

### 4. 查询价格突变

```sql
-- 查询价格突变事件
SELECT
    event_time,
    old_price,
    new_price,
    change_rate,
    severity
FROM net_value_events
WHERE strategy_name = 'ton3l'
  AND event_type = 'price_spike'
  AND event_time > NOW() - INTERVAL '24 hours'
ORDER BY event_time DESC;
```

### 5. 净值趋势分析

```sql
-- 查询净值趋势（每分钟采样）
SELECT
    date_trunc('minute', recorded_at) AS minute,
    AVG(net_value) AS avg_net_value,
    AVG(underlying_price) AS avg_price,
    MAX(net_value) - MIN(net_value) AS volatility
FROM net_value_history
WHERE strategy_name = 'ton3l'
  AND recorded_at > NOW() - INTERVAL '1 hour'
GROUP BY minute
ORDER BY minute DESC;
```

---

## ⚙️ 配置参数

### 数据库持久化配置

`config/strategies.yaml`:

```yaml
database:
  net_value_persistence:
    enabled: true              # 是否启用持久化
    batch_size: 40            # 批量大小（推荐：4策略×10秒）
    flush_interval: 10        # 刷新间隔（秒）
    enable_partitioning: false # 月度分区（生产环境推荐）
```

### 环境变量

`.env`:

```bash
# PostgreSQL 配置
POSTGRES_USER=xtetf           # 数据库用户
POSTGRES_PASSWORD=12345678    # 数据库密码
POSTGRES_DB=xtetf            # 数据库名称
POSTGRES_HOST=localhost      # 数据库主机
POSTGRES_PORT=5432           # 数据库端口
```

---

## 🛠️ 运维管理

### 数据库维护

#### 1. 查看表大小

```sql
SELECT
    schemaname,
    tablename,
    pg_size_pretty(pg_total_relation_size(schemaname||'.'||tablename)) AS size
FROM pg_tables
WHERE tablename LIKE 'net_value%'
ORDER BY pg_total_relation_size(schemaname||'.'||tablename) DESC;
```

#### 2. 清理旧数据

```sql
-- 删除3个月前的数据（谨慎操作！）
DELETE FROM net_value_history
WHERE recorded_at < NOW() - INTERVAL '3 months';

DELETE FROM net_value_events
WHERE event_time < NOW() - INTERVAL '3 months';

-- 清理后重建索引
REINDEX TABLE net_value_history;
REINDEX TABLE net_value_events;

-- 回收空间
VACUUM FULL net_value_history;
VACUUM FULL net_value_events;
```

#### 3. 数据导出

```bash
# 导出最近7天的数据
pg_dump -U xtetf -d xtetf \
  --table=net_value_history \
  --table=net_value_events \
  --data-only \
  --where="recorded_at > NOW() - INTERVAL '7 days'" \
  > netvalue_backup_$(date +%Y%m%d).sql
```

#### 4. 性能优化

```sql
-- 分析表统计信息
ANALYZE net_value_history;
ANALYZE net_value_events;

-- 检查索引使用情况
SELECT
    schemaname,
    tablename,
    indexname,
    idx_scan,
    idx_tup_read,
    idx_tup_fetch
FROM pg_stat_user_indexes
WHERE tablename LIKE 'net_value%'
ORDER BY idx_scan DESC;
```

### 监控指标

#### 1. 数据写入监控

```python
# 检查最近数据写入时间
from sqlalchemy import create_engine, text

with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT
            strategy_name,
            MAX(recorded_at) as last_update,
            COUNT(*) as count_1h,
            EXTRACT(EPOCH FROM (NOW() - MAX(recorded_at))) as seconds_since
        FROM net_value_history
        WHERE recorded_at > NOW() - INTERVAL '1 hour'
        GROUP BY strategy_name
    """))
    for row in result:
        print(f"{row.strategy_name}: {row.seconds_since:.0f}秒前，最近1小时{row.count_1h}条")
```

#### 2. 异常事件监控

```python
# 检查最近的异常事件
with engine.connect() as conn:
    result = conn.execute(text("""
        SELECT
            strategy_name,
            event_type,
            severity,
            COUNT(*) as count
        FROM net_value_events
        WHERE event_time > NOW() - INTERVAL '1 hour'
        GROUP BY strategy_name, event_type, severity
        ORDER BY severity DESC, count DESC
    """))
    for row in result:
        print(f"{row.strategy_name}: {row.event_type} ({row.severity}) - {row.count}次")
```

---

## 🚨 故障排查

### 问题 1: 数据库连接失败

**症状**: `role "postgres" does not exist`

**解决方案**:
```bash
# 1. 检查环境变量
cat .env | grep POSTGRES

# 2. 验证数据库连接
psql -U xtetf -d xtetf -c "SELECT version();"

# 3. 确认用户和数据库存在
psql -U postgres -c "\du"  # 列出所有用户
psql -U postgres -c "\l"   # 列出所有数据库
```

### 问题 2: 表不存在

**症状**: `relation "net_value_history" does not exist`

**解决方案**:
```bash
# 1. 检查表是否存在
uv run python scripts/init_net_value_tables.py --check

# 2. 创建表
uv run python scripts/init_net_value_tables.py

# 3. 验证表结构
psql -U xtetf -d xtetf -c "\d net_value_history"
```

### 问题 3: 索引名称冲突

**症状**: `relation "idx_symbol_time" already exists`

**解决方案**:
- 已修复：净值表使用 `idx_nv_*` 前缀避免冲突
- 如果仍有问题，使用 `--drop` 参数重建：
  ```bash
  uv run python scripts/init_net_value_tables.py --drop
  ```

### 问题 4: 没有数据写入

**症状**: 数据库中查询不到数据

**排查步骤**:
```bash
# 1. 检查配置是否启用
grep "enabled:" config/strategies.yaml

# 2. 检查日志
tail -f logs/*/net_value.log | grep -E "(数据库|持久化|NetValueRecorder)"

# 3. 检查批量缓冲区
# 数据可能在缓冲区中，等待批量写入（最多10秒）

# 4. 手动刷新
# 重启程序会自动刷新缓冲区
```

### 问题 5: RuntimeWarning

**症状**: `coroutine was never awaited`

**解决方案**:
- 已修复：使用线程池 + `asyncio.run()` 处理异步操作
- 如果仍有问题，检查代码版本是否最新

---

## 📚 技术文档

### 架构设计

```
主线程（同步）
  ↓
ImprovedNetValue.cal_net_value()
  ↓
_save_to_redis()
  ├─ Redis 写入（同步）
  └─ _record_net_value_to_db_sync()
       ↓
     线程池提交任务
       ↓
     后台线程
       ↓
     asyncio.run(_run_async_db_write)
       ↓
     NetValueRecorder.record_net_value()
       ↓
     批量缓冲（40条/批，10秒刷新）
       ↓
     PostgreSQL（异步写入）
```

### 数据流

1. **实时计算**: 主循环每秒计算净值
2. **同步写入**: 立即写入 Redis（<1ms）
3. **异步批量**: 提交到线程池（非阻塞）
4. **批量写入**: 40条一批或10秒刷新
5. **事件记录**: 异常事件立即写入数据库

### 关键特性

- **非阻塞**: 主线程只负责提交任务
- **批量优化**: 减少数据库连接开销
- **线程安全**: 使用锁保护共享状态
- **优雅降级**: 数据库失败不影响主流程
- **资源控制**: 单worker线程池，低开销

---

## 📝 开发指南

### 添加新的净值字段

1. 修改 `etf/storage/models.py`:
   ```python
   class NetValueHistory(Base):
       # 添加新字段
       new_field = Column(Numeric(20, 8))
   ```

2. 重建表（开发环境）:
   ```bash
   uv run python scripts/init_net_value_tables.py --drop
   ```

3. 修改 `ImprovedNetValue._format_db_data()`:
   ```python
   def _format_db_data(self, data: Dict) -> Dict:
       return {
           # ...
           "new_field": data.get("new_field"),
       }
   ```

### 添加新的事件类型

1. 在 `ImprovedNetValue` 中记录事件:
   ```python
   if self.db_recorder:
       self._record_event_sync("new_event_type", {
           "severity": "medium",
           "timestamp": time.time(),
           # 其他事件数据
       })
   ```

2. 事件会自动写入 `net_value_events` 表

---

## ✅ 部署检查清单

部署前请确认：

- [ ] PostgreSQL 已安装并运行
- [ ] 环境变量已正确配置（`.env`）
- [ ] 数据库表已创建（`init_net_value_tables.py`）
- [ ] 数据库连接测试成功
- [ ] 配置文件中 `enabled: true`
- [ ] 依赖包已安装（`asyncpg`, `psycopg2-binary`）
- [ ] 日志目录已创建（`logs/`）
- [ ] 磁盘空间充足（预留至少 20GB）
- [ ] 备份策略已制定

---

## 🔗 相关文档

- [RISK_CONTROL_IMPLEMENTATION.md](./RISK_CONTROL_IMPLEMENTATION.md) - 风险控制系统
- [PROJECT_PROGRESS_REPORT.md](./PROJECT_PROGRESS_REPORT.md) - 项目进度报告
- [TECHNICAL_DEBT.md](./TECHNICAL_DEBT.md) - 技术债务跟踪

---

**最后更新**: 2025-11-20
**版本**: 1.0.0
