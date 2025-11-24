# Prometheus Metrics 指南

本文档说明如何使用 Prometheus Pull 模式收集和监控 ETF 交易系统的指标。

## 📊 架构变更

### 旧架构（Push 模式）
```
ETF System → OpenTelemetry SDK → OTLP Collector → Prometheus
            (主动推送)          (需要额外组件)
```

### 新架构（Pull 模式，推荐）
```
ETF System ← Prometheus
(HTTP /metrics)  (主动拉取)
```

**优势**：
- ✅ 简单可靠：无需 OTLP Collector
- ✅ 标准化：Prometheus 业界标准
- ✅ 易于调试：直接访问 HTTP 端点
- ✅ 去中心化：系统自主暴露指标

---

## 🚀 快速开始

### 1. 环境变量配置

在 `.env` 文件中添加以下配置：

```bash
# Metrics 配置
ENABLE_METRICS=true                    # 启用 Metrics（默认: true）
METRICS_EXPORT_MODE=prometheus         # 导出模式（prometheus | otlp，默认: prometheus）
PROMETHEUS_PORT=8000                   # Prometheus HTTP 端口（默认: 8000）

# 如果使用多个策略，需要为每个策略分配不同端口
# stg3l: 8000
# stg3s: 8001
# stg5l: 8002
# stg5s: 8003
```

### 2. 启动系统

```bash
# 单策略启动
python run_etf.py --strategy stg3l

# 查看日志确认 Prometheus 端点
# 应该看到类似输出:
# ✅ Prometheus 初始化成功
#    Metrics 端点: http://0.0.0.0:8000/metrics
```

### 3. 验证 Metrics 端点

```bash
# 访问 metrics 端点
curl http://localhost:8000/metrics

# 应该看到类似输出:
# # HELP etf_risk_level Current risk level (1=high risk, 2=medium, 3=normal)
# # TYPE etf_risk_level gauge
# etf_risk_level{strategy="stg3l"} 3.0
# ...
```

### 4. 配置 Prometheus 抓取

编辑 Prometheus 配置文件（`prometheus.yml`）：

```yaml
scrape_configs:
  # ETF Trading System
  - job_name: 'etf-trading'
    scrape_interval: 15s  # 每15秒抓取一次
    static_configs:
      - targets:
          - 'localhost:8000'  # stg3l
          - 'localhost:8001'  # stg3s
          - 'localhost:8002'  # stg5l
          - 'localhost:8003'  # stg5s
        labels:
          environment: 'production'
          service: 'etf-trading'
```

重启 Prometheus：
```bash
# Docker
docker-compose restart prometheus

# 或直接运行
./prometheus --config.file=prometheus.yml
```

---

## 📈 可用指标

### 风险相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_risk_level` | Gauge | 风险等级（1=高风险，2=中等，3=正常） | `strategy` |
| `etf_risk_volatility_level` | Gauge | 波动率风险等级（1-3） | `strategy` |
| `etf_risk_mid_price_level` | Gauge | 中间价偏离等级（1-3） | `strategy` |
| `etf_risk_market_price_level` | Gauge | 市场价偏离等级（1-3） | `strategy` |
| `etf_risk_orderbook_level` | Gauge | 订单簿深度等级（1-3） | `strategy` |

### 净值相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_net_value` | Gauge | ETF 净值 | `strategy`, `leverage`, `direction` |
| `etf_net_value_change_rate` | Gauge | 净值变化率 | `strategy`, `leverage`, `direction` |

### 止损相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_stop_loss_triggered_total` | Counter | 止损触发次数 | `strategy`, `reason` |

### 持仓相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_position_amount` | Gauge | 持仓数量 | `strategy`, `symbol` |
| `etf_position_pnl_usdt` | Gauge | 持仓盈亏（USDT） | `strategy`, `symbol` |
| `etf_account_balance_usdt` | Gauge | 账户余额（USDT） | `strategy`, `asset` |

### API 相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_api_duration_seconds` | Histogram | API 调用耗时（秒） | `strategy`, `endpoint`, `status` |
| `etf_api_errors_total` | Counter | API 错误总数 | `strategy`, `endpoint` |
| `etf_api_success_rate` | Gauge | API 成功率（0-1） | `strategy` |

### 订单相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_orders_total` | Counter | 订单总数 | `strategy`, `type` |
| `etf_orders_success_total` | Counter | 成功订单数 | `strategy`, `type` |
| `etf_orders_failed_total` | Counter | 失败订单数 | `strategy`, `type` |

### Redis 相关指标

| 指标名称 | 类型 | 说明 | 标签 |
|---------|------|------|------|
| `etf_redis_operations_total` | Counter | Redis 操作总数 | `strategy`, `operation` |

---

## 📊 Grafana 仪表板

### 导入预设仪表板

1. 登录 Grafana
2. 导航到 **Dashboards → Import**
3. 上传 `dashboards/etf_trading_dashboard.json`

### 关键面板

1. **风险监控**
   - 实时风险等级（Gauge）
   - 风险子指标趋势（时间序列）

2. **净值监控**
   - 所有策略净值对比
   - 净值变化率

3. **止损告警**
   - 止损触发频率
   - 止损原因分布

4. **系统健康**
   - API 成功率
   - API 延迟分布
   - 订单成功率

---

## 🔧 常见问题

### Q1: 如何切换回 OTLP 模式？

```bash
# .env 文件
METRICS_EXPORT_MODE=otlp
OTLP_ENDPOINT=http://localhost:4317
```

**不推荐**，建议使用 Prometheus Pull 模式。

### Q2: 端口冲突怎么办？

每个策略需要不同端口：

```bash
# stg3l
PROMETHEUS_PORT=8000

# stg3s
PROMETHEUS_PORT=8001

# 以此类推...
```

或使用环境变量覆盖：
```bash
PROMETHEUS_PORT=8001 python run_etf.py --strategy stg3s
```

### Q3: 如何禁用 Metrics？

```bash
# .env 文件
ENABLE_METRICS=false
```

### Q4: 如何查看所有可用指标？

```bash
curl http://localhost:8000/metrics | grep "# HELP"
```

### Q5: Prometheus 抓取失败？

检查：
1. 端口是否正确开放
2. 防火墙规则
3. Prometheus 配置文件中的 `targets`
4. 系统日志中的错误信息

---

## 🎯 PromQL 查询示例

### 实时风险监控

```promql
# 所有策略的当前风险等级
etf_risk_level

# 高风险策略（risk_level = 1）
etf_risk_level{strategy=~".*"} == 1

# 风险等级变化率
rate(etf_risk_level[5m])
```

### 净值分析

```promql
# 所有策略净值
etf_net_value

# 3x 杠杆策略净值
etf_net_value{leverage="3"}

# 净值增长率（过去1小时）
(etf_net_value - etf_net_value offset 1h) / etf_net_value offset 1h
```

### 止损告警

```promql
# 止损触发频率（每小时）
rate(etf_stop_loss_triggered_total[1h]) * 3600

# 按原因分组的止损次数
sum by (reason) (etf_stop_loss_triggered_total)
```

### API 性能

```promql
# API 平均延迟（过去5分钟）
rate(etf_api_duration_seconds_sum[5m]) / rate(etf_api_duration_seconds_count[5m])

# API 成功率（过去15分钟）
sum(rate(etf_orders_success_total[15m])) / sum(rate(etf_orders_total[15m]))

# API P99 延迟
histogram_quantile(0.99, rate(etf_api_duration_seconds_bucket[5m]))
```

---

## 🚨 告警规则示例

在 Prometheus 配置中添加告警规则（`alerts.yml`）：

```yaml
groups:
  - name: etf_trading_alerts
    interval: 30s
    rules:
      # 高风险告警
      - alert: HighRiskLevel
        expr: etf_risk_level == 1
        for: 2m
        labels:
          severity: critical
        annotations:
          summary: "策略 {{ $labels.strategy }} 进入高风险状态"
          description: "风险等级为 1，请立即检查"

      # 止损频繁触发
      - alert: FrequentStopLoss
        expr: rate(etf_stop_loss_triggered_total[1h]) > 0.1
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "策略 {{ $labels.strategy }} 止损频繁触发"
          description: "过去1小时触发 {{ $value }} 次止损"

      # API 成功率过低
      - alert: LowAPISuccessRate
        expr: etf_api_success_rate < 0.9
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "API 成功率过低"
          description: "策略 {{ $labels.strategy }} API 成功率 {{ $value }}"

      # 订单失败率过高
      - alert: HighOrderFailureRate
        expr: |
          sum(rate(etf_orders_failed_total[5m])) by (strategy) /
          sum(rate(etf_orders_total[5m])) by (strategy) > 0.1
        for: 3m
        labels:
          severity: warning
        annotations:
          summary: "订单失败率过高"
          description: "策略 {{ $labels.strategy }} 订单失败率 {{ $value | humanizePercentage }}"
```

---

## 📚 参考资源

- [Prometheus 官方文档](https://prometheus.io/docs/)
- [PromQL 查询语法](https://prometheus.io/docs/prometheus/latest/querying/basics/)
- [Grafana 仪表板配置](https://grafana.com/docs/grafana/latest/dashboards/)
- [prometheus_client Python 库文档](https://github.com/prometheus/client_python)

---

## 🔄 迁移指南（从 OTLP 到 Prometheus）

### 1. 停止现有服务

```bash
# 停止所有 ETF 策略
pm2 stop all
```

### 2. 更新环境变量

```bash
# .env
METRICS_EXPORT_MODE=prometheus  # 改为 prometheus
PROMETHEUS_PORT=8000            # 新增端口配置
```

### 3. 重启服务

```bash
# 启动策略
pm2 start ecosystem.config.js
pm2 logs  # 查看日志确认
```

### 4. 配置 Prometheus

参考上文"配置 Prometheus 抓取"部分。

### 5. 验证数据

```bash
# 检查 metrics 端点
curl http://localhost:8000/metrics

# 检查 Prometheus Target 状态
# 访问 http://localhost:9090/targets
```

---

**最后更新**: 2025-01-22
**作者**: ETF Trading Team
