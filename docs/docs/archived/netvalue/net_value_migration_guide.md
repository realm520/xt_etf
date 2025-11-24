# 净值计算系统升级迁移指南

## 概述

本指南帮助您从现有的净值计算系统迁移到改进版系统。改进版解决了程序重启导致的净值计算错误问题。

## 主要改进

### 1. 数据结构增强
- 增加时间戳记录，支持断线检测
- 存储更多元数据（价格历史、异常事件等）
- 保留净值历史记录用于审计

### 2. 断线恢复机制
- 自动检测程序重启间隔
- 基于历史数据或K线恢复净值
- 精确补算管理费

### 3. 异常保护
- 单次价格变化限制（默认10%）
- 异常事件记录和告警
- 数据验证和容错处理

## 迁移步骤

### 第一步：备份现有数据

```bash
# 备份当前净值
redis-cli get netvalue_stg3l > backup_netvalue_stg3l.txt
redis-cli get netvalue_stg3s > backup_netvalue_stg3s.txt
redis-cli get netvalue_stg5l > backup_netvalue_stg5l.txt
redis-cli get netvalue_stg5s > backup_netvalue_stg5s.txt
```

### 第二步：部署新代码

1. 将改进版代码复制到项目中：
```bash
cp etf/net_value_improved.py .
cp etf/net_value_recovery.py etf/
```

2. 安装测试代码（可选）：
```bash
cp tests/test_net_value_improved.py tests/
```

### 第三步：创建迁移脚本

创建 `migrate_net_value.py`：

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-

import redis
import json
import time

def migrate_net_value(symbol, m_lever, long=True):
    """迁移单个净值数据"""
    r = redis.Redis(host='localhost', port=6379, db=0, decode_responses=True)

    # 构建键名
    direction = "l" if long else "s"
    old_key = f'netvalue_{symbol.split("_")[0]}{m_lever}{direction}'
    new_detail_key = f'{old_key}_detail'

    # 读取旧数据
    old_value = r.get(old_key)
    if not old_value:
        print(f"未找到旧数据: {old_key}")
        return

    net_value = float(old_value)

    # 创建新数据结构
    new_data = {
        "net_value": net_value,
        "last_price": None,  # 需要从市场获取
        "last_update_ts": time.time(),
        "create_ts": time.time(),
        "update_count": 0,
        "total_fee_deducted": 0.0,
        "abnormal_events": [{
            "type": "migration",
            "from_version": "v1",
            "to_version": "v2",
            "timestamp": time.time()
        }]
    }

    # 保存新数据
    r.set(new_detail_key, json.dumps(new_data))
    print(f"迁移完成: {old_key} -> {new_detail_key}")
    print(f"净值: {net_value}")

if __name__ == "__main__":
    # 迁移所有策略
    configs = [
        ("stg_usdt", 3, True),   # STG 3倍做多
        ("stg_usdt", 3, False),  # STG 3倍做空
        ("stg_usdt", 5, True),   # STG 5倍做多
        ("stg_usdt", 5, False),  # STG 5倍做空
    ]

    for symbol, m_lever, long in configs:
        migrate_net_value(symbol, m_lever, long)
```

### 第四步：更新启动脚本

创建新的启动脚本 `net_value_stg3l_v2.py`：

```python
#!/usr/bin/env python
# -*- coding:utf-8 -*-

from etf.net_value_improved import ImprovedNetValue

if __name__ == '__main__':
    config = {
        "symbol": "stg_usdt",
        "m_lever": 3,
        "long": True,
        "time_gap_second": 10,
        "rebalance": 0.05,
        "daily_fee": 0.001,
        "max_single_change": 0.10,  # 新增：最大单次变化限制
        "max_restart_gap": 300      # 新增：最大重启间隔（5分钟）
    }

    calculator = ImprovedNetValue(**config)
    calculator.run()
```

### 第五步：测试验证

1. 运行单元测试：
```bash
pytest tests/test_net_value_improved.py -v
```

2. 进行小规模测试：
```bash
# 使用测试环境运行新版本
python net_value_stg3l_v2.py
```

3. 验证数据存储：
```bash
# 检查Redis数据
redis-cli get netvalue_stg3l
redis-cli get netvalue_stg3l_detail
```

### 第六步：切换到新系统

1. **停止旧版本**：
```bash
# 找到并停止旧进程
ps aux | grep net_value_stg
kill <PID>
```

2. **运行迁移脚本**：
```bash
python migrate_net_value.py
```

3. **启动新版本**：
```bash
# 使用PM2或其他进程管理器
pm2 start net_value_stg3l_v2.py --name "netvalue-stg3l-v2"
pm2 start net_value_stg3s_v2.py --name "netvalue-stg3s-v2"
pm2 start net_value_stg5l_v2.py --name "netvalue-stg5l-v2"
pm2 start net_value_stg5s_v2.py --name "netvalue-stg5s-v2"
```

### 第七步：监控和验证

1. **检查日志**：
```bash
pm2 logs netvalue-stg3l-v2
```

2. **监控Redis数据**：
```bash
# 监控脚本
watch -n 1 'redis-cli get netvalue_stg3l && redis-cli get netvalue_stg3l_detail | jq .'
```

3. **验证断线恢复**：
```bash
# 模拟重启
pm2 restart netvalue-stg3l-v2
# 检查日志中的恢复信息
```

## 回滚方案

如果需要回滚到旧版本：

1. 停止新版本进程
2. 从备份恢复净值数据
3. 重启旧版本程序

```bash
# 恢复备份
redis-cli set netvalue_stg3l "$(cat backup_netvalue_stg3l.txt)"
# 启动旧版本
python net_value_stg3l.py
```

## 注意事项

1. **兼容性**：新版本保持向后兼容，继续更新旧的Redis键
2. **监控**：迁移后密切监控系统运行状态
3. **备份**：保留备份数据至少一周
4. **渐进式迁移**：可以先迁移一个策略，验证无误后再迁移其他

## 配置参数说明

| 参数 | 默认值 | 说明 |
|------|--------|------|
| max_single_change | 0.10 | 单次价格变化最大限制（10%） |
| max_restart_gap | 300 | 最大重启间隔（300秒=5分钟） |
| daily_fee | 0.001 | 日管理费率（0.1%） |
| rebalance | 0.05 | 再平衡阈值（5%） |

## 故障排查

### 问题1：净值异常跳变
- 检查 `abnormal_events` 记录
- 调整 `max_single_change` 参数

### 问题2：重启后净值不连续
- 检查日志中的恢复记录
- 验证 `max_restart_gap` 设置

### 问题3：Redis连接失败
- 检查Redis服务状态
- 验证连接参数

## 联系支持

如有问题，请联系：
- Email: huangyongjie088@gmail.com
- 提供日志文件和Redis数据快照
