# ETF净值推送到交易所集成文档

## 📋 概述

本文档说明如何将计算的ETF净值推送到XT交易所，使交易所能够展示实时净值信息。

## 🔧 已实现的功能

### 1. API接口封装 (`etf/xt.py`)

#### 新增方法

```python
def req_put(self, url, params=None, auth=None):
    """PUT请求方法，支持JSON数据"""
    # 支持PUT方法的通用请求封装
```

```python
def update_etf_net_worth(self, symbol: str, net_worth: float) -> dict:
    """
    推送ETF净值到交易所

    参数:
        symbol: ETF交易对符号，如 "TON3L_USDT", "STG3L_USDT"
        net_worth: 净值（必须大于0）

    返回:
        {'rc': 0, 'mc': 'SUCCESS', 'result': {...}}
    """
```

#### API规格

- **端点**: `PUT /v4/etf/net-worth`
- **认证**: 需要XT API密钥和签名
- **请求体**:
  ```json
  {
    "symbol": "TON3L_USDT",
    "netWorth": 1.0234
  }
  ```
- **响应**:
  ```json
  {
    "rc": 0,
    "mc": "SUCCESS",
    "ma": [],
    "result": {...}
  }
  ```

### 2. 测试脚本 (`scripts/test_update_net_worth.py`)

快速测试净值推送功能：

```bash
# QA环境测试
python scripts/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0234

# 生产环境测试
python scripts/test_update_net_worth.py --symbol STG3L_USDT --net-worth 0.9876 --env prod
```

## 🚀 集成到净值计算器

### 方案1: 修改 `ImprovedNetValue` 类（推荐）

在 `etf/net_value_improved.py` 中添加推送功能：

```python
class ImprovedNetValue:
    def __init__(
        self,
        symbol: str,
        m_lever: int,
        # ... 其他参数 ...
        enable_push_to_exchange: bool = False,  # 是否推送到交易所
        push_interval: int = 60,  # 推送间隔（秒）
    ):
        self.enable_push_to_exchange = enable_push_to_exchange
        self.push_interval = push_interval
        self.last_push_time = 0

        # 如果启用推送，创建认证客户端
        if self.enable_push_to_exchange:
            # 需要加载API密钥
            import json
            with open("APIKey.json", "r") as f:
                api_key = json.load(f)

            self.push_client = Spot(
                host="https://sapi.xt-qa2.com",  # 或从配置读取
                access_key=api_key["access_key"],
                secret_key=api_key["secret_key"],
            )

    def _push_to_exchange(self, net_value: float):
        """推送净值到交易所"""
        if not self.enable_push_to_exchange:
            return

        current_time = time.time()
        if current_time - self.last_push_time < self.push_interval:
            return  # 未到推送间隔

        try:
            # 转换symbol格式: ton_usdt -> TON3L_USDT
            etf_symbol = self._convert_to_etf_symbol(self.symbol, self.m_lever, self.long)

            result = self.push_client.update_etf_net_worth(
                symbol=etf_symbol,
                net_worth=net_value
            )

            logger.info(f"成功推送净值到交易所: {etf_symbol} = {net_value}")
            self.last_push_time = current_time

        except Exception as e:
            logger.error(f"推送净值到交易所失败: {e}", exc_info=True)

    def _convert_to_etf_symbol(self, base_symbol: str, leverage: int, is_long: bool) -> str:
        """转换symbol格式: ton_usdt -> TON3L_USDT"""
        base = base_symbol.split("_")[0].upper()  # ton -> TON
        direction = "L" if is_long else "S"
        return f"{base}{leverage}{direction}_USDT"

    def run(self):
        """主运行循环"""
        while True:
            # ... 现有净值计算代码 ...

            net_value_after_fee = self.cal_fee(net_value)

            # 更新数据
            self.net_value_data.update({...})

            # 保存到Redis
            self._save_to_redis(self.net_value_data)

            # 🆕 推送到交易所
            self._push_to_exchange(net_value_after_fee)

            # ... 其余代码 ...
```

### 方案2: 独立推送服务

创建独立的净值推送服务 `scripts/push_net_value_service.py`：

```python
#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
ETF净值推送服务
从Redis读取净值，定期推送到交易所
"""

import time
import redis
import json
from etf.xt import Spot

def main():
    # 配置
    strategies = {
        "ton3l": {"symbol": "TON3L_USDT", "redis_key": "netvalue_ton3l"},
        "stg3l": {"symbol": "STG3L_USDT", "redis_key": "netvalue_stg3l"},
        "stg3s": {"symbol": "STG3S_USDT", "redis_key": "netvalue_stg3s"},
        "stg5l": {"symbol": "STG5L_USDT", "redis_key": "netvalue_stg5l"},
        "stg5s": {"symbol": "STG5S_USDT", "redis_key": "netvalue_stg5s"},
    }

    # Redis连接
    r = redis.Redis(host="localhost", port=6379, db=0, decode_responses=True)

    # XT客户端
    with open("APIKey.json", "r") as f:
        api_key = json.load(f)

    client = Spot(
        host="https://sapi.xt-qa2.com",
        access_key=api_key["access_key"],
        secret_key=api_key["secret_key"],
    )

    print("🚀 净值推送服务启动")

    while True:
        for strategy_name, config in strategies.items():
            try:
                # 从Redis读取净值
                net_value = r.get(config["redis_key"])
                if not net_value:
                    print(f"⚠️  {strategy_name}: Redis中没有净值数据")
                    continue

                net_value = float(net_value)

                # 推送到交易所
                result = client.update_etf_net_worth(
                    symbol=config["symbol"],
                    net_worth=net_value
                )

                print(f"✅ {strategy_name}: {config['symbol']} = {net_value}")

            except Exception as e:
                print(f"❌ {strategy_name}: 推送失败 - {e}")

        # 每60秒推送一次
        time.sleep(60)

if __name__ == "__main__":
    main()
```

## 📊 配置参数

在 `config/strategies.yaml` 中添加推送配置：

```yaml
strategies:
  ton3l:
    # ... 现有配置 ...

    # 净值推送配置
    net_value_push:
      enabled: true              # 是否启用推送
      interval: 60               # 推送间隔（秒）
      retry_count: 3             # 失败重试次数
      retry_delay: 5             # 重试延迟（秒）
```

## 🔐 安全考虑

1. **API密钥管理**
   - 使用独立的API密钥用于净值推送
   - 确保密钥具有最小权限（只需要ETF净值更新权限）

2. **推送频率控制**
   - 建议推送间隔 ≥ 60秒，避免频繁请求
   - 实施重试机制，但避免无限重试

3. **异常处理**
   - 推送失败不应影响净值计算
   - 记录所有推送失败的情况，便于排查

## 📈 监控指标

建议监控以下指标：

- **推送成功率**: 成功推送次数 / 总推送次数
- **推送延迟**: 净值计算时间 - 推送确认时间
- **推送失败原因**: 网络错误、认证错误、业务错误等分类统计

## 🧪 测试步骤

### 1. 单元测试

```bash
# 测试API接口
python scripts/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0
```

### 2. 集成测试

```bash
# 启动净值计算器（启用推送）
python run_net_value.py --strategy ton3l --enable-push

# 监控Redis和交易所，验证净值同步
watch -n 5 'redis-cli GET netvalue_ton3l'
```

### 3. 压力测试

```bash
# 测试推送频率限制
for i in {1..10}; do
    python scripts/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.$i
    sleep 1
done
```

## 🚦 部署建议

### 开发环境
- 推送到QA环境 (`https://sapi.xt-qa2.com`)
- 推送间隔: 10-30秒

### 生产环境
- 推送到生产环境 (`https://sapi.xt.com`)
- 推送间隔: 60秒
- 启用失败告警
- 定期检查推送成功率

## 📚 相关文档

- [XT API文档](https://xt-com.github.io/xt4-api/)
- [净值计算器文档](../CLAUDE.md)
- [风险控制系统](./RISK_CONTROL_IMPLEMENTATION.md)
