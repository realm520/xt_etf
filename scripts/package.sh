#!/bin/bash
# XT ETF 项目打包脚本
# 用途: 将项目打包成可部署的 tar.gz 文件
# 使用: ./scripts/package.sh [version] [--include-tests]

set -e  # 遇到错误立即退出

# 颜色输出
RED='\033[0:31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 函数: 打印带颜色的消息
print_info() {
    echo -e "${BLUE}ℹ${NC} $1"
}

print_success() {
    echo -e "${GREEN}✓${NC} $1"
}

print_warning() {
    echo -e "${YELLOW}⚠${NC} $1"
}

print_error() {
    echo -e "${RED}✗${NC} $1"
}

# 函数: 显示帮助信息
show_help() {
    cat << EOF
XT ETF 项目打包脚本

用法:
    $0 [VERSION] [OPTIONS]

参数:
    VERSION         版本号（默认: 从 VERSION 文件读取或使用 dev）

选项:
    --include-tests 包含测试文件（默认不包含）
    --docker        创建 Docker 镜像（额外）
    --help, -h      显示此帮助信息

示例:
    $0 1.0.0                    # 打包 v1.0.0
    $0 1.0.0 --include-tests    # 打包并包含测试文件
    $0                          # 使用默认版本打包

输出:
    build/xt-etf-[VERSION].tar.gz

EOF
}

# 解析参数
VERSION=""
INCLUDE_TESTS=false
BUILD_DOCKER=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --include-tests)
            INCLUDE_TESTS=true
            shift
            ;;
        --docker)
            BUILD_DOCKER=true
            shift
            ;;
        *)
            if [ -z "$VERSION" ]; then
                VERSION=$1
            else
                print_error "未知参数: $1"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# 确定版本号
if [ -z "$VERSION" ]; then
    if [ -f "VERSION" ]; then
        VERSION=$(cat VERSION)
        print_info "从 VERSION 文件读取版本: $VERSION"
    else
        VERSION="dev-$(date +%Y%m%d%H%M%S)"
        print_warning "未指定版本号，使用: $VERSION"
    fi
fi

# 配置
PACKAGE_NAME="xt-etf-${VERSION}"
BUILD_DIR="build/${PACKAGE_NAME}"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"

print_info "📦 开始打包 XT ETF v${VERSION}..."
print_info "项目根目录: ${PROJECT_ROOT}"

# 进入项目根目录
cd "${PROJECT_ROOT}"

# 检查必需文件
print_info "检查必需文件..."
REQUIRED_FILES=("run_etf.py" "pyproject.toml" "config/strategies.yaml")
for file in "${REQUIRED_FILES[@]}"; do
    if [ ! -f "$file" ]; then
        print_error "缺少必需文件: $file"
        exit 1
    fi
done
print_success "必需文件检查通过"

# 清理并创建构建目录
print_info "创建构建目录..."
rm -rf build/
mkdir -p "${BUILD_DIR}"

# 复制核心文件
print_info "复制核心代码..."

# 核心Python模块
for dir in binance etf; do
    if [ -d "$dir" ]; then
        print_info "  复制 $dir/..."
        rsync -a --exclude='__pycache__' --exclude='*.pyc' "$dir/" "${BUILD_DIR}/$dir/"
    fi
done

# 配置文件
print_info "  复制配置文件..."
mkdir -p "${BUILD_DIR}/config"
cp config/strategies.yaml "${BUILD_DIR}/config/"
if [ -f "config/observability.yaml" ]; then
    cp config/observability.yaml "${BUILD_DIR}/config/"
fi

# 脚本目录
print_info "  复制脚本..."
mkdir -p "${BUILD_DIR}/scripts"
rsync -a --exclude='local_*' --exclude='dev_*' scripts/ "${BUILD_DIR}/scripts/"
chmod +x "${BUILD_DIR}"/scripts/*.sh

# 主入口文件
print_info "  复制主入口文件..."
for file in run_etf.py run_net_value.py hedging*.py; do
    if [ -f "$file" ]; then
        cp "$file" "${BUILD_DIR}/"
    fi
done

# 项目配置文件
print_info "  复制项目配置..."
cp pyproject.toml "${BUILD_DIR}/"
if [ -f "setup.py" ]; then
    cp setup.py "${BUILD_DIR}/"
fi

# PM2 配置
if [ -f "ecosystem.config.js" ]; then
    print_info "  复制 PM2 配置..."
    cp ecosystem.config.js "${BUILD_DIR}/ecosystem.config.js.template"
fi

# 文档
print_info "  复制文档..."
mkdir -p "${BUILD_DIR}/docs"
for doc in README.md CLAUDE.md LICENSE; do
    if [ -f "$doc" ]; then
        cp "$doc" "${BUILD_DIR}/"
    fi
done

# 关键文档
for doc in docs/DEPLOYMENT_GUIDE.md docs/USER_GUIDE.md docs/TROUBLESHOOTING.md \
           docs/API_KEY_SECURITY.md docs/PACKAGING_DEPLOYMENT.md; do
    if [ -f "$doc" ]; then
        cp "$doc" "${BUILD_DIR}/docs/"
    fi
done

# 测试文件（可选）
if [ "$INCLUDE_TESTS" = true ]; then
    print_info "  包含测试文件..."
    if [ -d "tests" ]; then
        rsync -a --exclude='__pycache__' --exclude='*.pyc' tests/ "${BUILD_DIR}/tests/"
    fi
fi

# 配置模板
print_info "创建配置模板..."
if [ -f ".env.example" ]; then
    cp .env.example "${BUILD_DIR}/.env.example"
else
    print_warning ".env.example 不存在，跳过"
fi

if [ -f "APIKey_template.json" ]; then
    cp APIKey_template.json "${BUILD_DIR}/"
else
    print_warning "APIKey_template.json 不存在，跳过"
fi

# 创建必需目录
print_info "创建必需目录..."
mkdir -p "${BUILD_DIR}"/{logs,data,backups}
touch "${BUILD_DIR}/logs/.gitkeep"
touch "${BUILD_DIR}/data/.gitkeep"
touch "${BUILD_DIR}/backups/.gitkeep"

# 创建版本信息
print_info "生成版本信息..."
echo "${VERSION}" > "${BUILD_DIR}/VERSION"

if command -v git &> /dev/null && [ -d ".git" ]; then
    git rev-parse HEAD > "${BUILD_DIR}/GIT_COMMIT" 2>/dev/null || echo "unknown" > "${BUILD_DIR}/GIT_COMMIT"
    git describe --tags --always > "${BUILD_DIR}/GIT_TAG" 2>/dev/null || echo "unknown" > "${BUILD_DIR}/GIT_TAG"
else
    echo "unknown" > "${BUILD_DIR}/GIT_COMMIT"
    echo "unknown" > "${BUILD_DIR}/GIT_TAG"
fi

date -u +"%Y-%m-%d %H:%M:%S UTC" > "${BUILD_DIR}/BUILD_TIME"

# 创建快速部署说明
print_info "生成部署说明..."
cat > "${BUILD_DIR}/QUICK_DEPLOY.md" << 'EOF'
# XT ETF 快速部署指南

## 部署步骤

### 1. 解压文件
```bash
tar -xzf xt-etf-*.tar.gz
cd xt-etf-*
```

### 2. 检查依赖
```bash
./scripts/check_dependencies.sh
```

### 3. 设置环境
```bash
# 安装 Python 依赖
./scripts/setup_uv.sh

# 或使用传统方式
python3 -m venv .venv
source .venv/bin/activate
pip install -e .
```

### 4. 配置系统
```bash
# 复制环境变量配置
cp .env.example .env
vim .env  # 填写实际配置

# 配置 API 密钥
cp APIKey_template.json APIKey.json
vim APIKey.json  # 填写实际密钥

# 或使用加密密钥（推荐）
export ETF_KEY_PASSWORD='your-secure-password'
python scripts/encrypt_apikeys.py

# 配置 PM2
cp ecosystem.config.js.template ecosystem.config.js
vim ecosystem.config.js  # 修改 cwd 路径
```

### 5. 启动服务
```bash
# 使用 PM2（推荐）
pm2 start ecosystem.config.js
pm2 save
pm2 startup  # 设置开机启动

# 或直接运行
python run_etf.py --strategy stg3l
```

### 6. 验证运行
```bash
# 检查进程状态
pm2 status

# 查看日志
pm2 logs etf-stg3l

# 检查 Redis 连接
redis-cli ping
```

## 系统要求

- **操作系统**: Ubuntu 20.04+ / CentOS 8+ / Debian 11+
- **Python**: 3.11+
- **Redis**: 6.x+
- **Node.js**: 18.x+ (如使用 PM2)
- **内存**: 最小 4GB，推荐 8GB+
- **存储**: 最小 20GB，推荐 50GB+ SSD

## 重要提示

1. **密钥安全**: 切勿将 APIKey.json 提交到版本控制
2. **环境隔离**: 生产环境使用加密密钥存储
3. **定期备份**: 配置自动备份 Redis 和配置文件
4. **监控告警**: 启用日志和监控系统
5. **防火墙**: 仅开放必需端口

## 详细文档

- 完整部署指南: `docs/DEPLOYMENT_GUIDE.md`
- 打包部署说明: `docs/PACKAGING_DEPLOYMENT.md`
- 故障排查: `docs/TROUBLESHOOTING.md`
- API密钥安全: `docs/API_KEY_SECURITY.md`

## 获取帮助

- 项目文档: `CLAUDE.md`
- 用户指南: `docs/USER_GUIDE.md`
- GitHub Issues: (项目仓库地址)
EOF

# 创建 manifest 文件
print_info "生成文件清单..."
cat > "${BUILD_DIR}/MANIFEST.txt" << EOF
XT ETF 项目打包清单
====================

版本: ${VERSION}
打包时间: $(date -u +"%Y-%m-%d %H:%M:%S UTC")
打包机器: $(hostname)

核心文件:
  ✓ run_etf.py
  ✓ run_net_value.py
  ✓ pyproject.toml
  ✓ config/strategies.yaml

模块:
  ✓ binance/
  ✓ etf/

脚本:
  ✓ scripts/

文档:
  ✓ docs/
  ✓ README.md
  ✓ CLAUDE.md

配置模板:
  ✓ .env.example
  ✓ ecosystem.config.js.template
  $([ -f "APIKey_template.json" ] && echo "✓" || echo "⚠") APIKey_template.json

测试:
  $([ "$INCLUDE_TESTS" = true ] && echo "✓ tests/" || echo "✗ 未包含")

文件统计:
$(find "${BUILD_DIR}" -type f | wc -l) 个文件
$(du -sh "${BUILD_DIR}" | cut -f1) 总大小
EOF

# 计算文件统计
print_info "统计文件..."
FILE_COUNT=$(find "${BUILD_DIR}" -type f | wc -l)
DIR_SIZE=$(du -sh "${BUILD_DIR}" | cut -f1)
print_success "包含 ${FILE_COUNT} 个文件，总大小 ${DIR_SIZE}"

# 创建 tar.gz 压缩包
print_info "创建压缩包..."
cd build/
tar -czf "${PACKAGE_NAME}.tar.gz" "${PACKAGE_NAME}/"

# 生成校验和
print_info "生成校验和..."
shasum -a 256 "${PACKAGE_NAME}.tar.gz" > "${PACKAGE_NAME}.tar.gz.sha256"

# 清理临时目录（可选）
# rm -rf "${PACKAGE_NAME}/"

cd "${PROJECT_ROOT}"

# 显示结果
PACKAGE_PATH="build/${PACKAGE_NAME}.tar.gz"
PACKAGE_SIZE=$(du -h "${PACKAGE_PATH}" | cut -f1)

print_success "✅ 打包完成！"
echo ""
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "📦 打包信息"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "版本:     ${VERSION}"
echo "文件:     ${PACKAGE_PATH}"
echo "大小:     ${PACKAGE_SIZE}"
echo "校验和:   ${PACKAGE_PATH}.sha256"
echo ""
echo "📂 解压命令:"
echo "   tar -xzf ${PACKAGE_NAME}.tar.gz"
echo ""
echo "🚀 部署命令:"
echo "   ./scripts/deploy.sh <server> <user>"
echo ""
echo "📖 查看部署说明:"
echo "   tar -xzf ${PACKAGE_NAME}.tar.gz"
echo "   cat ${PACKAGE_NAME}/QUICK_DEPLOY.md"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# Docker 构建（可选）
if [ "$BUILD_DOCKER" = true ]; then
    print_info "🐳 构建 Docker 镜像..."
    if command -v docker &> /dev/null; then
        docker build -t "xt-etf:${VERSION}" -t "xt-etf:latest" .
        print_success "Docker 镜像构建完成: xt-etf:${VERSION}"
    else
        print_warning "Docker 未安装，跳过镜像构建"
    fi
fi

print_success "🎉 所有任务完成！"
