# PostgreSQL 集成配置指南

ETF交易系统订单记录器PostgreSQL集成使用指南。

## 📋 目录

1. [系统要求](#系统要求)
2. [安装PostgreSQL](#安装postgresql)
3. [配置环境变量](#配置环境变量)
4. [初始化数据库](#初始化数据库)
5. [验证集成](#验证集成)
6. [常见问题](#常见问题)

---

## 系统要求

### 软件要求
- **PostgreSQL**: 12.0 或更高版本
- **Python**: 3.9 或更高版本
- **依赖包**: asyncpg, tenacity, python-dotenv

### 安装依赖
```bash
# 使用 uv 安装（推荐）
uv pip install asyncpg tenacity python-dotenv tabulate

# 或使用 pip
pip install asyncpg tenacity python-dotenv tabulate
```

---

## 安装PostgreSQL

### macOS
```bash
# 使用Homebrew安装
brew install postgresql@15

# 启动PostgreSQL服务
brew services start postgresql@15

# 验证安装
psql --version
```

### Ubuntu/Debian
```bash
# 安装PostgreSQL
sudo apt update
sudo apt install postgresql postgresql-contrib

# 启动服务
sudo systemctl start postgresql
sudo systemctl enable postgresql

# 验证安装
psql --version
```

### Windows
1. 下载安装包：https://www.postgresql.org/download/windows/
2. 运行安装向导
3. 记住设置的超级用户密码

---

## 配置环境变量

### 1. 创建PostgreSQL用户和数据库

```bash
# 切换到postgres用户（Linux/macOS）
sudo -u postgres psql

# 或直接连接（macOS Homebrew）
psql postgres
```

在PostgreSQL命令行中执行：
```sql
-- 创建用户
CREATE USER etf_user WITH PASSWORD 'etf_password';

-- 创建数据库
CREATE DATABASE etf_trading OWNER etf_user;

-- 授予权限
GRANT ALL PRIVILEGES ON DATABASE etf_trading TO etf_user;

-- 退出
\q
```

### 2. 配置.env文件

编辑项目根目录的 `.env` 文件：

```bash
# PostgreSQL 数据库配置
psql_user=etf_user
psql_password=etf_password
psql_db=etf_trading
psql_host=localhost
psql_port=5432

# Redis 配置
REDIS_URL=redis://localhost:6379/0
```

**生产环境建议**:
- 使用强密码
- 限制数据库访问IP
- 启用SSL连接

---

## 初始化数据库

### 自动初始化（推荐）

运行初始化脚本：
```bash
python scripts/init_database.py
```

脚本会自动：
1. ✅ 验证PostgreSQL连接
2. 📦 创建数据库（如果不存在）
3. 📊 创建所有数据表

**输出示例**:
```
2025-01-16 10:00:00 - INFO - 开始初始化PostgreSQL数据库...

📡 步骤 1/3: 验证PostgreSQL连接...
✅ PostgreSQL 连接成功
📌 版本: PostgreSQL 15.5

📦 步骤 2/3: 确保数据库存在...
✅ 数据库 'etf_trading' 已存在

📊 步骤 3/3: 创建数据表...
✅ 成功创建所有数据表
📊 创建的表: orders, trades, market_snapshots, strategy_metrics, pnl_records, system_logs

============================================================
PostgreSQL 数据库初始化完成
============================================================
```

### 手动初始化

使用Python脚本：
```python
import asyncio
from etf.storage.models import Base, create_tables
from sqlalchemy import create_engine

# 同步引擎（仅用于初始化）
engine = create_engine("postgresql://etf_user:etf_password@localhost/etf_trading")

# 创建所有表
Base.metadata.create_all(engine)
```

---

## 验证集成

### 1. 查看数据库状态

```bash
# 连接到数据库
psql -U etf_user -d etf_trading

# 列出所有表
\dt

# 查看orders表结构
\d orders

# 退出
\q
```

### 2. 查询订单记录

使用查询脚本：
```bash
# 查看统计信息
python scripts/query_orders.py --stats

# 查看最近20条订单
python scripts/query_orders.py --orders --limit 20

# 查看最近20条成交
python scripts/query_orders.py --trades --limit 20

# 查看特定策略的订单
python scripts/query_orders.py --strategy stg3l --limit 50
```

### 3. 启动交易系统测试

```bash
# 启动策略（会自动使用PostgreSQL记录订单）
python run_etf.py --strategy stg3l --env qa
```

观察日志输出：
```
2025-01-16 10:05:00 - INFO - PostgreSQL连接成功: localhost:5432/etf_trading
2025-01-16 10:05:00 - INFO - Redis连接成功
2025-01-16 10:05:00 - INFO - 订单记录器启动成功

# 订单记录成功
2025-01-16 10:05:15 - INFO - ✅ 成功写入 5 条订单记录到PostgreSQL
2025-01-16 10:05:20 - INFO - ✅ 成功写入 3 条成交记录到PostgreSQL
```

---

## 数据库表结构

### orders 表（订单记录）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| symbol | VARCHAR(20) | 交易对 |
| order_id | VARCHAR(50) | 订单ID（唯一） |
| side | VARCHAR(10) | 买卖方向（BUY/SELL） |
| price | NUMERIC(20,8) | 价格 |
| quantity | NUMERIC(20,8) | 数量 |
| status | VARCHAR(20) | 订单状态 |
| strategy_name | VARCHAR(20) | 策略名称 |
| is_wash_trading | BOOLEAN | 是否刷量订单 |
| created_at | TIMESTAMP | 创建时间 |

### trades 表（成交记录）
| 字段 | 类型 | 说明 |
|------|------|------|
| id | SERIAL | 主键 |
| symbol | VARCHAR(20) | 交易对 |
| trade_id | VARCHAR(50) | 成交ID（唯一） |
| order_id | VARCHAR(50) | 订单ID |
| price | NUMERIC(20,8) | 成交价格 |
| quantity | NUMERIC(20,8) | 成交数量 |
| fee | NUMERIC(20,8) | 手续费 |
| is_wash_trading | BOOLEAN | 是否刷量成交 |
| traded_at | TIMESTAMP | 成交时间 |

**其他表**: market_snapshots, strategy_metrics, pnl_records, system_logs

---

## 特性说明

### 1. 异步批量写入
- 订单和成交记录异步写入队列
- 每秒批量处理最多100条记录
- 最小化对交易性能的影响

### 2. 自动重试机制
- 使用tenacity库实现指数退避重试
- 最多重试3次
- 自动处理临时连接问题

### 3. CSV降级方案
- 数据库不可用时自动降级到CSV
- 数据保存在 `logs/order_records/`
- 恢复后可手动导入到数据库

### 4. 重复数据处理
- 自动检测唯一性约束冲突
- 遇到重复订单时自动跳过
- 不影响后续数据写入

### 5. 统计信息
```python
from etf.storage import get_order_recorder

recorder = get_order_recorder()
stats = recorder.get_stats()

# 输出示例:
# {
#   'total_orders': 1250,
#   'real_orders': 380,
#   'wash_orders': 870,
#   'db_write_success': 1200,
#   'db_write_failed': 5,
#   'csv_fallback_count': 45,
#   'db_available': True,
#   'queue_sizes': {'orders': 2, 'trades': 0}
# }
```

---

## 常见问题

### Q1: 数据库连接失败

**错误信息**:
```
❌ PostgreSQL连接失败: could not connect to server
```

**解决方案**:
1. 确认PostgreSQL服务运行:
   ```bash
   # macOS
   brew services list | grep postgresql

   # Linux
   systemctl status postgresql
   ```

2. 检查.env配置是否正确

3. 测试连接:
   ```bash
   psql -U etf_user -d etf_trading -h localhost
   ```

### Q2: 权限不足

**错误信息**:
```
permission denied for table orders
```

**解决方案**:
```sql
-- 以postgres超级用户登录
psql -U postgres -d etf_trading

-- 授予所有权限
GRANT ALL PRIVILEGES ON ALL TABLES IN SCHEMA public TO etf_user;
GRANT ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public TO etf_user;
```

### Q3: 数据库已存在旧表

**解决方案**:
```bash
# 删除所有旧表（谨慎操作！）
python -c "
import asyncio
from etf.storage.models import drop_tables
from sqlalchemy import create_engine

engine = create_engine('postgresql://etf_user:etf_password@localhost/etf_trading')
drop_tables(engine)
"

# 重新初始化
python scripts/init_database.py
```

### Q4: 依赖包缺失

**错误信息**:
```
ModuleNotFoundError: No module named 'asyncpg'
```

**解决方案**:
```bash
uv pip install asyncpg tenacity python-dotenv
```

### Q5: CSV降级模式

如果数据库暂时不可用，系统会自动使用CSV降级：

```
📝 降级写入 10 条订单记录到CSV: orders_20250116.csv
```

**恢复方案**:
1. 修复数据库问题
2. 重启系统（自动恢复到PostgreSQL模式）
3. 手动导入CSV数据（可选）

---

## 性能优化建议

### 1. 数据库索引
系统已自动创建以下索引：
- `idx_symbol_created`: (symbol, created_at)
- `idx_strategy_wash`: (strategy_name, is_wash_trading)
- `idx_order_id`: (order_id) UNIQUE

### 2. 连接池配置
默认配置已优化，如需调整：
```python
# etf/storage/order_recorder.py
engine = create_async_engine(
    db_url,
    pool_size=20,        # 连接池大小
    max_overflow=10,     # 最大溢出连接
    pool_recycle=3600,   # 连接回收时间（秒）
)
```

### 3. 批量写入优化
```python
# 调整批量大小（默认100）
# etf/storage/order_recorder.py:359
while not self.order_queue.empty() and len(orders) < 100:
```

### 4. 定期维护
```sql
-- 清理过期数据（30天前）
DELETE FROM orders WHERE created_at < NOW() - INTERVAL '30 days';
DELETE FROM trades WHERE traded_at < NOW() - INTERVAL '30 days';

-- 重建索引
REINDEX TABLE orders;
REINDEX TABLE trades;

-- 更新统计信息
VACUUM ANALYZE orders;
VACUUM ANALYZE trades;
```

---

## 下一步

✅ PostgreSQL集成完成后，建议：

1. **配置监控**: 使用Grafana可视化订单数据
2. **设置备份**: 定期备份PostgreSQL数据库
3. **优化查询**: 根据实际使用情况创建额外索引
4. **数据分析**: 使用SQL查询分析交易策略效果

---

**文档版本**: v1.0
**最后更新**: 2025-01-16
