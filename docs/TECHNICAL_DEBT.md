# 技术债务跟踪清单

**文档版本**: v1.0
**更新日期**: 2025-10-29
**项目**: XT ETF Trading System

---

## 📊 概览

### 债务统计
- **总数**: 14项TODO标记 + 3项系统级债务
- **高优先级**: 2项（影响生产功能）
- **中优先级**: 5项（增强功能）
- **低优先级**: 7项（优化项）

### 风险评估
- **总体风险**: 🟢 **低风险** - 债务在可控范围内
- **紧急度**: 🟡 **中等** - 建议1个月内完成高优先级项

---

## 🔴 高优先级债务（影响生产功能）

### 1. 订单记录器PostgreSQL集成

**文件**: `etf/storage/order_recorder.py:150`

**当前状态**:
```python
# TODO: 实际写入数据库
# async with self.async_session() as session:
#     await session.bulk_insert_mappings(Order, orders)
#     await session.commit()
```

**问题描述**:
- 当前使用CSV文件作为降级方案
- 无法进行复杂查询和数据分析
- 数据完整性依赖文件系统

**影响范围**:
- 订单历史查询功能受限
- 数据分析和报表生成困难
- 审计追踪不完整

**建议方案**:

**步骤1: 设计数据库表结构**
```sql
CREATE TABLE orders (
    id SERIAL PRIMARY KEY,
    order_id VARCHAR(50) UNIQUE NOT NULL,
    strategy_name VARCHAR(20) NOT NULL,
    symbol VARCHAR(20) NOT NULL,
    side VARCHAR(10) NOT NULL,  -- 'BUY' or 'SELL'
    order_type VARCHAR(20),  -- 'LIMIT', 'MARKET'
    price DECIMAL(20, 8),
    quantity DECIMAL(20, 8),
    status VARCHAR(20),  -- 'NEW', 'FILLED', 'CANCELED', 'REJECTED'
    fee DECIMAL(20, 8),
    is_wash_trade BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMP NOT NULL,
    updated_at TIMESTAMP,
    INDEX idx_strategy_time (strategy_name, created_at),
    INDEX idx_symbol_time (symbol, created_at),
    INDEX idx_order_id (order_id)
);
```

**步骤2: 实现异步批量写入**
```python
async def _flush_to_db(self):
    """批量写入数据库"""
    if not self._buffer:
        return

    orders_to_insert = list(self._buffer)
    self._buffer.clear()

    try:
        async with self.async_session() as session:
            # 使用bulk_insert_mappings提高性能
            await session.execute(
                insert(Order),
                [order.to_dict() for order in orders_to_insert]
            )
            await session.commit()

            logger.info(f"成功写入 {len(orders_to_insert)} 条订单记录")

    except Exception as e:
        logger.error(f"订单写入数据库失败: {e}")
        # 降级到CSV
        self._write_to_csv(orders_to_insert)
```

**步骤3: 添加重试机制**
```python
@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=2, max=10),
    retry=retry_if_exception_type(OperationalError)
)
async def _flush_to_db_with_retry(self):
    """带重试的数据库写入"""
    await self._flush_to_db()
```

**步骤4: 数据迁移**
```python
async def migrate_csv_to_db():
    """迁移历史CSV数据到数据库"""
    csv_files = glob.glob("logs/*/orders_*.csv")
    for csv_file in csv_files:
        # 读取CSV并批量插入
        df = pd.read_csv(csv_file)
        # ... 批量插入逻辑
```

**预期工作量**: 2-3天
**建议完成时间**: 1周内
**责任人**: 后端开发团队
**优先级**: 🔴 **高**

---

### 2. 稳定性监控异步实现

**文件**: `run_etf.py:746`

**当前状态**:
```python
# TODO: stability_monitor.start_monitoring() 需要异步事件循环
# 完整的异步监控将在 Phase 2 实现
# stability_monitor.start_monitoring()
```

**问题描述**:
- 稳定性监控仅在同步模式下工作
- 无法与主异步事件循环集成
- 无法实时检测系统异常

**影响范围**:
- 系统健康状态监控不完整
- 问题发现延迟
- 无法自动触发告警

**建议方案**:

**步骤1: 改造为异步监控**
```python
class StabilityMonitor:
    async def start_monitoring(self):
        """启动异步监控"""
        tasks = [
            asyncio.create_task(self._monitor_api_health()),
            asyncio.create_task(self._monitor_websocket_health()),
            asyncio.create_task(self._monitor_order_success_rate()),
            asyncio.create_task(self._monitor_system_resources()),
        ]
        await asyncio.gather(*tasks, return_exceptions=True)

    async def _monitor_api_health(self):
        """监控API连接健康"""
        while True:
            try:
                # 检查API响应时间
                start = time.time()
                await self.client.get_server_time()
                latency = time.time() - start

                if latency > 1.0:
                    await self._trigger_alert("API延迟过高", latency)

            except Exception as e:
                await self._trigger_alert("API连接失败", str(e))

            await asyncio.sleep(30)  # 30秒检查一次

    async def _monitor_websocket_health(self):
        """监控WebSocket连接健康"""
        while True:
            if not self.ws_manager.is_connected():
                await self._trigger_alert("WebSocket断开连接")

            await asyncio.sleep(10)

    async def _monitor_order_success_rate(self):
        """监控订单成功率"""
        while True:
            success_rate = await self._get_order_success_rate()
            if success_rate < 0.9:  # 成功率低于90%
                await self._trigger_alert(
                    "订单成功率过低",
                    f"当前成功率: {success_rate:.2%}"
                )

            await asyncio.sleep(60)
```

**步骤2: 集成到主循环**
```python
async def main():
    # ... 初始化代码 ...

    # 启动监控任务（不阻塞主循环）
    monitoring_task = asyncio.create_task(
        stability_monitor.start_monitoring()
    )

    try:
        # 主交易循环
        await trading_loop()
    finally:
        # 停止监控
        monitoring_task.cancel()
```

**步骤3: 配置告警规则**
```yaml
monitoring:
  api_latency_threshold: 1.0  # 秒
  order_success_rate_threshold: 0.9  # 90%
  websocket_reconnect_threshold: 5  # 5次重连
  alert_channels:
    - log
    - email
    - dingtalk
```

**预期工作量**: 3-4天
**建议完成时间**: 2周内
**责任人**: 后端开发 + 运维团队
**优先级**: 🔴 **高**

---

## 🟡 中优先级债务（增强功能）

### 3. 动态参数调整API

**文件**: 多个策略配置文件

**问题描述**:
- 当前参数修改需要重启系统
- 无法在运行时优化策略参数
- 策略调整响应慢

**建议方案**:

**步骤1: 设计配置更新API**
```python
class ConfigManager:
    def __init__(self):
        self.config = self._load_config()
        self.watchers = []

    async def update_parameter(self, strategy: str, param: str, value: Any):
        """更新单个参数"""
        if strategy not in self.config:
            raise ValueError(f"策略 {strategy} 不存在")

        if param not in self.config[strategy]:
            raise ValueError(f"参数 {param} 不存在")

        # 验证参数值
        self._validate_parameter(param, value)

        # 更新配置
        old_value = self.config[strategy][param]
        self.config[strategy][param] = value

        # 通知所有观察者
        await self._notify_watchers(strategy, param, old_value, value)

        logger.info(f"参数更新: {strategy}.{param} {old_value} -> {value}")
```

**步骤2: HTTP API接口**
```python
from fastapi import FastAPI, HTTPException

app = FastAPI()
config_manager = ConfigManager()

@app.put("/api/config/{strategy}/{parameter}")
async def update_parameter(
    strategy: str,
    parameter: str,
    value: float = Body(...)
):
    try:
        await config_manager.update_parameter(strategy, parameter, value)
        return {"status": "success", "message": "参数已更新"}
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))

@app.get("/api/config/{strategy}")
async def get_strategy_config(strategy: str):
    """获取策略当前配置"""
    return config_manager.get_config(strategy)
```

**步骤3: 参数热更新**
```python
class MarketMaker:
    def __init__(self, config_manager: ConfigManager):
        self.config_manager = config_manager
        # 注册参数变更监听
        config_manager.register_watcher(self._on_config_changed)

    async def _on_config_changed(self, strategy: str, param: str, value: Any):
        """配置变更回调"""
        if param == "bid_ask_spread":
            self.bid_ask_spread = value
            logger.info(f"价差已更新为 {value}")
        elif param == "sleep_interval":
            self.sleep_interval = value
            logger.info(f"循环间隔已更新为 {value}秒")
```

**可调整参数列表**:
- `bid_ask_spread`: 买卖价差
- `sleep_interval`: 主循环间隔
- `washing_interval`: 刷量间隔
- `max_position`: 最大仓位
- `stop_loss.fixed_threshold`: 固定止损阈值
- `stop_loss.trailing_stop`: 移动止损回撤

**预期工作量**: 3-4天
**建议完成时间**: 2周内
**责任人**: 后端开发团队
**优先级**: 🟡 **中**

---

### 4. 高级监控指标

**文件**: `etf/observability/metrics.py`

**问题描述**:
- 当前监控指标基础
- 缺少高级分析指标
- 策略性能分析困难

**建议增强指标**:

**1. 策略PnL实时计算**
```python
class PnLTracker:
    def __init__(self):
        self.entry_positions = {}  # 入场仓位
        self.realized_pnl = 0.0
        self.unrealized_pnl = 0.0

    async def update_pnl(self, current_price: float):
        """更新PnL"""
        # 计算未实现盈亏
        self.unrealized_pnl = self._calculate_unrealized(current_price)

        # 记录到metrics
        metrics.record_gauge(
            "strategy.unrealized_pnl",
            self.unrealized_pnl,
            {"strategy": self.strategy_name}
        )

        metrics.record_gauge(
            "strategy.realized_pnl",
            self.realized_pnl,
            {"strategy": self.strategy_name}
        )
```

**2. 刷量/真实交易比例监控**
```python
class TradeRatioMonitor:
    def __init__(self):
        self.wash_trades = 0
        self.real_trades = 0

    def record_trade(self, is_wash: bool):
        """记录交易"""
        if is_wash:
            self.wash_trades += 1
        else:
            self.real_trades += 1

        # 计算比例
        total = self.wash_trades + self.real_trades
        if total > 0:
            ratio = self.real_trades / total
            metrics.record_gauge(
                "strategy.real_trade_ratio",
                ratio,
                {"strategy": self.strategy_name}
            )
```

**3. 订单成功率趋势**
```python
class OrderSuccessRateTrend:
    def __init__(self, window_size=100):
        self.window = deque(maxlen=window_size)

    def record_order_result(self, success: bool):
        """记录订单结果"""
        self.window.append(1 if success else 0)

        # 计算移动平均成功率
        if len(self.window) > 0:
            success_rate = sum(self.window) / len(self.window)
            metrics.record_gauge(
                "strategy.order_success_rate_ma",
                success_rate,
                {"strategy": self.strategy_name}
            )
```

**预期工作量**: 2-3天
**建议完成时间**: 3周内
**责任人**: 后端开发团队
**优先级**: 🟡 **中**

---

### 5. 集成测试覆盖率提升

**当前状态**: 约50%覆盖率（估算）

**目标**: 80%+覆盖率

**测试优先级**:

**P0 - 核心交易流程**
```python
async def test_full_trading_cycle():
    """测试完整交易周期"""
    # 1. 启动策略
    # 2. 接收市场数据
    # 3. 风险评估
    # 4. 生成订单
    # 5. 订单执行
    # 6. 订单记录
    pass

async def test_risk_control_integration():
    """测试风险控制集成"""
    # 1. 触发Level 3风险
    # 2. 验证交易暂停
    # 3. 风险恢复
    # 4. 验证交易恢复
    pass

async def test_stop_loss_execution():
    """测试止损执行"""
    # 1. 建立仓位
    # 2. 价格触发止损
    # 3. 验证订单撤销
    # 4. 验证冷却期
    pass
```

**P1 - WebSocket和数据流**
```python
async def test_websocket_reconnection():
    """测试WebSocket重连"""
    # 1. 建立连接
    # 2. 模拟断线
    # 3. 验证自动重连
    # 4. 验证数据恢复
    pass

async def test_depth_cache_failover():
    """测试深度数据降级"""
    # 1. WebSocket数据正常
    # 2. WebSocket断开
    # 3. 验证使用缓存
    # 4. 验证降级到REST
    pass
```

**P2 - 订单管理**
```python
async def test_order_validation():
    """测试订单验证"""
    # 各种非法参数测试
    pass

async def test_circuit_breaker():
    """测试熔断器"""
    # 1. 模拟5次连续失败
    # 2. 验证熔断触发
    # 3. 等待60秒
    # 4. 验证熔断恢复
    pass

async def test_blacklist_mechanism():
    """测试黑名单机制"""
    # 1. 触发永久错误
    # 2. 验证加入黑名单
    # 3. 验证后续订单被拒绝
    pass
```

**工具和框架**:
```bash
# 安装测试依赖
pip install pytest pytest-asyncio pytest-cov pytest-mock

# 运行测试
pytest tests/ --cov=etf --cov-report=html

# 查看覆盖率报告
open htmlcov/index.html
```

**预期工作量**: 1-2周
**建议完成时间**: 1个月内
**责任人**: QA + 开发团队
**优先级**: 🟡 **中**

---

### 6. Grafana仪表板配置

**问题描述**:
- 当前仅收集指标，无可视化
- 无法直观监控系统状态
- 问题发现依赖日志查看

**建议仪表板**:

**1. 交易监控仪表板**
- 订单成功率（实时/1小时MA）
- 订单数量（真实/刷量分离）
- 订单延迟分布
- 策略PnL趋势

**2. 风险监控仪表板**
- 当前风险等级
- 市场波动率
- 订单簿深度评分
- 止损触发统计

**3. 系统健康仪表板**
- API延迟
- WebSocket连接状态
- 熔断器状态
- 错误率趋势

**4. 资源监控仪表板**
- CPU使用率
- 内存使用率
- Redis连接数
- PostgreSQL连接数

**配置示例**:
```json
{
  "dashboard": {
    "title": "XT ETF Trading - 交易监控",
    "panels": [
      {
        "title": "订单成功率",
        "targets": [
          {
            "expr": "rate(orders_success_total[1m]) / rate(orders_placed_total[1m])",
            "legendFormat": "{{strategy}}"
          }
        ]
      }
    ]
  }
}
```

**预期工作量**: 2-3天
**建议完成时间**: 2周内
**责任人**: 运维团队
**优先级**: 🟡 **中**

---

### 7. 告警规则配置

**问题描述**:
- 监控数据已收集，但无告警
- 问题发现依赖人工巡检
- 无法及时响应异常

**建议告警规则**:

**关键告警（Slack/钉钉/邮件）**:
```yaml
groups:
  - name: critical_alerts
    rules:
      - alert: OrderSuccessRateLow
        expr: rate(orders_success_total[5m]) / rate(orders_placed_total[5m]) < 0.9
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "订单成功率过低"
          description: "{{ $labels.strategy }} 5分钟订单成功率 {{ $value | humanizePercentage }}"

      - alert: StopLossTriggeredFrequently
        expr: rate(stop_loss_triggered_total[1h]) > 3
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "止损频繁触发"
          description: "{{ $labels.strategy }} 1小时内触发 {{ $value }} 次止损"

      - alert: WebSocketDisconnected
        expr: websocket_connected == 0
        for: 1m
        labels:
          severity: critical
        annotations:
          summary: "WebSocket连接断开"
```

**警告告警（仅日志）**:
```yaml
  - name: warning_alerts
    rules:
      - alert: APILatencyHigh
        expr: api_latency_seconds > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API延迟过高"

      - alert: RiskLevelHigh
        expr: risk_level >= 3
        for: 2m
        labels:
          severity: warning
        annotations:
          summary: "风险等级高"
```

**预期工作量**: 1-2天
**建议完成时间**: 2周内
**责任人**: 运维团队
**优先级**: 🟡 **中**

---

## 🟢 低优先级债务（优化项）

### 8. 缓存策略优化

**文件**: `etf/symbol_config.py:80`

**问题描述**:
- Symbol配置刷新间隔硬编码（1小时）
- 无法根据场景动态调整

**建议方案**:
```python
class SymbolConfig:
    def __init__(self, refresh_interval: int = 3600):
        self.refresh_interval = refresh_interval  # 可配置

    async def start_auto_refresh(self):
        """自动刷新配置"""
        while True:
            await asyncio.sleep(self.refresh_interval)
            await self.refresh_all_configs()
```

**预期工作量**: 1小时
**建议完成时间**: 有空闲时
**优先级**: 🟢 **低**

---

### 9. 日志压缩

**文件**: `etf/utils/logger.py:60`

**问题描述**:
- 过期日志仅删除，不压缩
- 浪费磁盘空间

**建议方案**:
```python
import gzip
import shutil

def compress_old_logs(log_dir: str, days: int = 7):
    """压缩N天前的日志"""
    cutoff = datetime.now() - timedelta(days=days)
    for log_file in glob.glob(f"{log_dir}/*.log.*"):
        if os.path.getmtime(log_file) < cutoff.timestamp():
            # 压缩
            with open(log_file, 'rb') as f_in:
                with gzip.open(f"{log_file}.gz", 'wb') as f_out:
                    shutil.copyfileobj(f_in, f_out)
            os.remove(log_file)
```

**预期工作量**: 2小时
**建议完成时间**: 有空闲时
**优先级**: 🟢 **低**

---

### 10-14. 其他低优先级项

**10. 函数文档完善** - 约10处缺少docstring
**11. 异常处理增强** - 5处可优化的try-except
**12. 代码注释优化** - 部分复杂逻辑缺少注释
**13. 类型注解补充** - 部分函数缺少类型注解
**14. 配置验证增强** - 配置参数合法性检查

**预期工作量**: 共2-3天
**建议完成时间**: 随代码修改逐步完善
**优先级**: 🟢 **低**

---

## 📅 实施计划

### 第1周（2025-11-04至2025-11-10）
- [x] ✅ 提交当前修改
- [x] ✅ QA环境验证
- [ ] 🔴 订单记录器PostgreSQL集成

### 第2周（2025-11-11至2025-11-17）
- [ ] 🔴 稳定性监控异步实现
- [ ] 🟡 Grafana仪表板配置
- [ ] 🟡 告警规则配置

### 第3周（2025-11-18至2025-11-24）
- [ ] 🟡 动态参数调整API
- [ ] 🟡 高级监控指标
- [ ] 🟡 集成测试覆盖率提升（开始）

### 第4周（2025-11-25至2025-12-01）
- [ ] 🟡 集成测试覆盖率提升（完成）
- [ ] 🟢 低优先级债务清理（按需）

---

## 📈 进度跟踪

### 完成度统计
- **高优先级**: 0/2 (0%)
- **中优先级**: 0/5 (0%)
- **低优先级**: 0/7 (0%)

**总体完成度**: 0/14 (0%)

### 更新日志
- 2025-10-29: 创建技术债务清单，识别14项债务
- (待更新)

---

## 🎯 成功标准

### 高优先级完成标准
- [ ] 订单记录器PostgreSQL集成完成，测试通过
- [ ] 稳定性监控异步实现，24小时运行无异常

### 中优先级完成标准
- [ ] 动态参数调整API上线，支持主要参数调整
- [ ] Grafana仪表板配置完成，4个仪表板上线
- [ ] 告警规则生效，关键告警正常触发
- [ ] 高级监控指标收集，数据准确
- [ ] 集成测试覆盖率达到80%+

### 低优先级完成标准
- [ ] 所有低优先级项完成50%+

---

**文档结束**

如需更新进度，请修改本文档的"进度跟踪"和"更新日志"部分。
