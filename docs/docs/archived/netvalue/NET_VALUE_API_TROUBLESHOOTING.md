# ETF净值推送API故障排查文档

## 📋 当前状态

### ✅ 已完成
- API接口封装（`etf/xt.py`）
- 测试工具（`scripts/test_update_net_worth.py`）
- 密钥加载（支持.env和策略配置）
- 请求签名和认证

### ❌ 遇到问题
- **错误代码**: 502 Bad Gateway
- **请求路径**: `PUT /v4/etf/net-worth`
- **环境**: QA (https://sapi.xt-qa2.com)

## 🔍 502错误分析

### 错误详情
```
502 Server Error: Bad Gateway for url: https://sapi.xt-qa2.com/v4/etf/net-worth
```

### 可能原因

#### 1. **接口路径错误** (可能性: 🔴 高)
当前使用: `/v4/etf/net-worth`

**可能的正确路径**:
- `/v4/etf/networth` (无连字符)
- `/v4/etf/net-value`
- `/v4/etf/update-net-worth`
- 其他自定义路径

**需要确认**: XT提供的接口文档中的准确路径

#### 2. **QA环境未部署** (可能性: 🟡 中)
- QA环境可能只部署了部分API
- 该接口可能只在生产环境可用
- 需要确认接口在哪些环境可用

#### 3. **权限不足** (可能性: 🟢 低)
- API密钥缺少ETF净值更新权限
- 通常会返回401/403而非502
- 但不排除XT的特殊处理

#### 4. **服务暂时不可用** (可能性: 🟢 低)
- QA环境服务重启
- 临时维护
- 可以稍后重试

## 🧪 排查步骤

### Step 1: 确认接口路径

联系XT技术支持，确认：
1. 接口的准确路径
2. 请求方法（PUT/POST）
3. 请求体格式

**参考curl**:
```bash
curl --location --request PUT 'https://sapi.xt-qa2.com/v4/etf/net-worth' \
--header 'accept: */*' \
--header 'Content-Type: application/json' \
--header 'validate-algorithms: HmacSHA256' \
--header 'validate-recvwindow: 60000' \
--header 'validate-appkey: xxx' \
--header 'validate-timestamp: xxx' \
--header 'validate-signature: xxx' \
--data '{
    "symbol": "TON3L_USDT",
    "netWorth": 1.0234
}'
```

### Step 2: 测试不同路径

如果XT确认了接口路径，修改 `etf/xt.py:669`:

```python
# 当前代码
res = self.req_put(url='/v4/etf/net-worth', params=params, auth=True)

# 尝试其他路径
res = self.req_put(url='/v4/etf/networth', params=params, auth=True)  # 无连字符
res = self.req_put(url='/v4/etf/net-value', params=params, auth=True)  # 使用value
```

### Step 3: 测试生产环境

```bash
# 谨慎：生产环境测试可能会影响实际数据
python scripts/test_update_net_worth.py \
    --symbol TON3L_USDT \
    --net-worth 1.0 \
    --env prod
```

### Step 4: 检查API权限

确认API密钥具有以下权限：
- ✅ 查询权限（已验证，可以获取深度数据）
- ❓ ETF净值更新权限
- ❓ ETF管理权限

### Step 5: 使用Postman/curl直接测试

使用提供的curl命令直接测试，排除代码问题：

```bash
# 生成签名
python -c "
import time
import hashlib
import hmac
import json

access_key = 'your_access_key'
secret_key = 'your_secret_key'
timestamp = str(int(time.time() * 1000))

headers = {
    'validate-timestamp': timestamp,
    'validate-appkey': access_key,
    'validate-recvwindow': '60000',
    'validate-algorithms': 'HmacSHA256'
}

body = {'symbol': 'TON3L_USDT', 'netWorth': 1.0234}
body_str = json.dumps(body)

# 签名计算
x = '&'.join([f'{k}={v}' for k, v in sorted(headers.items())])
y = f'#PUT#/v4/etf/net-worth##' + body_str
sign_str = x + y
signature = hmac.new(secret_key.encode(), sign_str.encode(), hashlib.sha256).hexdigest().upper()

print(f'Signature: {signature}')
print(f'Timestamp: {timestamp}')
"

# 使用生成的签名测试
curl -X PUT 'https://sapi.xt-qa2.com/v4/etf/net-worth' \
  -H 'Content-Type: application/json' \
  -H 'validate-algorithms: HmacSHA256' \
  -H 'validate-recvwindow: 60000' \
  -H 'validate-appkey: your_access_key' \
  -H 'validate-timestamp: generated_timestamp' \
  -H 'validate-signature: generated_signature' \
  -d '{"symbol":"TON3L_USDT","netWorth":1.0234}'
```

## 📝 需要向XT确认的问题

1. **接口路径**
   - 准确的URL路径是什么？
   - 是 `/v4/etf/net-worth` 还是其他？

2. **环境可用性**
   - 该接口在QA环境是否可用？
   - 还是只在生产环境部署？

3. **权限要求**
   - 需要哪些API权限？
   - 当前密钥是否已授权？

4. **请求格式**
   - 请求体字段是否正确？
   - 是 `netWorth` 还是 `net_worth` 或其他？

5. **Symbol格式**
   - 是 `TON3L_USDT` 还是 `ton3l_usdt`？
   - 是否需要特定格式？

6. **响应格式**
   - 成功时的响应格式是什么？
   - 是否有特殊的错误码？

## 🔧 临时解决方案

在XT确认接口可用之前，可以：

### 方案1: 仅本地计算和存储
```python
# 净值只存储在Redis，不推送到交易所
# 做市商从Redis读取净值进行定价
net_value_calculator.run()  # 只计算和存储
```

### 方案2: 使用Mock接口测试
```python
# 创建Mock服务器用于本地测试
# scripts/mock_xt_server.py
from flask import Flask, request
app = Flask(__name__)

@app.route('/v4/etf/net-worth', methods=['PUT'])
def update_net_worth():
    data = request.json
    return {'rc': 0, 'mc': 'SUCCESS', 'result': data}

if __name__ == '__main__':
    app.run(port=8080)
```

### 方案3: 延迟推送功能
```python
# 在配置中禁用推送功能
enable_push_to_exchange: false

# 等XT接口就绪后再启用
enable_push_to_exchange: true
```

## 📊 错误码参考

| 错误码 | 含义 | 可能原因 |
|--------|------|---------|
| 502 | Bad Gateway | 接口路径错误、服务未部署、上游服务故障 |
| 401 | Unauthorized | 认证失败、密钥无效 |
| 403 | Forbidden | 权限不足 |
| 404 | Not Found | 路径不存在 |
| 500 | Internal Server Error | 服务器内部错误 |

## 🎯 下一步行动

1. **联系XT技术支持**
   - 提供当前的请求详情
   - 确认接口路径和格式
   - 获取接口文档

2. **更新代码**（如果路径确认有误）
   ```python
   # etf/xt.py:669
   res = self.req_put(url='/v4/etf/正确的路径', params=params, auth=True)
   ```

3. **重新测试**
   ```bash
   python scripts/test_update_net_worth.py --symbol TON3L_USDT --net-worth 1.0234
   ```

4. **文档更新**
   - 更新API文档
   - 补充接口说明
   - 记录注意事项

## 📚 相关资源

- [XT API文档](https://xt-com.github.io/xt4-api/)
- [净值推送集成文档](./NET_VALUE_PUSH_INTEGRATION.md)
- [测试脚本](../scripts/test_update_net_worth.py)
- [XT客户端实现](../etf/xt.py)

---

**更新日期**: 2025-11-20
**状态**: 等待XT确认接口路径和环境可用性
