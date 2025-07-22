# ETF交易系统使用指南

本指南提供ETF交易系统的完整使用说明，包括安装、配置、运行和监控等所有操作步骤。

## 目录

- [快速开始](#快速开始)
- [系统安装](#系统安装)
- [配置管理](#配置管理)
- [运行系统](#运行系统)
- [监控和维护](#监控和维护)
- [故障排查](#故障排查)
- [性能优化](#性能优化)

---

## 快速开始

### 环境要求

- Python 3.9+
- Redis 6.0+
- 8GB+ RAM
- 2+ CPU cores

### 5分钟启动

```bash
# 1. 克隆并进入项目目录
cd xt_etf

# 2. 快速环境设置（推荐使用uv）
./scripts/setup_uv.sh

# 3. 激活环境
source .venv/bin/activate

# 4. 启动Redis（如未运行）
redis-server

# 5. 配置API密钥
cp APIKey_template.json APIKey_prod.json
# 编辑APIKey_prod.json添加真实API密钥

# 6. 启动策略
python run_etf.py --strategy stg3l
```

---

## 系统安装

### 方法1: 使用uv（推荐）

```bash
# 安装uv包管理器
curl -LsSf https://astral.sh/uv/install.sh | sh

# 运行自动设置脚本
./scripts/setup_uv.sh

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows
```

### 方法2: 传统pip安装

```bash
# 创建虚拟环境
python -m venv .venv
source .venv/bin/activate

# 安装依赖
pip install -e .
pip install -r requirements.txt
```

### 系统依赖

#### Redis安装

**Ubuntu/Debian:**
```bash
sudo apt update
sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis
```

**macOS:**
```bash
brew install redis
brew services start redis
```

**Docker:**
```bash
docker run -d -p 6379:6379 --name redis redis:alpine
```

---

## 配置管理

### API密钥配置

创建API密钥文件：

```bash
cp APIKey_template.json APIKey_prod.json
```

编辑`APIKey_prod.json`：
```json
{
  "api_key": "your_api_key",
  "secret_key": "your_secret_key",
  "passphrase": "your_passphrase",
  "sandbox": false
}
```

### 策略配置

系统预配置了4种策略，配置文件位于`config/strategies.yaml`：

```yaml
stg3l:  # BTC 3x Long
  symbol: "btc3l_usdt"
  leverage: 3
  direction: "long"
  bid_ask_spread: 0.008
  max_position: 100000
  stop_loss: 0.02

stg3s:  # BTC 3x Short  
  symbol: "btc3s_usdt"
  leverage: 3
  direction: "short"
  bid_ask_spread: 0.012
  max_position: 100000
  stop_loss: 0.025

stg5l:  # BTC 5x Long
  symbol: "btc5l_usdt"
  leverage: 5
  direction: "long"
  bid_ask_spread: 0.015
  max_position: 50000
  stop_loss: 0.05

stg5s:  # BTC 5x Short
  symbol: "btc5s_usdt"
  leverage: 5
  direction: "short"
  bid_ask_spread: 0.025
  max_position: 50000
  stop_loss: 0.05
```

### 环境配置

支持多环境配置：

- `--env prod`: 生产环境（默认）
- `--env qa`: 测试环境
- `--env dev`: 开发环境

---

## 运行系统

### 单策略运行

```bash
# 运行指定策略
python run_etf.py --strategy stg3l

# 指定环境
python run_etf.py --strategy stg3l --env prod

# 覆盖参数
python run_etf.py --strategy stg3l --bid-ask-spread 0.02
```

### 多策略运行

#### 方法1: PM2管理（推荐生产环境）

```bash
# 安装PM2
npm install -g pm2

# 启动所有策略
pm2 start ecosystem.config.js

# 启动指定策略
pm2 start ecosystem.config.js --only etf-stg3l

# 监控状态
pm2 monit

# 查看日志
pm2 logs etf-stg3l

# 重启策略
pm2 restart etf-stg3l

# 停止策略
pm2 stop etf-stg3l
```

#### 方法2: 便携脚本

```bash
# 快速启动脚本
./scripts/run_stg3l.sh  # 3x long
./scripts/run_stg3s.sh  # 3x short
./scripts/run_stg5l.sh  # 5x long  
./scripts/run_stg5s.sh  # 5x short
```

#### 方法3: 开发模式

```bash
# 同时启动净值服务和交易
./scripts/dev_start.sh stg3l
```

### 系统组件

#### 主要组件

1. **净值计算器** - 实时计算ETF净值
2. **做市商** - 提供流动性和价格发现
3. **洗盘控制器** - 维护价格连续性
4. **风险控制器** - 监控和控制风险
5. **订单管理器** - 处理订单执行

#### 独立运行组件

```bash
# 仅运行净值计算
python run_net_value.py --strategy stg3l

# 仅运行监控
python monitor_low_freq.py
```

---

## 监控和维护

### 实时监控

#### 系统状态监控

```bash
# PM2监控面板
pm2 monit

# 查看所有进程
pm2 list

# 资源使用情况
pm2 show etf-stg3l
```

#### 日志监控

```bash
# 实时日志
pm2 logs etf-stg3l --lines 100

# 错误日志
pm2 logs etf-stg3l --err

# 输出日志
pm2 logs etf-stg3l --out
```

### 性能监控

#### 低频策略监控

```bash
# 运行性能监控
python monitor_low_freq.py
```

监控指标：
- 洗盘频率：60-120次/小时
- 真实交易比例：5-30%
- 净值偏差：<5%
- 订单成功率：>95%

#### 系统指标

```python
# 获取做市商性能统计
stats = market_maker.get_performance_stats()
print(f"订单匹配耗时: {stats['order_matching']['avg_time']:.4f}s")

# 获取洗盘交易统计
wash_stats = wash_controller.get_performance_stats() 
print(f"洗盘交易次数: {wash_stats['wash_trading']['count']}")
```

### Redis监控

```bash
# 连接Redis查看状态
redis-cli info

# 查看净值数据
redis-cli get netvalue_btc3l

# 监控Redis内存使用
redis-cli info memory
```

### 健康检查

```bash
# 运行测试套件
./scripts/run_tests.sh

# 检查特定组件
pytest tests/test_market_making.py -v

# 基准测试
pytest tests/test_performance_benchmarks.py
```

---

## 故障排查

### 常见问题

#### 1. 连接问题

**症状**: WebSocket连接失败或频繁断线
```
WebSocket connection failed: Connection timeout
```

**解决方案**:
```bash
# 检查网络连接
ping api.example.com

# 检查API密钥
python -c "from etf.client import test_connection; test_connection()"

# 重启连接
pm2 restart etf-stg3l
```

#### 2. Redis连接问题

**症状**: Redis连接失败
```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**解决方案**:
```bash
# 检查Redis状态
systemctl status redis
redis-cli ping

# 重启Redis
systemctl restart redis

# 检查端口占用
netstat -tlnp | grep 6379
```

#### 3. 内存不足

**症状**: 系统OOM或性能下降
```
MemoryError: Unable to allocate memory
```

**解决方案**:
```bash
# 检查内存使用
free -h
pm2 show etf-stg3l

# 重启高内存进程
pm2 restart etf-stg3l

# 清理日志
pm2 flush
```

#### 4. API限频

**症状**: 请求被拒绝
```
APIError: Rate limit exceeded
```

**解决方案**:
- 检查请求频率配置
- 增加重试延迟
- 联系交易所提高限额

### 调试工具

#### 启用调试日志

```python
# 修改日志级别
logging.basicConfig(level=logging.DEBUG)

# 或在运行时
python run_etf.py --strategy stg3l --log-level DEBUG
```

#### 性能分析

```bash
# 运行性能基准测试
pytest tests/test_performance_benchmarks.py -v -s

# 内存分析
python -m memory_profiler run_etf.py --strategy stg3l
```

---

## 性能优化

### 系统优化

#### Redis优化

```bash
# 编辑redis.conf
sudo nano /etc/redis/redis.conf

# 关键配置
maxmemory 2gb
maxmemory-policy allkeys-lru
save 900 1
```

#### Python优化

```bash
# 使用优化的Python解释器
export PYTHONOPTIMIZE=1

# 启用快速随机数生成
export PYTHONHASHSEED=random
```

### 策略优化

#### 批量处理优化

```python
# 使用批量优化
from etf.utils.optimization import optimize_batch_operations

batches = optimize_batch_operations(orders, max_batch_size=100, operation_type="mixed")
```

#### 异步处理优化

```python
# 使用异步处理器
from etf.utils.optimization import async_order_processor

result = await async_order_processor.process_orders_async(
    orders, processor_func
)
```

### 监控优化建议

1. **定期清理日志**: 设置日志轮转，防止磁盘空间不足
2. **监控内存使用**: 设置内存告警阈值
3. **网络监控**: 监控API请求延迟和成功率
4. **定期重启**: 建议每24小时重启一次策略进程

---

## 安全建议

### API密钥安全

1. **权限最小化**: 只授予必要的交易权限
2. **定期轮换**: 定期更换API密钥
3. **环境隔离**: 不同环境使用不同密钥
4. **访问限制**: 限制IP白名单

### 系统安全

```bash
# 设置文件权限
chmod 600 APIKey*.json
chown $USER:$USER APIKey*.json

# 防火墙配置
ufw allow 6379  # Redis端口
ufw enable
```

---

## 附录

### 常用命令速查

```bash
# 系统启动
python run_etf.py --strategy stg3l

# 查看状态
pm2 list
pm2 logs etf-stg3l

# 性能监控  
python monitor_low_freq.py

# 运行测试
./scripts/run_tests.sh

# 重启服务
pm2 restart all
```

### 配置模板

详见配置文件：
- `config/strategies.yaml` - 策略配置
- `APIKey_template.json` - API密钥模板
- `ecosystem.config.js` - PM2配置

---

*最后更新: 2025-01-22*
*版本: 1.0.0*