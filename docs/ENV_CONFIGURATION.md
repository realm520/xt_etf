# 环境变量配置指南

本文档说明如何使用 `.env` 文件配置系统环境变量。

## 快速开始

1. **创建 `.env` 文件**（项目根目录）

```bash
# 复制示例配置
cat > .env << 'EOF'
# XT Exchange API Keys
access_key=your_access_key_here
secret_key=your_secret_key_here
EOF
```

2. **配置必需的API密钥**

编辑 `.env` 文件，填入你的真实API密钥：
- `access_key`: XT交易所的Access Key
- `secret_key`: XT交易所的Secret Key

3. **验证配置**

```bash
# 运行净值计算器测试
python run_net_value.py --strategy ton3l --env qa
```

---

## 完整配置选项

### 1. API密钥配置（必需）

```bash
# XT Exchange API Keys
# 用于交易和净值推送
access_key=your_access_key_here
secret_key=your_secret_key_here
```

**注意**: 
- `.env` 文件是**唯一推荐**的 API 密钥配置方式（`APIKey.json` 已废弃）
- `.env` 文件已在 `.gitignore` 中，不会被提交到版本控制
- 详细安全指南请参考 [API_KEY_SECURITY.md](API_KEY_SECURITY.md)

### 2. PostgreSQL数据库配置（可选）

用于订单记录和净值持久化存储。

```bash
POSTGRES_USER=postgres
POSTGRES_PASSWORD=your_password
POSTGRES_HOST=localhost
POSTGRES_PORT=5432
POSTGRES_DB=xt_etf
```

**启用方式**: 在 `config/strategies.yaml` 中设置
```yaml
database:
  net_value_persistence:
    enabled: true
```

### 3. OpenTelemetry可观测性配置（可选）

用于指标收集、性能监控和分布式追踪。

```bash
# 启用/禁用 OpenTelemetry
ENABLE_OTEL=true

# OTLP Collector 端点
OTLP_ENDPOINT=http://localhost:4317
```

**支持的指标**:
- 净值变化率
- 风险等级
- 订单执行性能
- API调用延迟

### 4. WebSocket实时数据配置（可选）

用于实时获取市场深度数据，降低REST API调用频率。

```bash
# 启用/禁用 WebSocket
ENABLE_WEBSOCKET=true
```

**优势**:
- 降低API限流风险
- 提高数据实时性（延迟 < 100ms）
- 减少REST API调用成本

### 5. 日志配置（可选）

```bash
# 日志级别: DEBUG, INFO, WARNING, ERROR, CRITICAL
LOG_LEVEL=INFO
```

**日志级别说明**:
- `DEBUG`: 详细调试信息（开发模式）
- `INFO`: 正常运行信息（生产推荐）
- `WARNING`: 警告信息
- `ERROR`: 错误信息
- `CRITICAL`: 严重错误

### 6. 安全配置（生产环境）

```bash
# 允许使用明文API密钥（仅用于开发/测试）
# 生产环境应设置为 false 或删除此行
ALLOW_PLAIN_KEYS=false
```

**生产环境建议**:
1. 使用加密的 `APIKey.enc` 文件
2. 设置环境变量 `ETF_KEY_PASSWORD`
3. 禁用 `ALLOW_PLAIN_KEYS`

---

## 配置示例

### 开发环境 (QA)

```bash
# .env (QA环境)
access_key=qa_access_key_here
secret_key=qa_secret_key_here

# 开启详细日志
LOG_LEVEL=DEBUG

# 禁用可选功能（减少依赖）
ENABLE_OTEL=false
ENABLE_WEBSOCKET=true
```

运行命令:
```bash
python run_net_value.py --strategy ton3l --env qa
```

### 生产环境 (PROD)

```bash
# .env (生产环境)
access_key=prod_access_key_here
secret_key=prod_secret_key_here

# 正常日志级别
LOG_LEVEL=INFO

# 启用所有功能
ENABLE_OTEL=true
OTLP_ENDPOINT=http://otel-collector:4317
ENABLE_WEBSOCKET=true

# 数据库持久化
POSTGRES_HOST=db.example.com
POSTGRES_PASSWORD=strong_password_here
POSTGRES_DB=xt_etf_prod

# 安全配置
ALLOW_PLAIN_KEYS=false
```

运行命令:
```bash
python run_net_value.py --strategy ton3l --env prod
```

---

## 配置优先级

系统按以下优先级加载配置（从高到低）：

1. **命令行参数** - 最高优先级
   ```bash
   python run_net_value.py --strategy ton3l --init-net-value 1.0
   ```

2. **策略配置文件 (config/strategies.yaml)** - 可选覆盖
   ```yaml
   ton3l:
     # 如需特定策略使用不同的密钥，可在此处指定
     # 但推荐统一使用 .env 文件管理
   ```

---

## 常见问题

### Q1: 为什么推送被禁用？

**症状**: 日志显示"交易所推送: 禁用"

**原因**: 
1. `.env` 文件不存在
2. API密钥未正确配置
3. `config/strategies.yaml` 中 `net_value_push.enabled: false`

**解决方案**:
```bash
# 1. 创建 .env 文件
cat > .env << 'EOF'
access_key=your_real_key
secret_key=your_real_secret
EOF

# 2. 检查配置文件
grep -A 5 "net_value_push:" config/strategies.yaml

# 3. 重启程序
python run_net_value.py --strategy ton3l --env qa
```

### Q2: 如何验证 .env 是否生效？

```bash
# 方法1: 查看启动日志
python run_net_value.py --strategy ton3l --env qa 2>&1 | grep "API密钥"

# 期望输出:
# ✅ 从 .env 文件加载API密钥

# 方法2: 使用 dotenv 测试
python -c "from dotenv import load_dotenv; import os; load_dotenv(); print(os.getenv('access_key'))"
```

### Q3: .env 文件会被提交到Git吗？

**不会**。`.env` 文件已在 `.gitignore` 中被忽略：

```bash
# 查看 .gitignore
grep "\.env" .gitignore

# 输出:
# .env
# .env.*
```

### Q4: 如何在多个环境间切换？

创建多个环境配置文件：

```bash
# QA环境
.env.qa

# 生产环境
.env.prod

# 本地开发
.env.local
```

使用时通过符号链接切换：
```bash
# 切换到QA环境
ln -sf .env.qa .env

# 切换到生产环境
ln -sf .env.prod .env
```

---

## 安全建议

1. **永远不要提交 `.env` 文件到Git**
   - 已在 `.gitignore` 中配置
   - 使用 `git status` 验证

2. **使用加密存储（生产环境）**
   ```bash
   # 加密API密钥
   export ETF_KEY_PASSWORD='strong_password'
   python scripts/encrypt_apikeys.py
   ```

3. **定期轮换密钥**
   - 建议每90天更换一次API密钥
   - 记录密钥轮换日期

4. **最小权限原则**
   - 只授予必要的API权限
   - 交易权限与查询权限分离

5. **监控异常访问**
   - 启用 OpenTelemetry 监控
   - 设置告警规则

---

## 相关文档

- [净值推送配置指南](NET_VALUE_PUSH_GUIDE.md)
- [项目开发路线图](DEVELOPMENT_ROADMAP.md)
- [API密钥加密工具](../scripts/encrypt_apikeys.py)

---

## 更新日志

- **2025-01-20**: 初始版本，添加完整的环境变量配置说明
- **2025-01-20**: 添加净值推送的 `.env` 支持
