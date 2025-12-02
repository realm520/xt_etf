# API 密钥安全管理指南

## 🔒 概述

本文档说明如何安全地管理 XT ETF 交易系统的 API 密钥，确保生产环境的密钥安全。

> **⚡ 推荐方式**: 使用 `.env` 文件管理 API 密钥（详见 [ENV_CONFIGURATION.md](ENV_CONFIGURATION.md)）
>
> ```bash
> # .env 文件示例
> access_key=your_access_key_here
> secret_key=your_secret_key_here
> ```
>
> 以下加密文件方式为**高级安全选项**，适用于需要额外保护的场景。

## ⚠️ 重要警告

**绝对禁止**:
- ❌ 将明文 API 密钥提交到 Git 仓库
- ❌ 在生产环境使用明文密钥文件
- ❌ 在代码中硬编码 API 密钥
- ❌ 通过不安全的渠道传输密钥

**强制要求**:
- ✅ 优先使用 `.env` 文件（已在 .gitignore 中）
- ✅ 高安全场景使用加密的 .enc 文件
- ✅ 加密密码必须通过环境变量管理
- ✅ 定期轮换 API 密钥

---

## 📋 密钥文件类型

### 1. 明文密钥文件 (APIKey*.json)
```json
{
  "xt_stg3l": {
    "access_key": "your-access-key",
    "secret_key": "your-secret-key"
  }
}
```
- ⚠️ **仅用于开发/测试环境**
- ❌ **禁止在生产环境使用**
- ✅ 已在 .gitignore 中配置

### 2. 加密密钥文件 (APIKey*.enc)
```json
{
  "version": "1.0",
  "algorithm": "AES-256-GCM",
  "salt": "base64-encoded-salt",
  "nonce": "base64-encoded-nonce",
  "tag": "base64-encoded-tag",
  "ciphertext": "base64-encoded-ciphertext"
}
```
- ✅ **生产环境唯一允许的格式**
- ✅ 使用 AES-256-GCM 加密算法
- ✅ 已在 .gitignore 中配置

---

## 🚀 快速开始

### 方法 1: 使用加密脚本（推荐）

```bash
# 1. 设置加密密码（使用强密码！）
export ETF_KEY_PASSWORD='your-very-secure-password-min-16-chars'

# 2. 运行加密脚本
python scripts/encrypt_apikeys.py

# 按提示操作：
# - 输入要加密的文件（默认 APIKey.json）
# - 确认输出文件（默认 APIKey.enc）
# - 选择是否删除明文文件（推荐删除）
```

### 方法 2: 使用 Python 命令

```bash
# 1. 设置密码
export ETF_KEY_PASSWORD='your-secure-password'

# 2. 加密指定文件
python -c "from etf.utils.crypto import encrypt_api_keys; encrypt_api_keys('APIKey.json', 'APIKey.enc')"

# 3. 删除明文文件（可选但推荐）
rm APIKey.json
```

### 方法 3: 交互式加密（无环境变量）

```bash
python scripts/encrypt_apikeys.py
# 系统会提示输入密码（密码不会显示）
```

---

## 🔐 生产环境部署

### 步骤 1: 准备加密密钥文件

```bash
# 开发环境操作
export ETF_KEY_PASSWORD='production-password-min-16-chars'
python scripts/encrypt_apikeys.py

# 验证加密文件存在
ls -la *.enc
# 应该看到: APIKey.enc
```

### 步骤 2: 配置生产服务器

```bash
# 在生产服务器上设置环境变量（永久）
echo 'export ETF_KEY_PASSWORD="production-password"' >> ~/.bashrc
source ~/.bashrc

# 或者使用 systemd service 配置
# 在 /etc/systemd/system/etf.service 中添加:
# Environment="ETF_KEY_PASSWORD=production-password"
```

### 步骤 3: 部署加密文件

```bash
# 将 .enc 文件安全传输到生产服务器
# 使用 SCP（确保使用 SSH 密钥认证）
scp APIKey.enc user@production-server:/path/to/xt_etf/

# 或通过安全的密钥管理服务部署
```

### 步骤 4: 验证部署

```bash
# 测试密钥加载
python -c "from etf.utils.crypto import load_api_keys; print('Success:', load_api_keys('APIKey.json'))"

# 如果成功，应该看到加密文件被正确解密
```

---

## 🛡️ 安全机制

### 自动安全检查

系统会在启动时自动检查：

1. **生产环境检测**
   ```python
   if config["env"] == "prod":
       # 检查是否存在加密文件
       # 如果只有明文文件，程序将拒绝启动
   ```

2. **警告信息**
   ```
   🚨 安全警告: 生产环境检测到明文 API 密钥!
   请立即执行以下步骤加密您的 API 密钥:
   1. 设置加密密码: export ETF_KEY_PASSWORD='your-secure-password'
   2. 运行加密脚本: python scripts/encrypt_apikeys.py
   程序将在 10 秒后退出...
   ```

3. **强制退出**
   - 生产环境如检测到明文密钥，程序将在 10 秒后自动退出
   - 除非设置 `ALLOW_PLAIN_KEYS=true`（仅用于测试）

### 开发/测试环境例外

如果确实需要在开发环境使用明文密钥：

```bash
# 仅用于开发/测试！
export ALLOW_PLAIN_KEYS=true
python run_etf.py --strategy stg3l --env prod
```

⚠️ **警告**: 此选项仅用于开发/测试，绝不应在真实生产环境使用！

---

## 🔑 密码管理最佳实践

### 密码强度要求

- ✅ 至少 16 个字符
- ✅ 包含大小写字母、数字、特殊字符
- ✅ 避免使用常见单词或个人信息
- ✅ 使用密码管理器生成随机密码

### 密码存储

**推荐方式（优先级从高到低）**:

1. **密钥管理服务** (AWS Secrets Manager, HashiCorp Vault)
   ```bash
   # 从 AWS Secrets Manager 获取
   export ETF_KEY_PASSWORD=$(aws secretsmanager get-secret-value --secret-id etf/key-password --query SecretString --output text)
   ```

2. **环境变量** (systemd, .bashrc)
   ```bash
   # ~/.bashrc 或 ~/.zshrc
   export ETF_KEY_PASSWORD='your-secure-password'
   ```

3. **交互式输入** (手动启动场景)
   ```bash
   # 脚本会提示输入密码
   python scripts/encrypt_apikeys.py
   ```

**禁止的方式**:
- ❌ 硬编码在代码中
- ❌ 存储在配置文件中
- ❌ 提交到 Git 仓库
- ❌ 通过明文聊天工具传输

---

## 📁 文件组织

### 目录结构

```
xt_etf/
├── APIKey.json          # 明文密钥（开发环境，不提交）
├── APIKey.enc           # 加密密钥（生产环境，不提交）
├── APIKey_stg3l.json    # 策略专用明文密钥（不提交）
├── APIKey_stg3l.enc     # 策略专用加密密钥（不提交）
├── .gitignore           # 确保包含 APIKey* 规则
├── scripts/
│   └── encrypt_apikeys.py  # 加密工具
└── etf/
    └── utils/
        └── crypto.py    # 加密/解密实现
```

### .gitignore 配置

确保以下规则存在：

```gitignore
# 敏感信息和配置文件
APIKey*.json
APIKey*.enc
*.key
*.pem
.env
.env.*
```

---

## 🔄 密钥轮换

建议定期轮换 API 密钥（如每 90 天）：

### 轮换步骤

1. **在交易所生成新密钥**
   ```bash
   # 登录 XT 交易所
   # 创建新的 API 密钥
   # 保存 access_key 和 secret_key
   ```

2. **更新密钥文件**
   ```bash
   # 编辑 APIKey.json
   vim APIKey.json
   # 更新对应策略的密钥
   ```

3. **重新加密**
   ```bash
   export ETF_KEY_PASSWORD='your-password'
   python scripts/encrypt_apikeys.py
   ```

4. **部署新密钥**
   ```bash
   scp APIKey.enc user@production:/path/to/xt_etf/
   ```

5. **重启服务**
   ```bash
   pm2 restart etf-stg3l
   ```

6. **撤销旧密钥**
   ```bash
   # 在交易所删除旧的 API 密钥
   ```

---

## 🚨 安全事件响应

### 密钥泄露处理

如果怀疑密钥泄露：

1. **立即撤销**
   - 登录交易所立即删除受影响的 API 密钥

2. **生成新密钥**
   - 创建新的 API 密钥对

3. **更新系统**
   - 按照密钥轮换步骤更新所有系统

4. **审计日志**
   - 检查交易记录是否有异常活动

5. **报告**
   - 记录事件并改进安全措施

### 检查清单

定期检查：

- [ ] 所有生产环境使用 .enc 文件
- [ ] 没有明文密钥文件在生产服务器
- [ ] ETF_KEY_PASSWORD 正确配置
- [ ] .gitignore 规则正确
- [ ] 密钥文件权限正确 (chmod 600)
- [ ] 最近 90 天内轮换过密钥

---

## 📚 相关文档

- [部署指南](DEPLOYMENT_GUIDE.md)
- [安全最佳实践](SECURITY_BEST_PRACTICES.md)
- [环境配置](ENVIRONMENT_SETUP.md)

## ❓ 常见问题

### Q: 忘记加密密码怎么办？
A: 无法恢复。需要使用原始 API 密钥重新生成加密文件。建议使用密码管理器。

### Q: 可以在多个服务器共享同一个 .enc 文件吗？
A: 可以，只要密码相同。但建议为不同环境使用不同的 API 密钥。

### Q: 开发环境必须使用加密吗？
A: 不强制，但强烈推荐。可以设置 `ALLOW_PLAIN_KEYS=true` 在开发环境使用明文。

### Q: 如何验证 .enc 文件是否正确？
A: 运行测试加载命令：
```bash
python -c "from etf.utils.crypto import load_api_keys; print(load_api_keys('APIKey.json'))"
```

---

**文档版本**: 1.0
**最后更新**: 2025-01-16
**维护者**: ETF Trading Team
