# Scripts 目录分类整理

## 🎯 分类建议

### ✅ **核心生产脚本（保留）**

#### 部署和运维
- `deploy.sh` - 生产部署脚本
- `rollback.sh` - 版本回滚
- `package.sh` - 项目打包
- `check_dependencies.sh` - 依赖检查

#### 环境设置
- `setup_uv.sh` - UV环境设置（推荐）
- `dev_start.sh` - 开发环境启动

#### 数据库管理
- `init_database.py` - PostgreSQL数据库初始化
- `init_net_value_tables.py` - 净值表初始化

#### 安全
- `encrypt_apikeys.py` - API密钥加密工具

#### 测试
- `run_tests.sh` - 测试运行脚本

---

### 🔬 **调试/分析脚本（考虑归档）**

#### 订单簿调试
- `debug_detailed.py` - 订单簿生成详细调试
- `debug_layer_loss.py` - 250档档位丢失调试
- `test_budget_range.py` - 预算范围测试
- `test_equal_value_orderbook.py` - 等价值订单簿测试
- `test_orderbook_distribution.py` - 订单簿分布测试
- `test_orderbook_performance.py` - 订单簿性能测试
- `test_ton3l_orderbook.py` - TON3L订单簿测试
- `visualize_orderbook_comparison.py` - 订单簿可视化对比

#### 数据分析
- `analyze_kline_quality.py` - K线质量分析
- `query_order_stats.py` - 订单统计查询

#### 监控工具
- `monitor_last_amount.py` - last_amount监控
- `monitor_net_value_persistence.py` - 净值持久化监控
- `start_monitor.py` - 启动实时监控

#### 配置验证
- `validate_config.py` - 配置验证

---

### ⚠️ **疑问脚本（需确认）**

- `account.sh` - **包含硬编码API密钥！安全风险！**

---

## 📊 统计

**总脚本数**: 25

- **核心生产脚本**: 10 个
- **调试/分析脚本**: 14 个
- **安全风险脚本**: 1 个

---

## 🗂️ 建议的目录结构

```
scripts/
├── production/           # 生产环境脚本
│   ├── deploy.sh
│   ├── rollback.sh
│   ├── package.sh
│   ├── check_dependencies.sh
│   ├── setup_uv.sh
│   └── dev_start.sh
│
├── database/            # 数据库管理
│   ├── init_database.py
│   └── init_net_value_tables.py
│
├── security/            # 安全工具
│   └── encrypt_apikeys.py
│
├── testing/             # 测试脚本
│   └── run_tests.sh
│
├── monitoring/          # 监控工具（生产可选）
│   ├── monitor_last_amount.py
│   ├── monitor_net_value_persistence.py
│   ├── start_monitor.py
│   └── query_order_stats.py
│
└── archived/            # 已归档（开发调试用）
    ├── debug/
    │   ├── debug_detailed.py
    │   └── debug_layer_loss.py
    │
    ├── testing/
    │   ├── test_budget_range.py
    │   ├── test_equal_value_orderbook.py
    │   ├── test_orderbook_distribution.py
    │   ├── test_orderbook_performance.py
    │   └── test_ton3l_orderbook.py
    │
    └── analysis/
        ├── analyze_kline_quality.py
        ├── visualize_orderbook_comparison.py
        └── validate_config.py
```

---

## ⚠️ 立即行动项

### 🔴 高优先级 - 安全问题

1. **删除 `account.sh`**
   - 包含明文API密钥
   - 严重安全风险
   - 建议立即删除或移到 `.gitignore`

```bash
# 建议命令
rm scripts/account.sh
# 或移到安全位置
mv scripts/account.sh ~/.local/bin/account_backup.sh
```

---

## 🟡 中优先级 - 整理归档

### 调试脚本归档
```bash
mkdir -p scripts/archived/{debug,testing,analysis}

# 移动调试脚本
mv scripts/debug_*.py scripts/archived/debug/

# 移动测试脚本
mv scripts/test_budget_range.py scripts/archived/testing/
mv scripts/test_equal_value_orderbook.py scripts/archived/testing/
mv scripts/test_orderbook_distribution.py scripts/archived/testing/
mv scripts/test_orderbook_performance.py scripts/archived/testing/
mv scripts/test_ton3l_orderbook.py scripts/archived/testing/

# 移动分析脚本
mv scripts/analyze_kline_quality.py scripts/archived/analysis/
mv scripts/visualize_orderbook_comparison.py scripts/archived/analysis/
mv scripts/validate_config.py scripts/archived/analysis/
```

---

## 🟢 低优先级 - 文档更新

1. **更新 CLAUDE.md**
   - 更新脚本路径说明
   - 添加归档脚本的访问说明

2. **添加 scripts/README.md**
   - 脚本分类说明
   - 使用指南

---

## ❓ 需要你确认的问题

1. **监控脚本**（4个）
   - `monitor_*.py` 和 `start_monitor.py`
   - 问题：这些是生产环境需要的吗？
   - 建议：
     - 如果生产使用 → 保留在 `scripts/monitoring/`
     - 如果仅开发调试 → 移到 `scripts/archived/monitoring/`

2. **配置验证**
   - `validate_config.py`
   - 问题：是否还在使用？
   - 建议：
     - 如果还在用 → 保留在 `scripts/`
     - 如果已废弃 → 移到 `scripts/archived/`

3. **订单簿测试脚本**（6个）
   - 问题：订单簿功能是否已稳定？这些测试脚本还需要经常使用吗？
   - 建议：
     - 如果功能已稳定 → 归档
     - 如果还在开发优化 → 保留

---

## 📝 推荐操作流程

### Step 1: 立即处理安全问题
```bash
# 删除或移走包含密钥的脚本
rm scripts/account.sh
```

### Step 2: 创建归档目录结构
```bash
mkdir -p scripts/archived/{debug,testing,analysis,monitoring}
```

### Step 3: 移动调试脚本（你确认后执行）
```bash
# 根据你的确认，选择性执行移动命令
# ...
```

### Step 4: 添加说明文档
```bash
# 创建 scripts/README.md 说明各脚本用途
# 更新 CLAUDE.md 中的脚本路径说明
```

---

## 💡 建议

1. **保留的核心脚本** (10个)
   - 部署、环境、数据库、安全、测试
   - 这些是生产环境必需的

2. **归档但保留的脚本** (14个)
   - 调试、分析、性能测试
   - 移到 `archived/` 但不删除，方便后续调试

3. **立即删除的脚本** (1个)
   - `account.sh` - 安全风险

**你需要确认哪些脚本要保留、归档还是删除吗？我可以帮你执行具体的整理操作！**
