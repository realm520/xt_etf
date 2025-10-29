#!/bin/bash
# XT ETF 依赖检查脚本
# 用途: 检查部署环境是否满足要求
# 使用: ./scripts/check_dependencies.sh

set -e

GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }

ERRORS=0
WARNINGS=0

print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "🔍 XT ETF 环境依赖检查"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 检查操作系统
print_info "1️⃣  操作系统检查..."
if [[ "$OSTYPE" == "linux-gnu"* ]]; then
    print_success "操作系统: Linux"
elif [[ "$OSTYPE" == "darwin"* ]]; then
    print_warning "操作系统: macOS (生产环境推荐使用Linux)"
    WARNINGS=$((WARNINGS+1))
else
    print_error "不支持的操作系统: $OSTYPE"
    ERRORS=$((ERRORS+1))
fi

# 检查Python
print_info "2️⃣  Python环境检查..."
if command -v python3 &> /dev/null; then
    PY_VERSION=$(python3 --version | cut -d' ' -f2)
    print_success "Python: $PY_VERSION"
    if [[ "$PY_VERSION" < "3.8" ]]; then
        print_error "Python版本过低，需要3.8+（推荐3.11）"
        ERRORS=$((ERRORS+1))
    fi
else
    print_error "Python3未安装"
    ERRORS=$((ERRORS+1))
fi

# 检查Redis
print_info "3️⃣  Redis检查..."
if command -v redis-cli &> /dev/null; then
    if redis-cli ping &>/dev/null; then
        REDIS_VERSION=$(redis-cli --version | awk '{print $2}')
        print_success "Redis: $REDIS_VERSION (运行中)"
    else
        print_error "Redis未运行"
        ERRORS=$((ERRORS+1))
    fi
else
    print_error "Redis未安装"
    ERRORS=$((ERRORS+1))
fi

# 检查Node.js和PM2
print_info "4️⃣  Node.js和PM2检查..."
if command -v node &> /dev/null; then
    NODE_VERSION=$(node --version)
    print_success "Node.js: $NODE_VERSION"
else
    print_warning "Node.js未安装（PM2需要）"
    WARNINGS=$((WARNINGS+1))
fi

if command -v pm2 &> /dev/null; then
    PM2_VERSION=$(pm2 --version)
    print_success "PM2: $PM2_VERSION"
else
    print_warning "PM2未安装（推荐用于生产环境）"
    WARNINGS=$((WARNINGS+1))
fi

# 检查磁盘空间
print_info "5️⃣  磁盘空间检查..."
DISK_FREE=$(df -h . | awk 'NR==2 {print $4}')
print_info "可用空间: $DISK_FREE"

# 检查内存
print_info "6️⃣  内存检查..."
if command -v free &> /dev/null; then
    MEM_FREE=$(free -h | awk 'NR==2 {print $7}')
    print_info "可用内存: $MEM_FREE"
fi

# 总结
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ $ERRORS -eq 0 ]; then
    print_success "✅ 所有必需依赖检查通过！"
    if [ $WARNINGS -gt 0 ]; then
        print_warning "⚠️  有 $WARNINGS 个警告，请检查"
    fi
    exit 0
else
    print_error "❌ 发现 $ERRORS 个错误"
    print_info "请安装缺失的依赖后再继续"
    exit 1
fi
