# 净值推送环境变量配置更新

**更新日期**: 2025-01-20  
**影响范围**: 净值计算器 (`run_net_value.py`)  
**问题**: 配置文件显示推送启用，但运行时显示"交易所推送: 禁用"

---

## 问题分析

### 原始问题

用户启动 TON3L 策略净值计算器时，虽然 `config/strategies.yaml` 中配置了：

```yaml
net_value_push:
  enabled: true
```

但日志显示：
```
交易所推送: 禁用
```

### 根本原因

1. **缺少 API 密钥文件**: `APIKey.json` 不存在
2. **未从 .env 加载**: `run_net_value.py` 没有读取环境变量的代码
3. **初始化失败静默**: 推送参数未添加，使用了默认值 `enable_push_to_exchange=False`

---

## 解决方案

### 代码改进 (run_net_value.py)

**改进点 1**: 添加 `.env` 支持（优先级最高）

```python
# 方式1: 从 .env 文件加载（推荐）
from dotenv import load_dotenv
load_dotenv()

access_key_env = os.getenv("access_key")
secret_key_env = os.getenv("secret_key")

if access_key_env and secret_key_env:
    api_key = {
        "access_key": access_key_env,
        "secret_key": secret_key_env
    }
    logging.info("✅ 从 .env 文件加载API密钥")
```

**改进点 2**: 降级到 APIKey.json（如果 .env 不可用）

```python
else:
    # 方式2: 从 APIKey.json 加载（降级方案）
    api_key_file = strategy_config.get("apikey", "APIKey.json")
    api_key_path = os.path.join(os.path.dirname(__file__), api_key_file)
    
    if os.path.exists(api_key_path):
        with open(api_key_path, "r") as f:
            api_keys = json.load(f)
        # 查找策略对应的密钥...
```

**改进点 3**: 更清晰的错误提示

```python
if not api_key:
    logging.warning("⚠️  净值推送配置已启用，但未找到有效的API密钥，推送将被禁用")
    logging.warning("请确保以下任一方式配置API密钥:")
    logging.warning("  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx")
    logging.warning("  2. 在 APIKey.json 文件中配置相应的密钥")
```

---

## 配置方式对比

### 新增: .env 方式（推荐）

**优势**:
- ✅ 不会误提交到Git（`.gitignore` 已配置）
- ✅ 统一管理所有环境变量
- ✅ 支持 QA/生产环境切换（`.env.qa`, `.env.prod`）
- ✅ 与 `run_etf.py` 配置方式一致

**配置步骤**:
```bash
# 1. 创建 .env 文件
cat > .env << 'EOF'
access_key=your_real_access_key
secret_key=your_real_secret_key
EOF

# 2. 运行净值计算器
python run_net_value.py --strategy ton3l --env qa

# 3. 验证日志输出
# ✅ 从 .env 文件加载API密钥
# ✅ 净值推送已启用 - 主机: https://sapi.xt-qa2.com, 推送间隔: 60秒
# 净值计算器初始化完成: ton_usdt, 杠杆: 3x, 方向: 做多, 数据库持久化: 启用, 交易所推送: 启用
```

### 保留: APIKey.json 方式（降级）

**何时使用**:
- 无法访问 `.env` 文件（如只读文件系统）
- 需要多策略独立密钥（`xt_ton3l`, `xt_stg3l` 等）

**配置格式**:
```json
{
  "xt_ton3l": {
    "access_key": "qa_key",
    "secret_key": "qa_secret"
  },
  "xt_stg3l": {
    "access_key": "prod_key",
    "secret_key": "prod_secret"
  }
}
```

---

## 配置优先级

系统按以下顺序尝试加载API密钥（从高到低）：

1. **环境变量 (.env 文件)** - 最高优先级
   ```bash
   access_key=from_env_file
   secret_key=from_env_file
   ```

2. **APIKey.json 多策略格式**
   ```json
   {
     "xt_ton3l": {
       "access_key": "xxx",
       "secret_key": "xxx"
     }
   }
   ```

3. **APIKey.json 单策略格式** - 最低优先级
   ```json
   {
     "access_key": "xxx",
     "secret_key": "xxx"
   }
   ```

---

## 使用示例

### 场景 1: QA 环境测试（使用 .env）

```bash
# 1. 创建 QA 环境配置
cat > .env << 'EOF'
access_key=qa_access_key_here
secret_key=qa_secret_key_here
LOG_LEVEL=DEBUG
EOF

# 2. 启动 TON3L 净值计算器
python run_net_value.py --strategy ton3l --env qa

# 3. 预期日志
# ✅ 从 .env 文件加载API密钥
# ✅ 净值推送已启用 - 主机: https://sapi.xt-qa2.com, 推送间隔: 60秒
# 净值计算器开始运行: ton_usdt
```

### 场景 2: 生产环境部署（使用 .env）

```bash
# 1. 创建生产环境配置
cat > .env << 'EOF'
access_key=prod_access_key_here
secret_key=prod_secret_key_here
LOG_LEVEL=INFO
ENABLE_OTEL=true
ENABLE_WEBSOCKET=true
EOF

# 2. 启动多个策略
python run_net_value.py --strategy ton3l --env prod
python run_net_value.py --strategy stg3l --env prod
python run_net_value.py --strategy stg5l --env prod

# 3. 使用 PM2 管理（可选）
pm2 start ecosystem.config.js
```

### 场景 3: 多环境切换（使用符号链接）

```bash
# 1. 创建多个环境配置文件
cat > .env.qa << 'EOF'
access_key=qa_key
secret_key=qa_secret
EOF

cat > .env.prod << 'EOF'
access_key=prod_key
secret_key=prod_secret
EOF

# 2. 切换到 QA 环境
ln -sf .env.qa .env
python run_net_value.py --strategy ton3l --env qa

# 3. 切换到生产环境
ln -sf .env.prod .env
python run_net_value.py --strategy ton3l --env prod
```

---

## 验证方法

### 方法 1: 查看启动日志

```bash
python run_net_value.py --strategy ton3l --env qa 2>&1 | grep -E "(API密钥|推送)"

# 成功输出示例:
# ✅ 从 .env 文件加载API密钥
# ✅ 净值推送已启用 - 主机: https://sapi.xt-qa2.com, 推送间隔: 60秒
# 交易所推送: 启用
```

### 方法 2: 测试 .env 文件

```bash
# 测试环境变量是否正确加载
python -c "
from dotenv import load_dotenv
import os
load_dotenv()
print('access_key:', os.getenv('access_key'))
print('secret_key:', 'OK' if os.getenv('secret_key') else 'NOT FOUND')
"

# 预期输出:
# access_key: your_access_key
# secret_key: OK
```

### 方法 3: 检查推送功能

```bash
# 查看 Redis 中的净值数据（推送前提）
redis-cli GET netvalue_ton3l

# 查看推送日志
tail -f logs/ton3l/ton3l.log | grep -E "(推送|push)"

# 预期输出（每60秒一次）:
# 正在推送净值到交易所: TON3L_USDT = 1.023456
# ✅ 净值推送成功: TON3L_USDT = 1.023456
```

---

## 故障排除

### 问题 1: 仍然显示"交易所推送: 禁用"

**原因**: 
- `.env` 文件不存在或未正确配置
- `access_key` 或 `secret_key` 为空

**解决**:
```bash
# 检查 .env 文件是否存在
ls -la .env

# 验证内容
cat .env | grep -E "access_key|secret_key"

# 如果不存在，创建它
cat > .env << 'EOF'
access_key=your_real_key
secret_key=your_real_secret
EOF
```

### 问题 2: 推送失败（401 Unauthorized）

**原因**: API 密钥无效或无推送权限

**解决**:
```bash
# 1. 验证密钥是否正确
# 2. 检查交易所后台，确保密钥有"更新ETF净值"权限
# 3. 重新生成 API 密钥（如果需要）
```

### 问题 3: 推送间隔不生效

**原因**: `config/strategies.yaml` 中 `interval` 配置错误

**解决**:
```yaml
net_value_push:
  enabled: true
  interval: 60  # 确保这个值正确（秒）
```

---

## 相关文档

- [环境变量完整配置指南](ENV_CONFIGURATION.md)
- [净值推送配置说明](NET_VALUE_PUSH_CONFIG_SUMMARY.md)
- [项目开发路线图](DEVELOPMENT_ROADMAP.md)

---

## 更新日志

- **2025-01-20**: 添加 `.env` 支持，优先级高于 `APIKey.json`
- **2025-01-20**: 改进错误提示，提供多种配置方式说明
- **2025-01-20**: 创建完整的环境变量配置文档
