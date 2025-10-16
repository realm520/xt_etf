# OpenTelemetry 可观测性系统

## 📊 概述

本系统使用 OpenTelemetry 统一导出 Metrics（指标），可连接到 Prometheus、Grafana、OTLP Collector 等标准监控系统。

**版本**: 1.0.0
**最后更新**: 2025-01-16

---

## 🎯 架构说明

```
ETF 交易系统
    ├─ run_etf.py (主程序)
    ├─ ImprovedNetValue (净值计算器)
    ├─ RiskController (风险控制器)
    └─ OpenTelemetry Metrics Collector
           ↓ (OTLP gRPC)
    OTLP Collector (localhost:4317)
           ↓
    ┌─────────┬──────────┬──────────┐
    Prometheus  Jaeger    Grafana Cloud
```

---

## 📋 已导出指标列表

### 业务指标

#### 1. 风险等级
```
etf.risk.level{strategy="stg3l"}
值: 1-3 (1=高风险, 2=中等, 3=正常)
更新频率: 每个交易循环
```

#### 2. 净值
```
etf.net_value{strategy="stg3l", leverage="3", direction="long"}
值: 浮点数
更新频率: 10秒（可配置）
```

#### 3. 净值变化率
```
etf.net_value.change_rate{strategy="stg3l", leverage="3", direction="long"}
值: -1 到 1 之间
更新频率: 10秒
```

#### 4. 止损触发次数
```
etf.stop_loss.triggered{strategy="stg3l", reason="fixed_threshold"}
类型: Counter（累计）
触发原因: fixed_threshold | trailing_stop | time_stop
```

#### 5. 持仓盈亏
```
etf.position.pnl{strategy="stg3l", symbol="stg3l_usdt"}
值: USDT
更新频率: 每个交易循环
```

### 系统指标

#### 6. API 调用耗时
```
etf.api.duration{endpoint="get_depth", status="success"}
类型: Histogram
单位: 毫秒
```

#### 7. API 错误次数
```
etf.api.errors{endpoint="get_depth"}
类型: Counter
```

#### 8. Redis 操作次数
```
etf.redis.operations{operation="set", strategy="stg3l"}
类型: Counter
```

---

## 🚀 快速开始

### 1. 本地开发环境

#### 启动 OTLP Collector（Docker）

```bash
# 创建配置文件 otel-collector-config.yaml
cat > otel-collector-config.yaml <<'EOF'
receivers:
  otlp:
    protocols:
      grpc:
        endpoint: 0.0.0.0:4317

exporters:
  prometheus:
    endpoint: "0.0.0.0:8889"
  logging:
    loglevel: debug

service:
  pipelines:
    metrics:
      receivers: [otlp]
      exporters: [prometheus, logging]
EOF

# 启动 OTLP Collector
docker run -d \
  --name otel-collector \
  -p 4317:4317 \
  -p 8889:8889 \
  -v $(pwd)/otel-collector-config.yaml:/etc/otel-collector-config.yaml \
  otel/opentelemetry-collector:latest \
  --config=/etc/otel-collector-config.yaml
```

#### 运行交易系统

```bash
# 启用 OpenTelemetry（默认启用）
export ENABLE_OTEL=true
export OTLP_ENDPOINT="http://localhost:4317"

# 运行策略
python run_etf.py --strategy stg3l
```

#### 查看指标

```bash
# 查看 Prometheus 格式指标
curl http://localhost:8889/metrics | grep etf_

# 示例输出:
# etf_risk_level{strategy="stg3l"} 3.0
# etf_net_value{strategy="stg3l",leverage="3",direction="long"} 1.025
# etf_stop_loss_triggered_total{strategy="stg3l",reason="fixed_threshold"} 0.0
```

---

### 2. 集成 Prometheus

#### Prometheus 配置（prometheus.yml）

```yaml
global:
  scrape_interval: 15s

scrape_configs:
  - job_name: 'etf-trading'
    static_configs:
      - targets: ['localhost:8889']  # OTLP Collector Prometheus 端点
```

#### 启动 Prometheus

```bash
docker run -d \
  --name prometheus \
  -p 9090:9090 \
  -v $(pwd)/prometheus.yml:/etc/prometheus/prometheus.yml \
  prom/prometheus
```

#### 查询示例

访问 http://localhost:9090/graph

```promql
# 风险等级时序图
etf_risk_level{strategy="stg3l"}

# 净值变化率（5分钟滚动）
rate(etf_net_value{strategy="stg3l"}[5m])

# 止损触发频率（每小时）
rate(etf_stop_loss_triggered_total{strategy="stg3l"}[1h])

# API 调用 P95 延迟
histogram_quantile(0.95, rate(etf_api_duration_bucket[5m]))
```

---

### 3. 集成 Grafana

#### 启动 Grafana

```bash
docker run -d \
  --name grafana \
  -p 3000:3000 \
  grafana/grafana
```

#### 配置数据源

1. 访问 http://localhost:3000（admin/admin）
2. Configuration → Data Sources → Add data source
3. 选择 Prometheus
4. URL: `http://prometheus:9090`
5. Save & Test

#### 导入仪表盘

创建新仪表盘，添加以下面板：

**风险等级监控**:
```promql
etf_risk_level{strategy=~"stg3l|stg3s|stg5l|stg5s"}
```

**净值对比**:
```promql
etf_net_value
```

**止损事件统计**:
```promql
increase(etf_stop_loss_triggered_total[1h])
```

---

## ⚙️ 配置说明

### 环境变量

| 变量 | 说明 | 默认值 |
|------|------|--------|
| `ENABLE_OTEL` | 启用/禁用 OpenTelemetry | `true` |
| `OTLP_ENDPOINT` | OTLP Collector 端点 | `http://localhost:4317` |

### 配置文件

参考 `config/observability.yaml`:

```yaml
opentelemetry:
  otlp_endpoint: "http://localhost:4317"
  metrics:
    enabled: true
    export_interval_seconds: 10
```

---

## 🔍 故障排查

### 问题 1: 指标未导出

**症状**: 查询 Prometheus 无数据

**检查清单**:
```bash
# 1. 检查 OTLP Collector 是否运行
docker ps | grep otel-collector

# 2. 检查端口是否监听
netstat -an | grep 4317

# 3. 查看 ETF 日志
# 应该看到: "✅ OpenTelemetry 初始化成功"

# 4. 查看 Collector 日志
docker logs otel-collector

# 5. 手动测试 OTLP 端点
curl http://localhost:8889/metrics
```

### 问题 2: "connection refused"

**原因**: OTLP Collector 未启动或端点配置错误

**解决**:
```bash
# 禁用 OpenTelemetry 继续运行
export ENABLE_OTEL=false
python run_etf.py --strategy stg3l
```

### 问题 3: 指标不更新

**检查**:
- 策略是否正常运行（查看主日志）
- 是否触发了条件（如止损未触发则计数为0）
- export_interval 配置（默认10秒）

---

## 📈 监控指标建议

### 关键指标告警

| 指标 | 阈值 | 告警级别 |
|------|------|----------|
| 风险等级 ≤ 1 | 持续 5 分钟 | Critical |
| 止损触发 > 5次/小时 | - | Warning |
| 净值跌幅 > 10% | - | Critical |
| API 错误率 > 10% | - | Warning |
| API P95 延迟 > 5秒 | - | Warning |

### Prometheus 告警规则示例

```yaml
groups:
  - name: etf_alerts
    rules:
      - alert: HighRiskLevel
        expr: etf_risk_level <= 1
        for: 5m
        labels:
          severity: critical
        annotations:
          summary: "策略 {{ $labels.strategy }} 风险等级过高"

      - alert: FrequentStopLoss
        expr: rate(etf_stop_loss_triggered_total[1h]) > 5
        labels:
          severity: warning
        annotations:
          summary: "策略 {{ $labels.strategy }} 止损触发频繁"
```

---

## 🔄 后续扩展

### 计划中的功能

1. **Traces（分布式追踪）**
   - 追踪完整的订单生命周期
   - 识别性能瓶颈

2. **结构化日志**
   - JSON 格式日志
   - 与 Traces 关联

3. **自定义 Exporter**
   - 直接导出到 Grafana Cloud
   - 导出到 Datadog

4. **自动 Instrumentation**
   - Redis 操作自动监控
   - HTTP 请求自动追踪

---

## 📚 参考资源

- [OpenTelemetry 官方文档](https://opentelemetry.io/docs/)
- [Prometheus 查询语法](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana 仪表盘指南](https://grafana.com/docs/grafana/latest/dashboards/)
- [OTLP 协议规范](https://opentelemetry.io/docs/specs/otlp/)

---

**文档维护者**: ETF Trading Team
**反馈**: 如有问题请提交 Issue
