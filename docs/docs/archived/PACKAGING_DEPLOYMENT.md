# XT ETF 打包与部署指南

**文档版本**: v1.0
**更新日期**: 2025-10-29
**适用环境**: Ubuntu 20.04+, CentOS 8+, Debian 11+

---

## 📋 目录

1. [快速开始](#快速开始)
2. [打包流程](#打包流程)
3. [部署流程](#部署流程)
4. [回滚操作](#回滚操作)
5. [环境要求](#环境要求)
6. [配置说明](#配置说明)
7. [安全最佳实践](#安全最佳实践)
8. [故障排查](#故障排查)

---

## 🚀 快速开始

### 一键打包部署

```bash
# 1. 开发机器：打包
./scripts/package.sh 1.0.0

# 2. 部署到生产服务器
./scripts/deploy.sh production-server trader

# 3. 验证部署
ssh trader@production-server "pm2 status"
```

### 回滚到之前版本

```bash
# 在目标服务器上执行
cd /opt/xt-etf/app
./scripts/rollback.sh

# 或远程执行
ssh trader@production-server "/opt/xt-etf/app/scripts/rollback.sh"
```

---

## 📦 打包流程

### 打包脚本使用

```bash
./scripts/package.sh [VERSION] [OPTIONS]

# 示例
./scripts/package.sh 1.0.0                    # 打包v1.0.0
./scripts/package.sh 1.0.0 --include-tests    # 包含测试文件
./scripts/package.sh                          # 使用默认版本
```

### 打包输出

```
build/
├── xt-etf-1.0.0.tar.gz           # 压缩包
├── xt-etf-1.0.0.tar.gz.sha256    # 校验和
└── xt-etf-1.0.0/                 # 解压目录
    ├── binance/                  # Binance库
    ├── etf/                      # 核心代码
    ├── config/                   # 配置文件
    ├── scripts/                  # 运维脚本
    ├── docs/                     # 文档
    ├── run_etf.py                # 主入口
    ├── pyproject.toml            # 依赖定义
    ├── .env.example              # 环境变量模板
    ├── APIKey_template.json      # API密钥模板
    ├── ecosystem.config.js.template  # PM2配置模板
    ├── VERSION                   # 版本号
    ├── GIT_COMMIT                # Git提交哈希
    ├── BUILD_TIME                # 构建时间
    ├── QUICK_DEPLOY.md           # 快速部署指南
    └── MANIFEST.txt              # 文件清单
```

### 打包内容

**包含**:
- ✅ 所有核心Python代码
- ✅ 配置文件模板
- ✅ 运维脚本
- ✅ 关键文档
- ✅ 必需目录结构

**排除**:
- ❌ 版本控制文件（.git/）
- ❌ 虚拟环境（.venv/）
- ❌ Python缓存（__pycache__/）
- ❌ 日志文件（logs/）
- ❌ 敏感文件（APIKey.json, .env）
- ❌ 临时文件（*.tmp, *.bak）

---

## 🚀 部署流程

### 部署脚本使用

```bash
./scripts/deploy.sh <HOST> <USER> [VERSION] [OPTIONS]

# 参数
#   HOST     - 目标服务器地址
#   USER     - SSH用户名
#   VERSION  - 版本号（默认：最新）

# 选项
#   --deploy-path PATH   - 部署路径（默认：/opt/xt-etf）
#   --skip-backup        - 跳过备份
#   --no-restart         - 部署后不重启
#   --dry-run            - 模拟运行
```

### 部署步骤详解

#### 步骤1: 检查连接
- 测试SSH连接
- 验证服务器可达性

#### 步骤2: 准备目录
- 创建部署目录（/opt/xt-etf）
- 设置正确的权限
- 检查磁盘空间

#### 步骤3: 上传文件
- 上传tar.gz到服务器
- 传输进度显示

#### 步骤4: 服务器端部署
```bash
# 自动执行以下操作：
1. 备份当前版本（/opt/xt-etf/backups/）
2. 解压新版本
3. 保留现有配置（.env, APIKey.json.enc）
4. 停止旧服务
5. 切换到新版本
6. 设置Python环境
7. 启动新服务
8. 清理临时文件
```

#### 步骤5: 健康检查
- 检查PM2进程状态
- 验证服务运行正常
- 显示服务状态报告

### 部署示例

```bash
# 基本部署
./scripts/deploy.sh 192.168.1.100 trader

# 指定版本
./scripts/deploy.sh 192.168.1.100 trader 1.0.0

# 自定义路径
./scripts/deploy.sh 192.168.1.100 trader --deploy-path /home/trader/xt-etf

# 仅部署不重启
./scripts/deploy.sh 192.168.1.100 trader --no-restart

# 模拟运行（测试）
./scripts/deploy.sh 192.168.1.100 trader --dry-run
```

---

## ↩️ 回滚操作

### 回滚脚本使用

```bash
./scripts/rollback.sh [BACKUP_PATH] [OPTIONS]

# 选项
#   --list          列出所有可用备份
#   --no-restart    回滚后不重启服务
```

### 回滚场景

**场景1: 回滚到最新备份**
```bash
cd /opt/xt-etf/app
./scripts/rollback.sh
```

**场景2: 回滚到指定备份**
```bash
# 先列出备份
./scripts/rollback.sh --list

# 选择特定备份
./scripts/rollback.sh backups/20250129_143000
```

**场景3: 远程回滚**
```bash
ssh trader@production-server "/opt/xt-etf/app/scripts/rollback.sh"
```

### 回滚流程

1. **列出可用备份** - 显示所有备份及其信息
2. **确认回滚** - 用户确认操作
3. **停止服务** - 停止当前运行的服务
4. **备份失败版本** - 保存当前版本到failed_目录
5. **恢复代码** - 从备份解压代码
6. **恢复配置** - 保留当前的配置文件
7. **重启服务** - 使用PM2重启服务
8. **健康检查** - 验证服务状态

---

## 🖥️ 环境要求

### 操作系统

**推荐**:
- Ubuntu 20.04/22.04 LTS ⭐⭐⭐⭐⭐
- CentOS 8+ / RHEL 8+ ⭐⭐⭐⭐
- Debian 11+ ⭐⭐⭐⭐

**支持但不推荐**:
- macOS 11.0+ （开发环境可用）

### 硬件配置

| 配置类型 | CPU | 内存 | 存储 | 网络 |
|---------|-----|------|------|------|
| **最小** | 2核@2.4GHz | 4GB | 20GB SSD | 10Mbps |
| **推荐** | 4核@3.0GHz | 8GB | 50GB SSD | 100Mbps |
| **生产** | 8核@3.5GHz | 16GB | 100GB NVMe | 1Gbps |

### 必需软件

```bash
# Python
Python 3.8+（推荐3.11）

# Redis
Redis 6.x+
- 用途: 缓存、状态存储
- 配置: 持久化启用

# Node.js + PM2
Node.js 18.x+
PM2 5.x+
- 用途: 进程管理

# 系统工具
git, curl, tar, gzip
```

### 可选软件

```bash
# PostgreSQL（订单持久化）
PostgreSQL 9.6+

# 可观测性
Jaeger/Tempo（OpenTelemetry）
Prometheus + Grafana（监控）
```

### 环境检查

```bash
# 运行依赖检查脚本
./scripts/check_dependencies.sh

# 输出示例
🔍 XT ETF 环境依赖检查
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
1️⃣  操作系统检查...
✓ 操作系统: Linux
2️⃣  Python环境检查...
✓ Python: 3.11.0
3️⃣  Redis检查...
✓ Redis: v=6.2.6 (运行中)
4️⃣  Node.js和PM2检查...
✓ Node.js: v18.16.0
✓ PM2: 5.3.0
5️⃣  磁盘空间检查...
ℹ 可用空间: 45G
6️⃣  内存检查...
ℹ 可用内存: 6.8Gi
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
✅ 所有必需依赖检查通过！
```

---

## ⚙️ 配置说明

### 环境变量配置

```bash
# 复制模板
cp .env.example .env

# 编辑配置
vim .env
```

**必需配置**:
```bash
# Redis连接
REDIS_URL=redis://localhost:6379/0

# 日志级别
LOG_LEVEL=INFO

# 加密密钥密码（生产必需）
ETF_KEY_PASSWORD=your-secure-password
```

**可选配置**:
```bash
# OpenTelemetry
ENABLE_OTEL=true
OTLP_ENDPOINT=http://localhost:4317

# 数据库
DB_URL=postgresql+asyncpg://user:pass@localhost/xt_etf

# 告警
LARK_WEBHOOK_URL=https://open.feishu.cn/...
```

### API密钥配置

**方式1: 明文存储（仅开发环境）**
```bash
cp APIKey_template.json APIKey.json
vim APIKey.json  # 填写实际密钥
chmod 600 APIKey.json
```

**方式2: 加密存储（推荐生产环境）**
```bash
# 1. 准备明文密钥
cp APIKey_template.json APIKey.json
vim APIKey.json

# 2. 加密
export ETF_KEY_PASSWORD='your-secure-password'
python scripts/encrypt_apikeys.py

# 3. 删除明文（可选）
rm APIKey.json

# 4. 验证
ls -lh APIKey.json.enc
```

### PM2配置

```bash
# 复制模板
cp ecosystem.config.js.template ecosystem.config.js

# 编辑配置
vim ecosystem.config.js

# 关键修改
module.exports = {
  apps: [{
    name: 'etf-stg3l',
    script: 'run_etf.py',
    cwd: '/opt/xt-etf/app',  # ← 修改为实际路径
    // ... 其他配置
  }]
}
```

### 策略配置

```bash
# 编辑策略参数
vim config/strategies.yaml

# 关键参数
stg3l:
  symbol: "BTCUSDT"
  sleep_interval: 10          # 主循环间隔（秒）
  washing_interval: 30        # 刷量间隔（秒）
  bid_ask_spread: 0.008       # 买卖价差
  max_position: 100000        # 最大仓位
  stop_loss:
    enabled: true
    fixed_threshold: -0.02    # 固定止损 -2%
    trailing_stop: 0.01       # 移动止损 1%
    time_stop: 24             # 时间止损 24小时
```

---

## 🔒 安全最佳实践

### 1. 密钥管理

**DO ✅**:
- 生产环境使用加密存储
- 密钥文件权限 `chmod 600`
- 使用环境变量传递密码
- 定期轮换API密钥
- 不同策略使用独立密钥

**DON'T ❌**:
- 将密钥提交到Git
- 在日志中输出密钥
- 通过命令行参数传递密钥
- 使用弱密码加密
- 共享生产密钥

### 2. 网络安全

```bash
# 防火墙配置
sudo ufw enable
sudo ufw allow 22/tcp        # SSH
sudo ufw allow out 443/tcp   # HTTPS（交易所API）
sudo ufw deny in 6379/tcp    # Redis（仅本地）
```

### 3. 访问控制

```bash
# 创建专用用户
sudo useradd -m -s /bin/bash trader
sudo usermod -aG sudo trader  # 可选

# 设置目录权限
sudo chown -R trader:trader /opt/xt-etf
chmod 700 /opt/xt-etf
```

### 4. 日志安全

```bash
# 日志权限
chmod 640 logs/*.log

# 定期清理敏感日志
find logs/ -name "*.log" -mtime +30 -delete
```

---

## 🔧 故障排查

### 问题1: 上传失败

**症状**: `scp: permission denied`

**原因**: 权限不足或路径不存在

**解决**:
```bash
# 检查SSH连接
ssh user@server "echo 'test'"

# 检查目标目录
ssh user@server "ls -ld /opt/xt-etf"

# 创建目录
ssh user@server "sudo mkdir -p /opt/xt-etf && sudo chown user:user /opt/xt-etf"
```

### 问题2: 服务无法启动

**症状**: `PM2 error: Process not found`

**排查步骤**:
```bash
# 1. 检查PM2配置
cat ecosystem.config.js | grep cwd

# 2. 检查Python环境
source .venv/bin/activate
python --version

# 3. 检查依赖
./scripts/check_dependencies.sh

# 4. 手动启动测试
python run_etf.py --strategy stg3l
```

### 问题3: Redis连接失败

**症状**: `ConnectionRefusedError: [Errno 111]`

**解决**:
```bash
# 检查Redis状态
sudo systemctl status redis

# 启动Redis
sudo systemctl start redis

# 测试连接
redis-cli ping

# 检查配置
redis-cli CONFIG GET bind
```

### 问题4: API密钥错误

**症状**: `Invalid API-key, IP, or permissions`

**解决**:
```bash
# 1. 验证密钥格式
cat APIKey.json | jq .

# 2. 检查加密密码
echo $ETF_KEY_PASSWORD

# 3. 重新加密
python scripts/encrypt_apikeys.py

# 4. 测试API连接
python -c "from etf.exchange.xt import XTClient; print(XTClient().test_connection())"
```

### 问题5: 回滚失败

**症状**: 回滚后服务异常

**解决**:
```bash
# 1. 列出所有备份
./scripts/rollback.sh --list

# 2. 选择更早的备份
./scripts/rollback.sh backups/20250128_120000

# 3. 手动恢复
cd /opt/xt-etf
tar -xzf backups/20250128_120000/app_backup.tar.gz
pm2 restart all
```

---

## 📚 相关文档

- [完整部署指南](DEPLOYMENT_GUIDE.md) - 详细部署说明
- [用户指南](USER_GUIDE.md) - 系统使用手册
- [故障排查](TROUBLESHOOTING.md) - 常见问题解决
- [API密钥安全](API_KEY_SECURITY.md) - 密钥管理最佳实践
- [项目进度报告](PROJECT_PROGRESS_REPORT.md) - 当前项目状态

---

## 🤝 获取帮助

- **文档**: 查看 `CLAUDE.md` 和 `docs/` 目录
- **日志**: `pm2 logs` 查看运行日志
- **社区**: (项目仓库Issues)

---

**文档结束** - 更新日期: 2025-10-29
