# uv 使用指南

## 快速开始

### 1. 安装 uv
```bash
# macOS/Linux
curl -LsSf https://astral.sh/uv/install.sh | sh

# 或使用 pip
pip install uv
```

### 2. 设置项目环境
```bash
# 运行自动设置脚本
./scripts/setup_uv.sh

# 或手动设置
uv venv --python 3.11
source .venv/bin/activate
uv pip install -e .
uv pip install -e ".[dev]"
```

## 常用命令

### 虚拟环境管理
```bash
# 创建虚拟环境
uv venv --python 3.11

# 激活虚拟环境
source .venv/bin/activate  # Linux/macOS
.venv\Scripts\activate     # Windows

# 删除虚拟环境
rm -rf .venv
```

### 依赖管理
```bash
# 安装项目（开发模式）
uv pip install -e .

# 安装包含开发依赖
uv pip install -e ".[dev]"

# 安装单个包
uv pip install package-name

# 查看已安装的包
uv pip list
```

### 项目管理
```bash
# 同步项目依赖（根据 pyproject.toml）
uv pip sync

# 升级所有包
uv pip install --upgrade-all

# 卸载包
uv pip uninstall package-name
```

## 与传统 pip 的区别

1. **速度提升**: uv 比传统 pip 快 10-100 倍
2. **缓存优化**: 智能缓存减少重复下载
3. **并行安装**: 自动并行处理依赖
4. **内存效率**: 更低的内存占用

## 配置说明

项目的 uv 配置位于 `pyproject.toml` 的 `[tool.uv]` 部分：

```toml
[tool.uv]
# Python 版本管理
managed = true
python-preference = "system"

# 开发依赖
dev-dependencies = [
    "pytest>=6.0",
    "ruff",
    "pyright",
    # ...
]
```

## 故障排除

### 常见问题

1. **虚拟环境激活失败**
   - 确保使用正确的激活命令
   - 检查 .venv 目录是否存在

2. **依赖安装失败**
   - 清理缓存: `uv cache clean`
   - 使用 --no-cache 选项重试

3. **Python 版本问题**
   - 确保系统安装了指定的 Python 版本
   - 使用 `uv python list` 查看可用版本

## 进阶用法

### 使用私有包索引
```bash
uv pip install --index-url https://private.pypi.org/simple/ package-name
```

### 离线模式
```bash
uv pip install --offline package-name
```

### 详细输出
```bash
uv pip install -v package-name  # 详细模式
uv pip install -vv package-name # 更详细
```
