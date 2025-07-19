# ETF 策略启动脚本

## 安装依赖

```bash
pip install pyyaml
```

## 使用方法

### 新的统一启动方式

1. **使用策略模式启动**（推荐）：
   ```bash
   python run_etf.py --strategy stg3l  # 3倍做多
   python run_etf.py --strategy stg3s  # 3倍做空
   python run_etf.py --strategy stg5l  # 5倍做多
   python run_etf.py --strategy stg5s  # 5倍做空
   ```

2. **使用便捷脚本**：
   ```bash
   ./scripts/run_stg3l.sh
   ./scripts/run_stg3s.sh
   ./scripts/run_stg5l.sh
   ./scripts/run_stg5s.sh
   ```对比原启动方式：
   # 原始方式（仍然可用）
   python run_etf_stg3l.py
   python run_etf_stg3s.py
   python run_etf_stg5l.py
   python run_etf_stg5s.py
   ```

### 命令行参数覆盖

使用策略模式时，仍然可以通过命令行参数覆盖配置：

```bash
# 覆盖买卖价差
python run_etf.py --strategy stg3l --bid-ask-spread 0.02

# 覆盖洗盘间隔
python run_etf.py --strategy stg3s --washing-interval 3

# 使用测试环境
python run_etf.py --strategy stg5l --env qa
```

### 验证配置

运行验证脚本确保新旧配置一致：

```bash
python scripts/validate_config.py
```

## 策略特点

| 策略 | 杠杆 | 方向 | 主循环间隔 | 洗盘间隔 | 买卖价差 | 特殊行为 |
|------|------|------|-----------|---------|---------|----------|
| STG3L | 3x | 做多 | 5秒 | 5秒 | 1% | - |
| STG3S | 3x | 做空 | 1秒 | 1秒 | 1% | - |
| STG5L | 5x | 做多 | 1秒 | 1秒 | 1% | 启动时取消所有订单 |
| STG5S | 5x | 做空 | 1秒 | 1秒 | 5% | 特殊的订单取消逻辑 |

## 注意事项

1. 新的策略模式完全保持了原有的参数值和行为
2. STG5S 的特殊订单取消逻辑已在代码中处理
3. 使用策略模式时会初始化余额（与单独文件行为一致）
4. 所有 API 密钥配置保持不变