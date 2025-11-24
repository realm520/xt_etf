# TON3L 新订单簿系统使用指南

## 配置说明

**当前配置**: `config/strategies.yaml` 中的 `ton3l` 策略

```yaml
ton3l:
  # ... 其他配置 ...

  # 新订单簿算法配置（已启用）
  orderbook_algorithm: "natural"     # 使用自然盘口算法
  orderbook_config:
    total_budget: 10000.0            # 总预算 10000 USDT
    layer: 500                       # 总档位500（买250 + 卖250，对称）
    extra_params:
      naturalness: "high"            # 高自然度（95%真实性）
```

## 配置参数说明

### 核心参数

| 参数 | 值 | 说明 |
|------|-----|------|
| `total_budget` | 10000.0 | 总预算（USDT），买卖双方各分一半 |
| `layer` | 500 | **总档位数**（买250 + 卖250） |
| `naturalness` | high | 自然度级别（low/medium/high/ultra） |

### 重要提示

⚠️ **档位参数说明**: `layer` 表示**总档位数**，不是单边档位数！

- `layer: 500` → 买盘250档 + 卖盘250档 = 总共500档 ✅
- `layer: 250` → 买盘125档 + 卖盘125档 = 总共250档 ❌

## 验证测试

已通过完整测试验证：

```bash
uv run python scripts/test_ton3l_orderbook.py
```

### 测试结果

✅ **总档位**: 500档（买250 + 卖250）
✅ **买卖对称**: 档位差异 0
✅ **预算精度**: 偏差 0.00%（实际 10000.06 USDT）
✅ **性能达标**: 生成时间 ~10ms

## 运行方式

### 方式1: 直接运行（测试）

```bash
python run_etf.py --strategy ton3l --env qa
```

### 方式2: PM2生产部署

```bash
pm2 start ecosystem.config.js --only etf-ton3l
pm2 logs etf-ton3l
```

## 预期效果

启动后，日志中应该看到：

```
📊 使用订单簿算法: natural
📊 订单簿生成完成: 250档买盘 + 250档卖盘, 耗时 ~10ms, 总金额 10000.00 USDT
```

## 自定义配置

如需调整参数，修改 `config/strategies.yaml` 中的配置：

### 调整预算

```yaml
orderbook_config:
  total_budget: 20000.0  # 增加到 20000 USDT
```

### 调整档位数（保持不超过600档）

```yaml
orderbook_config:
  layer: 600  # 总档位600（买300 + 卖300）
```

### 调整自然度

```yaml
extra_params:
  naturalness: "ultra"  # 最高真实性（98%）
```

## 性能基准

| 总档位 | 生成时间 | 内存占用 | 适用场景 |
|--------|---------|---------|----------|
| 500档 | ~10ms | <20MB | **生产推荐** ⭐ |
| 600档 | ~12ms | <25MB | 最大配置 |
| 1000档 | ~20ms | <40MB | 备选方案 |

## 常见问题

### Q1: 如何验证新系统是否生效？

查看日志中是否有 "使用订单簿算法: natural" 输出。

### Q2: 如何回退到旧系统？

注释掉或删除 `orderbook_algorithm` 和 `orderbook_config` 配置即可：

```yaml
# orderbook_algorithm: "natural"
# orderbook_config:
#   total_budget: 10000.0
#   layer: 500
```

### Q3: 档位数为什么和配置不一致？

请检查 `layer` 参数是否正确理解：
- `layer: 500` → 总共500档 ✅
- `layer: 250` → 总共250档（不是单边250档）❌

## 技术支持

- **测试脚本**: `scripts/test_ton3l_orderbook.py`
- **性能测试**: `scripts/test_orderbook_performance.py`
- **预算测试**: `scripts/test_budget_range.py`
- **详细文档**: `docs/ORDERBOOK_INTEGRATION_COMPLETE.md`

---

**更新日期**: 2025-11-23
**版本**: v1.0.0
**状态**: ✅ 生产就绪
