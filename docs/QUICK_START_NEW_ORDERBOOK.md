# 新订单簿系统快速启用指南

## 🚀 5分钟快速启用

### 步骤1: 修改配置文件

编辑 `config/strategies.yaml`，为你的策略添加以下配置：

```yaml
ton3s:  # 或其他策略名称
  # ... 保留现有配置 ...

  # ✨ 新增：启用新订单簿算法
  orderbook_algorithm: "natural"

  # ✨ 新增：使用推荐预设
  orderbook_preset: "medium"  # 1000 USDT, 5000档, 高自然度
```

### 步骤2: 重启交易程序

```bash
# 停止现有进程
pm2 stop etf-ton3s

# 启动新进程
pm2 start ecosystem.config.js --only etf-ton3s

# 查看日志
pm2 logs etf-ton3s
```

### 步骤3: 验证运行

在日志中应该看到：

```
📊 使用订单簿算法: natural
📊 订单簿生成完成: 2500档买盘 + 2500档卖盘, 耗时 22.72ms, 总金额 1000.00 USDT
```

**完成！** ✅ 新订单簿系统已启用

---

## 📊 预设配置对比

| 预设 | 预算 | 档位 | 自然度 | 生成时间 | 适用场景 |
|------|------|------|--------|---------|---------|
| small | 200 USDT | 1000 | medium | ~12ms | 测试环境 |
| **medium** ⭐ | 1000 USDT | 5000 | high | ~23ms | **生产推荐** |
| large | 5000 USDT | 20000 | high | ~96ms | 大账户 |
| xlarge | 50000 USDT | 100000 | ultra | ~485ms | 机构账户 |

---

## ⚙️ 自定义配置（高级）

如果预设不满足需求，可以自定义配置：

```yaml
ton3s:
  orderbook_algorithm: "natural"

  # 自定义配置（覆盖预设）
  orderbook_config:
    total_budget: 1500        # 自定义预算
    layer: 10000              # 自定义档位
    extra_params:
      naturalness: "high"     # low/medium/high/ultra
```

---

## 🔄 回退到旧系统

如果需要回退，只需删除或注释新配置：

```yaml
ton3s:
  # orderbook_algorithm: "natural"  # 注释掉
  # orderbook_preset: "medium"      # 注释掉

  # 旧配置会自动生效
  orderbook:
    min_order_value: 20.0
    layer: 30
```

---

## 📈 性能监控

### 关键指标

运行后，可以通过以下方式监控性能：

```bash
# 1. 查看订单簿生成时间（应 <100ms）
pm2 logs etf-ton3s | grep "订单簿生成完成"

# 2. 查看订单操作频率（应 <10次/分钟）
pm2 logs etf-ton3s | grep "订单操作计划" | tail -20

# 3. 查看内存占用
pm2 monit
```

### 性能告警阈值

如果出现以下情况，需要调整配置：

- ⚠️ 订单簿生成时间 >100ms → 降低档位数
- ⚠️ 内存占用 >500MB → 降低档位数或启用缓存
- ⚠️ 订单刷新频率 >10次/分钟 → 增大价格变化阈值

---

## 💡 常见问题

### Q1: 新系统和旧系统有什么区别？

**旧系统**：
- 30档固定指数分布
- 简单价格分布
- 无自然度优化

**新系统**：
- 1000-100000档可配置
- 真实盘口特征（订单墙、空洞、聚集）
- 4档自然度级别
- 更好的性能优化

### Q2: 启用新系统会影响现有交易吗？

**不会**。新系统完全向后兼容：

1. 未配置时，自动使用旧系统
2. 订单格式完全相同
3. 交易逻辑不受影响

### Q3: 如何验证新系统正常工作？

查看日志中的标志性输出：

```bash
# 新系统标志
📊 使用订单簿算法: natural
📊 订单簿生成完成: 2500档买盘 + 2500档卖盘

# 旧系统（无此输出）
目标盘口 - 卖1: {...}
```

### Q4: 性能不佳怎么办？

按以下顺序排查：

1. **降低档位数**：`layer: 5000` → `layer: 1000`
2. **降低自然度**：`naturalness: "high"` → `naturalness: "medium"`
3. **增大刷新间隔**：增加 `orderbook_refresh_interval`
4. **查看优化文档**：`docs/ORDERBOOK_PERFORMANCE_OPTIMIZATION.md`

---

## 📚 完整文档索引

1. **快速启用**（本文档）
2. **使用指南**: `docs/ORDERBOOK_USAGE.md`
3. **性能优化**: `docs/ORDERBOOK_PERFORMANCE_OPTIMIZATION.md`
4. **集成报告**: `docs/ORDERBOOK_INTEGRATION_COMPLETE.md`

---

## ✅ 快速检查清单

部署前确认：

- [ ] 配置文件已修改（添加 `orderbook_algorithm` 和 `orderbook_preset`）
- [ ] 选择了合适的预设（推荐 `medium`）
- [ ] 已重启交易程序
- [ ] 日志中看到"使用订单簿算法: natural"
- [ ] 订单簿生成时间 <100ms
- [ ] 订单操作正常（买卖单数量符合档位配置）

**全部确认？** 开始使用新订单簿系统吧！ 🎉

---

**最后更新**: 2025-11-23
**版本**: v1.0.0
