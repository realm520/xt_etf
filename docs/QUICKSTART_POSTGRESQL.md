# PostgreSQL集成快速开始指南

5分钟快速配置ETF交易系统的PostgreSQL订单记录功能。

## 🚀 快速开始（3步骤）

### 1️⃣ 安装依赖

```bash
# 安装PostgreSQL（如果还没有）
# macOS
brew install postgresql@15
brew services start postgresql@15

# Ubuntu/Debian
sudo apt install postgresql postgresql-contrib
sudo systemctl start postgresql

# 安装Python依赖
uv pip install asyncpg tenacity tabulate
```

### 2️⃣ 配置数据库

**创建数据库用户和数据库**：

```bash
# 连接到PostgreSQL
psql postgres

# 在PostgreSQL命令行中执行:
CREATE USER etf_user WITH PASSWORD 'etf_password';
CREATE DATABASE etf_trading OWNER etf_user;
GRANT ALL PRIVILEGES ON DATABASE etf_trading TO etf_user;
\q
```

**验证.env配置**（应该已经配置好）:

```bash
# PostgreSQL 数据库配置
POSTGRES_USER=etf_user
POSTGRES_PASSWORD=etf_password
POSTGRES_DB=etf_trading
POSTGRES_HOST=localhost
POSTGRES_PORT=5432

# Redis 配置
REDIS_URL=redis://localhost:6379/0
```

### 3️⃣ 初始化并测试

```bash
# 初始化数据库表
python scripts/init_database.py

# 测试集成
python scripts/test_db_integration.py

# 查看结果
python scripts/query_orders.py --stats
```

**成功输出示例**:
```
✅ PostgreSQL 连接成功
✅ 成功创建数据库 'etf_trading'
✅ 成功创建所有数据表
📊 创建的表: orders, trades, market_snapshots, strategy_metrics, pnl_records, system_logs
```

---

## ✅ 验证集成

### 方法1: 运行测试脚本

```bash
python scripts/test_db_integration.py
```

应该看到：
```
✅ PostgreSQL连接: 成功
✅ 数据库写入: 成功 (15 条记录)
✅ 数据库查询: 成功 (10 订单, 5 成交)
```

### 方法2: 启动交易系统

```bash
# 启动任意策略
python run_etf.py --strategy stg3l --env qa
```

观察日志：
```
INFO - PostgreSQL连接成功: localhost:5432/etf_trading
INFO - Redis连接成功
INFO - 订单记录器启动成功
INFO - ✅ 成功写入 5 条订单记录到PostgreSQL
```

### 方法3: 直接查询数据库

```bash
# 查看统计信息
python scripts/query_orders.py --stats

# 查看最近20条订单
python scripts/query_orders.py --orders --limit 20

# 查看特定策略
python scripts/query_orders.py --strategy stg3l
```

---

## 📊 核心功能

### 自动记录
系统会自动记录：
- ✅ 所有订单（下单、成交、取消）
- ✅ 成交记录（价格、数量、手续费）
- ✅ 策略信息（策略名称、是否刷量）
- ✅ 市场状态（净值、价差、订单簿）

### 智能降级
- 🔄 数据库不可用时自动使用CSV
- 📁 CSV文件保存在 `logs/order_records/`
- 🔁 数据库恢复后自动切换回来

### 性能优化
- ⚡ 异步批量写入（每秒最多100条）
- 🔄 自动重试（最多3次，指数退避）
- 🚫 重复数据自动跳过
- 📊 实时统计信息

---

## 🔍 常用命令

### 查看数据库
```bash
# 连接到数据库
psql -U etf_user -d etf_trading

# 列出所有表
\dt

# 查看orders表结构
\d orders

# 查询订单总数
SELECT COUNT(*) FROM orders;

# 查询最近10条订单
SELECT id, symbol, side, price, quantity, status, created_at
FROM orders
ORDER BY created_at DESC
LIMIT 10;

# 退出
\q
```

### 查看日志
```bash
# 实时查看日志
tail -f logs/stg3l/stg3l.log | grep "PostgreSQL\|订单记录"

# 查看错误日志
tail -f logs/stg3l/stg3l_error.log
```

### 查询订单
```bash
# 显示完整统计
python scripts/query_orders.py

# 只显示统计信息
python scripts/query_orders.py --stats

# 查看最近50条订单
python scripts/query_orders.py --orders --limit 50

# 查看最近30条成交
python scripts/query_orders.py --trades --limit 30

# 查看stg5l策略的订单
python scripts/query_orders.py --strategy stg5l --limit 100
```

---

## 🛠️ 故障排查

### 问题1: 连接失败

**错误**: `could not connect to server`

**解决**:
```bash
# 检查PostgreSQL是否运行
brew services list | grep postgresql  # macOS
systemctl status postgresql           # Linux

# 启动PostgreSQL
brew services start postgresql@15     # macOS
sudo systemctl start postgresql       # Linux

# 测试连接
psql -U etf_user -d etf_trading -h localhost
```

### 问题2: 权限不足

**错误**: `permission denied for table orders`

**解决**:
```sql
-- 以postgres用户登录
psql -U postgres -d etf_trading

-- 授予权限
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO etf_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO etf_user;
```

### 问题3: 依赖缺失

**错误**: `No module named 'asyncpg'`

**解决**:
```bash
uv pip install asyncpg tenacity tabulate
```

### 问题4: 数据库不存在

**解决**:
```bash
# 重新运行初始化脚本
python scripts/init_database.py
```

---

## 📈 使用PostgreSQL的优势

### vs CSV文件

| 特性 | PostgreSQL | CSV |
|------|-----------|-----|
| 查询速度 | ⚡ 快速（索引支持） | 🐌 慢（全表扫描） |
| 复杂查询 | ✅ 支持SQL | ❌ 需要Python处理 |
| 并发写入 | ✅ 安全 | ⚠️ 可能冲突 |
| 数据完整性 | ✅ 事务保证 | ❌ 无保证 |
| 统计分析 | ✅ 原生支持 | ❌ 需要pandas |
| 备份恢复 | ✅ 简单 | ⚠️ 复杂 |

### 实际使用场景

```sql
-- 查询策略表现
SELECT
    strategy_name,
    COUNT(*) as order_count,
    SUM(CASE WHEN status='FILLED' THEN 1 ELSE 0 END) as filled_count,
    AVG(price * quantity) as avg_order_value
FROM orders
WHERE created_at > NOW() - INTERVAL '1 day'
GROUP BY strategy_name;

-- 查询真实vs刷量订单占比
SELECT
    is_wash_trading,
    COUNT(*) as count,
    ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 2) as percentage
FROM orders
GROUP BY is_wash_trading;

-- 查询每小时订单数量趋势
SELECT
    DATE_TRUNC('hour', created_at) as hour,
    COUNT(*) as order_count
FROM orders
WHERE created_at > NOW() - INTERVAL '24 hours'
GROUP BY hour
ORDER BY hour;
```

---

## 🎓 进阶使用

### 数据导出
```bash
# 导出订单到CSV
psql -U etf_user -d etf_trading -c "\COPY (SELECT * FROM orders WHERE created_at > NOW() - INTERVAL '7 days') TO 'orders_last_7days.csv' CSV HEADER"

# 导出成交到Excel（需要安装pandas）
python -c "
import pandas as pd
from sqlalchemy import create_engine

engine = create_engine('postgresql://etf_user:etf_password@localhost/etf_trading')
df = pd.read_sql('SELECT * FROM trades ORDER BY traded_at DESC LIMIT 1000', engine)
df.to_excel('trades.xlsx', index=False)
"
```

### 定期维护
```bash
# 创建维护脚本 scripts/maintain_db.sh
#!/bin/bash

# 清理30天前的数据
psql -U etf_user -d etf_trading -c "
DELETE FROM orders WHERE created_at < NOW() - INTERVAL '30 days';
DELETE FROM trades WHERE traded_at < NOW() - INTERVAL '30 days';
"

# 重建索引
psql -U etf_user -d etf_trading -c "
REINDEX TABLE orders;
REINDEX TABLE trades;
"

# 更新统计信息
psql -U etf_user -d etf_trading -c "
VACUUM ANALYZE orders;
VACUUM ANALYZE trades;
"

echo "数据库维护完成"
```

### 备份恢复
```bash
# 备份数据库
pg_dump -U etf_user -d etf_trading -F c -f etf_trading_backup.dump

# 恢复数据库
pg_restore -U etf_user -d etf_trading -c etf_trading_backup.dump
```

---

## 📚 相关文档

- **完整配置指南**: `docs/POSTGRESQL_SETUP.md`
- **技术债务追踪**: `docs/TECHNICAL_DEBT.md`
- **项目进度报告**: `docs/PROJECT_PROGRESS_REPORT.md`

---

## ✨ 下一步

1. ✅ **开始交易**: PostgreSQL已配置完成，可以正常使用
2. 📊 **配置监控**: 考虑使用Grafana可视化订单数据
3. 💾 **设置备份**: 配置定期数据库备份
4. 🔍 **数据分析**: 使用SQL分析策略效果

**文档版本**: v1.0
**最后更新**: 2025-01-16
