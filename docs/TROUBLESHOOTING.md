# ETF交易系统故障排查指南

本指南提供ETF交易系统常见问题的快速诊断和解决方案，帮助用户快速定位和解决系统运行中遇到的问题。

## 🚨 紧急问题快速处理

### 系统完全停止
```bash
# 紧急停止所有交易
pm2 stop all

# 检查系统状态
pm2 list
systemctl status redis

# 快速重启
systemctl restart redis
pm2 restart all
```

### 内存不足
```bash
# 立即释放内存
pm2 restart all
# 清理系统缓存
sudo sync && echo 3 > /proc/sys/vm/drop_caches
```

---

## 🔍 常见问题诊断

### 1. 连接问题

#### WebSocket连接失败

**现象**:
```
WebSocket connection failed: Connection timeout
Connection refused to api.example.com:443
```

**诊断步骤**:
```bash
# 1. 检查网络连接
ping api.binance.com
ping api.xt.com

# 2. 检查DNS解析
nslookup api.binance.com

# 3. 检查防火墙
sudo ufw status
telnet api.binance.com 443

# 4. 检查API密钥
python -c "
import json
with open('APIKey_prod.json') as f:
    print(json.load(f)['api_key'][:10] + '...')
"
```

**解决方案**:
1. **网络问题**: 检查网络连接，联系网络管理员
2. **API密钥问题**: 验证密钥正确性，检查权限设置
3. **防火墙问题**: 添加白名单规则
4. **服务器问题**: 切换备用API端点

#### Redis连接失败

**现象**:
```
redis.exceptions.ConnectionError: Error connecting to Redis
```

**诊断步骤**:
```bash
# 1. 检查Redis状态
systemctl status redis
redis-cli ping

# 2. 检查端口占用
netstat -tlnp | grep 6379
lsof -i :6379

# 3. 检查配置文件
cat /etc/redis/redis.conf | grep -E "^(bind|port|requirepass)"

# 4. 检查日志
tail -f /var/log/redis/redis-server.log
```

**解决方案**:
```bash
# 重启Redis
sudo systemctl restart redis

# 检查配置
redis-cli config get '*'

# 清理Redis数据（如果需要）
redis-cli flushall
```

### 2. 性能问题

#### 订单处理缓慢

**现象**:
```
订单匹配平均耗时: 2.5678s (正常应 < 0.1s)
批量处理平均耗时: 5.2341s (正常应 < 1.0s)
```

**诊断步骤**:
```bash
# 1. 检查系统负载
htop
top -p $(pgrep -f "run_etf.py")

# 2. 检查内存使用
free -h
ps aux --sort=-%mem | grep python

# 3. 检查磁盘IO
iotop
df -h

# 4. 检查网络延迟
ping -c 10 api.binance.com
```

**解决方案**:
```bash
# 1. 重启进程释放内存
pm2 restart etf-stg3l

# 2. 优化Redis配置
redis-cli config set maxmemory-policy allkeys-lru

# 3. 清理日志文件
find /opt/etf-trading/logs -name "*.log" -mtime +3 -delete

# 4. 检查算法优化是否启用
grep -n "optimize_order_matching" /opt/etf-trading/app/etf/market_making.py
```

#### 内存泄漏

**现象**:
```
Process memory continuously growing
OOMKilled events in system log
```

**诊断步骤**:
```bash
# 1. 监控内存使用趋势
while true; do
    ps aux | grep "run_etf.py" | awk '{print $6}' 
    sleep 60
done

# 2. 检查Python内存分析
python -m memory_profiler run_etf.py --strategy stg3l

# 3. 查看系统日志
journalctl -u etf-trading -f | grep -i "killed"
```

**解决方案**:
```bash
# 1. 设置内存限制
pm2 restart etf-stg3l --max-memory-restart 2G

# 2. 启用垃圾回收
export PYTHONOPTIMIZE=1

# 3. 定期重启（临时方案）
crontab -e
# 添加: 0 */6 * * * pm2 restart etf-stg3l
```

### 3. 交易相关问题

#### 订单被拒绝

**现象**:
```
APIError: Order rejected - Insufficient balance
APIError: Rate limit exceeded
OrderError: Invalid price precision
```

**诊断步骤**:
```bash
# 1. 检查账户余额
python -c "
from etf.client import get_client
client = get_client()
print(client.get_account())
"

# 2. 检查订单参数
grep -A 10 "order_data" /opt/etf-trading/logs/stg3l.out.log

# 3. 检查交易规则
python -c "
from etf.client import get_client
client = get_client()
print(client.get_exchange_info())
"
```

**解决方案**:
1. **余额不足**: 充值或调整仓位大小
2. **限频**: 增加请求间隔，检查API权限
3. **精度错误**: 检查交易对的价格和数量精度规则
4. **交易时间**: 确认在交易时间内执行

#### 净值计算错误

**现象**:
```
NetValue calculation failed
Redis key netvalue_btc3l not found
Abnormal price spike detected
```

**诊断步骤**:
```bash
# 1. 检查Redis中的净值数据
redis-cli get netvalue_btc3l
redis-cli hgetall netvalue_btc3l_detail

# 2. 检查净值计算进程
pm2 show etf-netvalue-stg3l

# 3. 检查价格数据来源
python -c "
from etf.client import get_client
client = get_client()
print(client.get_ticker_price('BTCUSDT'))
"
```

**解决方案**:
```bash
# 1. 重启净值计算
pm2 restart etf-netvalue-stg3l

# 2. 手动设置初始净值（紧急情况）
redis-cli set netvalue_btc3l 1.0

# 3. 检查价格源配置
grep -n "price_source" /opt/etf-trading/config/strategies.yaml
```

### 4. 系统级问题

#### 磁盘空间不足

**现象**:
```
No space left on device
日志文件无法写入
```

**诊断和解决**:
```bash
# 1. 检查磁盘使用情况
df -h
du -sh /opt/etf-trading/* | sort -hr

# 2. 清理日志文件
find /opt/etf-trading/logs -name "*.log" -mtime +7 -delete
pm2 flush  # 清理PM2日志

# 3. 清理临时文件
sudo apt autoclean
sudo apt autoremove

# 4. 紧急扩容（如果可能）
sudo lvextend -l +100%FREE /dev/vg0/lv0
sudo resize2fs /dev/vg0/lv0
```

#### CPU使用率过高

**现象**:
```
Load average > 4.0
Python进程CPU使用率 > 80%
```

**诊断和解决**:
```bash
# 1. 定位高CPU进程
htop
ps aux --sort=-%cpu | head -10

# 2. 分析Python进程
python -m cProfile run_etf.py --strategy stg3l

# 3. 调整进程优先级
renice 10 $(pgrep -f "run_etf.py")

# 4. 优化策略参数
# 增加sleep_interval减少CPU占用
```

---

## 🛠️ 诊断工具和命令

### 系统状态检查

```bash
#!/bin/bash
# system-check.sh - 系统健康检查脚本

echo "=== ETF Trading System Health Check ==="
echo "Time: $(date)"
echo

# 检查进程状态
echo "1. Process Status:"
pm2 list

# 检查Redis状态
echo "2. Redis Status:"
redis-cli ping
redis-cli info memory | grep used_memory_human

# 检查系统资源
echo "3. System Resources:"
echo "Memory: $(free -h | awk 'NR==2{printf "%.0f%% used", $3*100/$2}')"
echo "CPU: $(top -bn1 | grep "Cpu(s)" | awk '{print $2}' | cut -d'%' -f1)% used"
echo "Disk: $(df -h / | awk 'NR==2{print $5}')"

# 检查网络连接
echo "4. Network Connectivity:"
ping -c 1 api.binance.com > /dev/null && echo "Binance API: OK" || echo "Binance API: FAILED"
ping -c 1 api.xt.com > /dev/null && echo "XT API: OK" || echo "XT API: FAILED"

# 检查最近错误
echo "5. Recent Errors:"
grep -i error /opt/etf-trading/logs/*.log | tail -5

echo "=== Health Check Complete ==="
```

### 日志分析工具

```bash
# 快速查看错误日志
alias log-errors="grep -i 'error\|exception\|failed' /opt/etf-trading/logs/*.log | tail -20"

# 查看特定策略日志
alias log-stg3l="tail -f /opt/etf-trading/logs/stg3l.out.log"

# 分析交易统计
alias trade-stats="grep -o 'successful.*orders\|failed.*orders' /opt/etf-trading/logs/*.log | sort | uniq -c"

# 监控内存使用
alias mem-monitor="watch -n 5 'ps aux --sort=-%mem | head -10'"
```

---

## 📞 支持和联系

### 紧急联系信息

- **系统管理员**: admin@company.com
- **技术支持**: support@company.com  
- **紧急电话**: +86-xxx-xxxx-xxxx

### 问题报告模板

当报告问题时，请提供以下信息：

```
问题描述：
[简要描述遇到的问题]

发生时间：
[问题发生的具体时间]

影响范围：
[哪些策略或功能受到影响]

错误信息：
[相关的错误日志或截图]

系统环境：
- 操作系统：
- Python版本：
- Redis版本：
- 策略版本：

已尝试的解决方案：
[已经尝试过的修复方法]

其他信息：
[任何其他相关信息]
```

### 日志收集脚本

```bash
#!/bin/bash
# collect-logs.sh - 收集故障诊断信息

REPORT_DIR="/tmp/etf-debug-$(date +%Y%m%d_%H%M%S)"
mkdir -p "$REPORT_DIR"

echo "Collecting system information..."

# 系统基本信息
uname -a > "$REPORT_DIR/system_info.txt"
cat /etc/os-release >> "$REPORT_DIR/system_info.txt"

# 进程状态
pm2 list > "$REPORT_DIR/pm2_status.txt"
ps aux | grep -E "(python|redis)" > "$REPORT_DIR/processes.txt"

# 系统资源
free -h > "$REPORT_DIR/memory.txt"
df -h > "$REPORT_DIR/disk.txt"
top -bn1 > "$REPORT_DIR/cpu.txt"

# Redis信息
redis-cli info > "$REPORT_DIR/redis_info.txt"

# 应用日志（最近1000行）
tail -1000 /opt/etf-trading/logs/*.log > "$REPORT_DIR/app_logs.txt"

# 系统日志
journalctl -u etf-trading --since "1 hour ago" > "$REPORT_DIR/system_logs.txt"

# 配置文件（不包含密钥）
cp -r /opt/etf-trading/config "$REPORT_DIR/"
find "$REPORT_DIR/config" -name "*key*" -delete

# 打包
tar -czf "${REPORT_DIR}.tar.gz" -C /tmp "$(basename $REPORT_DIR)"
echo "Debug information collected: ${REPORT_DIR}.tar.gz"
```

---

## 📚 更多资源

- [API参考文档](API_REFERENCE.md)
- [用户指南](USER_GUIDE.md)  
- [部署指南](DEPLOYMENT_GUIDE.md)
- [GitHub Issues](https://github.com/company/etf-trading/issues)

---

*最后更新: 2025-01-22*
*版本: 1.0.0*