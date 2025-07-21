# 归档的原始策略脚本

## 说明

这个目录包含了原始的 ETF 策略启动脚本。这些文件已被新的统一系统替代，但保留在此用于：

1. **历史参考** - 查看原始实现
2. **紧急回滚** - 如果新系统出现问题
3. **对比验证** - 确保新系统行为一致

## 归档文件

### 交易策略文件
- `run_etf_stg3l.py` - 3倍做多策略（5秒循环间隔）
- `run_etf_stg3s.py` - 3倍做空策略
- `run_etf_stg5l.py` - 5倍做多策略（启动时取消订单）
- `run_etf_stg5s.py` - 5倍做空策略（5%买卖价差）

### 净值计算文件
- `net_value_stg3l.py` - 3倍做多净值计算器
- `net_value_stg3s.py` - 3倍做空净值计算器
- `net_value_stg5l.py` - 5倍做多净值计算器
- `net_value_stg5s.py` - 5倍做空净值计算器

## 推荐使用方式

请使用新的统一启动方式：

### 交易策略
```bash
# 新方式（推荐）
python run_etf.py --strategy stg3l
python run_etf.py --strategy stg3s
python run_etf.py --strategy stg5l
python run_etf.py --strategy stg5s

# 或使用便捷脚本
./scripts/run_stg3l.sh
./scripts/run_stg3s.sh
./scripts/run_stg5l.sh
./scripts/run_stg5s.sh
```

### 净值计算
```bash
# 新方式（推荐）
python run_net_value.py --strategy stg3l
python run_net_value.py --strategy stg3s
python run_net_value.py --strategy stg5l
python run_net_value.py --strategy stg5s

# 或使用便捷脚本
./scripts/run_net_value_stg3l.sh
./scripts/run_net_value_stg3s.sh
./scripts/run_net_value_stg5l.sh
./scripts/run_net_value_stg5s.sh
```

## 紧急回滚

如需使用原始脚本：

### 交易策略
```bash
python legacy/run_etf_stg3l.py
python legacy/run_etf_stg3s.py
python legacy/run_etf_stg5l.py
python legacy/run_etf_stg5s.py
```

### 净值计算
```bash
python legacy/net_value_stg3l.py
python legacy/net_value_stg3s.py
python legacy/net_value_stg5l.py
python legacy/net_value_stg5s.py
```

## 注意事项

新系统完全保持了原有的：
- 所有参数值
- 策略逻辑
- 特殊行为（如 STG5S 的订单取消逻辑）
- API 密钥配置方式
