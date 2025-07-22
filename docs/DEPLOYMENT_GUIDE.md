# ETF交易系统部署指南

本指南详细介绍ETF交易系统在不同环境中的部署方法，包括开发、测试和生产环境的完整部署流程。

## 目录

- [部署架构](#部署架构)
- [环境准备](#环境准备)
- [开发环境部署](#开发环境部署)
- [测试环境部署](#测试环境部署)
- [生产环境部署](#生产环境部署)
- [容器化部署](#容器化部署)
- [监控和日志](#监控和日志)
- [备份和恢复](#备份和恢复)
- [扩展和维护](#扩展和维护)

---

## 部署架构

### 系统组件架构

```
┌─────────────────────────────────────────────────┐
│                 ETF Trading System               │
├─────────────────┬─────────────────┬─────────────────┤
│   Strategy 1    │   Strategy 2    │   Strategy N    │
│   (stg3l)       │   (stg3s)       │   (stg5l/5s)    │
├─────────────────┼─────────────────┼─────────────────┤
│           Core Components                        │
│  ┌─────────────┬─────────────┬─────────────────┐   │
│  │ MarketMaker │ WashController │ RiskController │   │
│  └─────────────┴─────────────┴─────────────────┘   │
│           OrderManager & Utils                   │
├─────────────────────────────────────────────────┤
│                 Redis Cache                      │
├─────────────────────────────────────────────────┤
│              Exchange APIs                       │
│         (Binance, XT, etc.)                      │
└─────────────────────────────────────────────────┘
```

### 推荐部署拓扑

#### 单机部署（适合中小规模）
```
┌──────────────────────────────────┐
│         Application Server        │
│  ┌─────────────────────────────┐  │
│  │      ETF Strategies         │  │
│  │   (4 processes via PM2)     │  │
│  └─────────────────────────────┘  │
│  ┌─────────────────────────────┐  │
│  │        Redis Cache          │  │
│  └─────────────────────────────┘  │
│  ┌─────────────────────────────┐  │
│  │    Monitoring & Logs        │  │
│  └─────────────────────────────┘  │
└──────────────────────────────────┘
```

#### 分布式部署（适合大规模生产）
```
┌─────────────┐   ┌─────────────┐   ┌─────────────┐
│   App Node 1 │   │   App Node 2 │   │   App Node N │
│   stg3l/stg5l│   │   stg3s/stg5s│   │   Monitor    │
└─────────────┘   └─────────────┘   └─────────────┘
       │                 │                 │
       └─────────────────┼─────────────────┘
                         │
           ┌─────────────────────────────┐
           │      Redis Cluster          │
           │   (Master/Slave + Sentinel) │
           └─────────────────────────────┘
```

---

## 环境准备

### 硬件要求

#### 最小配置
- **CPU**: 2 cores, 2.4GHz+
- **RAM**: 4GB
- **Storage**: 20GB SSD
- **Network**: 10Mbps+

#### 推荐配置
- **CPU**: 4+ cores, 3.0GHz+
- **RAM**: 8GB+
- **Storage**: 50GB+ NVMe SSD
- **Network**: 100Mbps+

#### 生产环境配置
- **CPU**: 8+ cores, 3.5GHz+
- **RAM**: 16GB+
- **Storage**: 100GB+ NVMe SSD
- **Network**: 1Gbps+, 低延迟

### 操作系统要求

#### 支持的操作系统
- **Linux**: Ubuntu 20.04+, CentOS 8+, RHEL 8+
- **macOS**: 11.0+
- **Windows**: Windows 10+ (WSL2推荐)

#### 推荐配置 (Ubuntu 20.04 LTS)

```bash
# 系统更新
sudo apt update && sudo apt upgrade -y

# 安装基础依赖
sudo apt install -y build-essential curl wget git vim htop net-tools

# 安装Python 3.9+
sudo apt install -y python3.9 python3.9-venv python3.9-dev python3-pip

# 安装Node.js (用于PM2)
curl -fsSL https://deb.nodesource.com/setup_18.x | sudo -E bash -
sudo apt-get install -y nodejs

# 安装PM2
sudo npm install -g pm2

# 设置系统参数
echo "* soft nofile 65536" | sudo tee -a /etc/security/limits.conf
echo "* hard nofile 65536" | sudo tee -a /etc/security/limits.conf
```

---

## 开发环境部署

### 快速开发环境搭建

```bash
# 1. 克隆项目
git clone <repository-url>
cd xt_etf

# 2. 使用uv快速设置
curl -LsSf https://astral.sh/uv/install.sh | sh
./scripts/setup_uv.sh
source .venv/bin/activate

# 3. 安装Redis
sudo apt install redis-server
sudo systemctl start redis
sudo systemctl enable redis

# 4. 配置开发API密钥
cp APIKey_template.json APIKey_dev.json
# 编辑APIKey_dev.json添加测试API密钥

# 5. 运行测试
./scripts/run_tests.sh

# 6. 启动开发服务
./scripts/dev_start.sh stg3l
```

### 开发环境配置

#### 创建开发配置文件

```bash
# config/dev.yaml
redis:
  host: localhost
  port: 6379
  db: 1  # 使用不同的数据库

logging:
  level: DEBUG
  file: logs/dev.log

trading:
  paper_trading: true
  max_position: 10000  # 减少测试资金
  order_delay: 1       # 增加延迟便于调试
```

#### IDE配置建议

**VS Code配置** (`.vscode/settings.json`):
```json
{
    "python.defaultInterpreterPath": "./.venv/bin/python",
    "python.formatting.provider": "black",
    "python.linting.enabled": true,
    "python.linting.pylintEnabled": true,
    "python.testing.pytestEnabled": true
}
```

---

## 测试环境部署

### 测试环境架构

```bash
# 1. 创建测试目录结构
mkdir -p /opt/etf-trading-test/{config,logs,data,backups}

# 2. 克隆代码到测试目录
cd /opt/etf-trading-test
git clone <repository-url> app
cd app

# 3. 设置测试环境
python3 -m venv .venv
source .venv/bin/activate
pip install -e .

# 4. 配置测试专用Redis
sudo cp /etc/redis/redis.conf /etc/redis/redis-test.conf
sudo sed -i 's/port 6379/port 6380/' /etc/redis/redis-test.conf
sudo sed -i 's|dir /var/lib/redis|dir /var/lib/redis-test|' /etc/redis/redis-test.conf

# 启动测试Redis实例
redis-server /etc/redis/redis-test.conf --daemonize yes
```

### 测试配置管理

#### 创建测试配置

```yaml
# config/test.yaml
environment: test
redis:
  host: localhost
  port: 6380
  db: 0

api:
  base_url: "https://testnet.exchange.com"
  timeout: 30

strategies:
  stg3l:
    symbol: "btc3l_usdt"
    max_position: 50000
    paper_trading: true
    
logging:
  level: INFO
  rotation: "1 day"
  retention: "7 days"
```

#### 自动化测试部署

```bash
# 创建测试部署脚本
cat > deploy-test.sh << 'EOF'
#!/bin/bash
set -e

echo "🚀 Deploying to test environment..."

# 拉取最新代码
git pull origin main

# 安装依赖
source .venv/bin/activate
pip install -e .

# 运行测试
./scripts/run_tests.sh

# 重启测试服务
pm2 restart ecosystem.test.config.js

echo "✅ Test deployment completed"
EOF

chmod +x deploy-test.sh
```

---

## 生产环境部署

### 生产环境准备

#### 1. 系统用户创建

```bash
# 创建专用用户
sudo useradd -m -s /bin/bash etf-trader
sudo usermod -aG docker etf-trader  # 如果使用Docker

# 创建目录结构
sudo mkdir -p /opt/etf-trading/{app,config,logs,data,backups}
sudo chown -R etf-trader:etf-trader /opt/etf-trading

# 切换到专用用户
sudo su - etf-trader
cd /opt/etf-trading
```

#### 2. 安全配置

```bash
# 设置防火墙
sudo ufw enable
sudo ufw allow ssh
sudo ufw allow 6379  # Redis端口（仅内网）

# 配置SSH密钥认证
mkdir -p ~/.ssh
chmod 700 ~/.ssh
# 上传公钥到 ~/.ssh/authorized_keys
chmod 600 ~/.ssh/authorized_keys

# 禁用密码认证
sudo sed -i 's/#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo systemctl restart ssh
```

#### 3. Redis生产配置

```bash
# 备份原配置
sudo cp /etc/redis/redis.conf /etc/redis/redis.conf.backup

# 生产环境配置
sudo tee /etc/redis/redis-prod.conf << 'EOF'
# 网络配置
bind 127.0.0.1
port 6379
tcp-backlog 511

# 内存管理
maxmemory 4gb
maxmemory-policy allkeys-lru

# 持久化
save 900 1
save 300 10
save 60 10000
rdbcompression yes
dbfilename dump.rdb
dir /var/lib/redis/

# 日志
logfile /var/log/redis/redis-server.log
loglevel notice

# 安全
requirepass your_strong_password_here
EOF

# 重启Redis
sudo systemctl restart redis
sudo systemctl enable redis
```

### 生产部署脚本

#### 自动化部署脚本

```bash
cat > deploy-prod.sh << 'EOF'
#!/bin/bash
set -e

DEPLOY_DIR="/opt/etf-trading"
APP_DIR="$DEPLOY_DIR/app"
BACKUP_DIR="$DEPLOY_DIR/backups/$(date +%Y%m%d_%H%M%S)"

echo "🚀 Starting production deployment..."

# 创建备份
echo "📦 Creating backup..."
mkdir -p "$BACKUP_DIR"
if [ -d "$APP_DIR" ]; then
    cp -r "$APP_DIR" "$BACKUP_DIR/app_backup"
fi

# 拉取新代码
echo "📥 Fetching latest code..."
if [ -d "$APP_DIR" ]; then
    cd "$APP_DIR"
    git pull origin main
else
    git clone <repository-url> "$APP_DIR"
    cd "$APP_DIR"
fi

# 安装依赖
echo "📦 Installing dependencies..."
source .venv/bin/activate
pip install -e .

# 运行测试
echo "🧪 Running tests..."
./scripts/run_tests.sh

# 停止旧服务
echo "⏹️ Stopping old services..."
pm2 stop all

# 启动新服务
echo "▶️ Starting new services..."
pm2 start ecosystem.config.js
pm2 save

echo "✅ Production deployment completed"
echo "📊 Monitoring: pm2 monit"
EOF

chmod +x deploy-prod.sh
```

#### 生产环境PM2配置

```javascript
// ecosystem.config.js
module.exports = {
  apps: [
    {
      name: 'etf-stg3l',
      script: 'python',
      args: 'run_etf.py --strategy stg3l --env prod',
      cwd: '/opt/etf-trading/app',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/etf-trading/app'
      },
      error_file: '/opt/etf-trading/logs/stg3l.error.log',
      out_file: '/opt/etf-trading/logs/stg3l.out.log',
      log_file: '/opt/etf-trading/logs/stg3l.combined.log',
      time: true
    },
    {
      name: 'etf-stg3s',
      script: 'python',
      args: 'run_etf.py --strategy stg3s --env prod',
      cwd: '/opt/etf-trading/app',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/etf-trading/app'
      },
      error_file: '/opt/etf-trading/logs/stg3s.error.log',
      out_file: '/opt/etf-trading/logs/stg3s.out.log',
      log_file: '/opt/etf-trading/logs/stg3s.combined.log',
      time: true
    },
    {
      name: 'etf-stg5l',
      script: 'python',
      args: 'run_etf.py --strategy stg5l --env prod',
      cwd: '/opt/etf-trading/app',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/etf-trading/app'
      },
      error_file: '/opt/etf-trading/logs/stg5l.error.log',
      out_file: '/opt/etf-trading/logs/stg5l.out.log',
      log_file: '/opt/etf-trading/logs/stg5l.combined.log',
      time: true
    },
    {
      name: 'etf-stg5s',
      script: 'python',
      args: 'run_etf.py --strategy stg5s --env prod',
      cwd: '/opt/etf-trading/app',
      instances: 1,
      autorestart: true,
      watch: false,
      max_memory_restart: '2G',
      env: {
        NODE_ENV: 'production',
        PYTHONPATH: '/opt/etf-trading/app'
      },
      error_file: '/opt/etf-trading/logs/stg5s.error.log',
      out_file: '/opt/etf-trading/logs/stg5s.out.log',
      log_file: '/opt/etf-trading/logs/stg5s.combined.log',
      time: true
    }
  ]
};
```

---

## 容器化部署

### Docker部署

#### Dockerfile

```dockerfile
FROM python:3.9-slim

# 设置工作目录
WORKDIR /app

# 安装系统依赖
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    && rm -rf /var/lib/apt/lists/*

# 复制依赖文件
COPY requirements.txt .
COPY pyproject.toml .

# 安装Python依赖
RUN pip install --no-cache-dir -e .

# 复制应用代码
COPY . .

# 创建非root用户
RUN useradd -m -s /bin/bash trader
RUN chown -R trader:trader /app
USER trader

# 健康检查
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
  CMD python -c "import redis; r=redis.Redis(); r.ping()" || exit 1

# 启动命令
CMD ["python", "run_etf.py", "--strategy", "stg3l"]
```

#### Docker Compose

```yaml
# docker-compose.yml
version: '3.8'

services:
  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"
    volumes:
      - redis_data:/data
      - ./config/redis.conf:/usr/local/etc/redis/redis.conf
    command: redis-server /usr/local/etc/redis/redis.conf
    restart: unless-stopped

  etf-stg3l:
    build: .
    depends_on:
      - redis
    environment:
      - STRATEGY=stg3l
      - ENV=prod
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    restart: unless-stopped
    mem_limit: 2g
    
  etf-stg3s:
    build: .
    depends_on:
      - redis
    environment:
      - STRATEGY=stg3s
      - ENV=prod
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    restart: unless-stopped
    mem_limit: 2g

  etf-stg5l:
    build: .
    depends_on:
      - redis
    environment:
      - STRATEGY=stg5l
      - ENV=prod
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    restart: unless-stopped
    mem_limit: 2g

  etf-stg5s:
    build: .
    depends_on:
      - redis
    environment:
      - STRATEGY=stg5s
      - ENV=prod
    volumes:
      - ./config:/app/config:ro
      - ./logs:/app/logs
    restart: unless-stopped
    mem_limit: 2g

volumes:
  redis_data:
```

#### 容器化部署命令

```bash
# 构建镜像
docker-compose build

# 启动所有服务
docker-compose up -d

# 查看状态
docker-compose ps

# 查看日志
docker-compose logs -f etf-stg3l

# 停止服务
docker-compose down

# 更新部署
docker-compose pull && docker-compose up -d
```

---

## 监控和日志

### 系统监控

#### Systemd服务监控

```bash
# 创建systemd服务文件
sudo tee /etc/systemd/system/etf-trading.service << 'EOF'
[Unit]
Description=ETF Trading System
After=network.target redis.service

[Service]
Type=forking
User=etf-trader
WorkingDirectory=/opt/etf-trading/app
ExecStart=/usr/local/bin/pm2 start ecosystem.config.js --no-daemon
ExecReload=/usr/local/bin/pm2 reload ecosystem.config.js
ExecStop=/usr/local/bin/pm2 stop ecosystem.config.js
Restart=always

[Install]
WantedBy=multi-user.target
EOF

# 启用服务
sudo systemctl enable etf-trading
sudo systemctl start etf-trading
```

#### 监控脚本

```bash
#!/bin/bash
# monitor.sh - 系统监控脚本

ALERT_EMAIL="admin@company.com"
LOG_FILE="/opt/etf-trading/logs/monitor.log"

check_process() {
    local process_name=$1
    if ! pm2 show "$process_name" | grep -q "online"; then
        echo "$(date): ALERT - $process_name is not running" >> "$LOG_FILE"
        echo "Process $process_name is down" | mail -s "ETF Trading Alert" "$ALERT_EMAIL"
        pm2 restart "$process_name"
    fi
}

check_redis() {
    if ! redis-cli ping | grep -q "PONG"; then
        echo "$(date): ALERT - Redis is not responding" >> "$LOG_FILE"
        echo "Redis is down" | mail -s "ETF Trading Alert" "$ALERT_EMAIL"
        sudo systemctl restart redis
    fi
}

check_memory() {
    local mem_usage=$(free | awk 'NR==2{printf "%.0f", $3*100/$2}')
    if [ "$mem_usage" -gt 90 ]; then
        echo "$(date): WARNING - High memory usage: ${mem_usage}%" >> "$LOG_FILE"
    fi
}

# 主监控循环
check_process "etf-stg3l"
check_process "etf-stg3s" 
check_process "etf-stg5l"
check_process "etf-stg5s"
check_redis
check_memory

# 清理旧日志
find /opt/etf-trading/logs -name "*.log" -mtime +7 -delete
```

### 日志管理

#### Logrotate配置

```bash
sudo tee /etc/logrotate.d/etf-trading << 'EOF'
/opt/etf-trading/logs/*.log {
    daily
    missingok
    rotate 30
    compress
    delaycompress
    notifempty
    sharedscripts
    postrotate
        pm2 reloadLogs
    endscript
}
EOF
```

---

## 备份和恢复

### 数据备份策略

#### 自动备份脚本

```bash
#!/bin/bash
# backup.sh - 数据备份脚本

BACKUP_DIR="/opt/etf-trading/backups"
DATE=$(date +%Y%m%d_%H%M%S)
BACKUP_PATH="$BACKUP_DIR/$DATE"

# 创建备份目录
mkdir -p "$BACKUP_PATH"

# 备份Redis数据
redis-cli BGSAVE
cp /var/lib/redis/dump.rdb "$BACKUP_PATH/"

# 备份配置文件
cp -r /opt/etf-trading/config "$BACKUP_PATH/"

# 备份应用代码
cd /opt/etf-trading
tar -czf "$BACKUP_PATH/app_code.tar.gz" app/

# 备份日志（最近7天）
find /opt/etf-trading/logs -name "*.log" -mtime -7 -exec cp {} "$BACKUP_PATH/" \;

# 上传到远程存储（可选）
# aws s3 sync "$BACKUP_PATH" s3://etf-trading-backups/$DATE/

# 清理旧备份（保留30天）
find "$BACKUP_DIR" -type d -mtime +30 -exec rm -rf {} \;

echo "Backup completed: $BACKUP_PATH"
```

#### 添加到Crontab

```bash
# 每日自动备份
crontab -e

# 添加以下行
0 2 * * * /opt/etf-trading/scripts/backup.sh >> /opt/etf-trading/logs/backup.log 2>&1
```

### 灾难恢复

#### 恢复流程

```bash
#!/bin/bash
# restore.sh - 系统恢复脚本

BACKUP_PATH=$1
if [ -z "$BACKUP_PATH" ]; then
    echo "Usage: $0 <backup_path>"
    exit 1
fi

# 停止服务
pm2 stop all
sudo systemctl stop redis

# 恢复Redis数据
sudo cp "$BACKUP_PATH/dump.rdb" /var/lib/redis/
sudo chown redis:redis /var/lib/redis/dump.rdb

# 恢复配置文件
cp -r "$BACKUP_PATH/config"/* /opt/etf-trading/config/

# 恢复应用代码
cd /opt/etf-trading
tar -xzf "$BACKUP_PATH/app_code.tar.gz"

# 重启服务
sudo systemctl start redis
sleep 5
pm2 start ecosystem.config.js

echo "Restore completed from: $BACKUP_PATH"
```

---

## 扩展和维护

### 水平扩展

#### 负载均衡配置

```bash
# 安装Nginx
sudo apt install nginx

# 配置负载均衡
sudo tee /etc/nginx/sites-available/etf-trading << 'EOF'
upstream etf_backend {
    server 10.0.1.10:8080;  # App Server 1
    server 10.0.1.11:8080;  # App Server 2
    server 10.0.1.12:8080;  # App Server 3
}

server {
    listen 80;
    server_name etf-trading.company.com;
    
    location / {
        proxy_pass http://etf_backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
    }
    
    location /health {
        access_log off;
        return 200 "healthy\n";
    }
}
EOF

sudo ln -s /etc/nginx/sites-available/etf-trading /etc/nginx/sites-enabled/
sudo systemctl reload nginx
```

### 定期维护

#### 维护检查清单

```bash
# 每日检查
- [ ] 检查所有策略进程状态
- [ ] 检查Redis内存使用情况  
- [ ] 检查API连接状态
- [ ] 检查错误日志
- [ ] 验证备份完成

# 每周检查
- [ ] 检查系统资源使用
- [ ] 清理旧日志文件
- [ ] 更新系统补丁
- [ ] 检查磁盘空间
- [ ] 性能基准测试

# 每月检查  
- [ ] 轮换API密钥
- [ ] 检查安全更新
- [ ] 审查监控告警
- [ ] 优化数据库性能
- [ ] 灾难恢复测试
```

#### 自动维护脚本

```bash
#!/bin/bash
# maintenance.sh - 定期维护脚本

LOG_FILE="/opt/etf-trading/logs/maintenance.log"

echo "$(date): Starting maintenance tasks..." >> "$LOG_FILE"

# 清理临时文件
find /tmp -name "*.tmp" -mtime +1 -delete

# 更新依赖包
cd /opt/etf-trading/app
source .venv/bin/activate
pip list --outdated >> "$LOG_FILE"

# 系统更新检查
apt list --upgradable 2>/dev/null | grep -v "WARNING" >> "$LOG_FILE"

# 磁盘空间检查
df -h >> "$LOG_FILE"

# Redis内存统计
redis-cli info memory >> "$LOG_FILE"

echo "$(date): Maintenance tasks completed." >> "$LOG_FILE"
```

---

## 故障排查

### 常见部署问题

#### 1. 端口冲突
```bash
# 检查端口占用
netstat -tlnp | grep 6379
lsof -i :6379

# 解决方案：修改端口或停止冲突服务
```

#### 2. 权限问题
```bash
# 检查文件权限
ls -la /opt/etf-trading/
# 修复权限
sudo chown -R etf-trader:etf-trader /opt/etf-trading/
```

#### 3. 内存不足
```bash
# 检查内存使用
free -h
ps aux --sort=-%mem | head

# 增加swap空间
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
```

### 紧急响应流程

1. **立即响应** (5分钟内)
   - 停止所有交易策略
   - 检查系统状态
   - 记录问题现象

2. **问题分析** (15分钟内)
   - 检查日志文件
   - 分析错误信息
   - 确定影响范围

3. **临时修复** (30分钟内)
   - 实施临时解决方案
   - 恢复关键功能
   - 通知相关人员

4. **长期修复**
   - 分析根本原因
   - 实施永久解决方案
   - 更新文档和流程

---

*最后更新: 2025-01-22*
*版本: 1.0.0*