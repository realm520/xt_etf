#!/bin/bash
# XT ETF 项目回滚脚本
# 用途: 快速回滚到之前的版本
# 使用: ./scripts/rollback.sh [backup_path]

set -e

# 颜色输出
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

print_info() { echo -e "${BLUE}ℹ${NC} $1"; }
print_success() { echo -e "${GREEN}✓${NC} $1"; }
print_warning() { echo -e "${YELLOW}⚠${NC} $1"; }
print_error() { echo -e "${RED}✗${NC} $1"; }

# 函数: 显示帮助
show_help() {
    cat << EOF
XT ETF 项目回滚脚本

用法:
    $0 [BACKUP_PATH] [OPTIONS]

参数:
    BACKUP_PATH     备份路径（默认: 最新备份）

选项:
    --list          列出所有可用备份
    --no-restart    回滚后不重启服务
    --help, -h      显示此帮助信息

示例:
    $0                                  # 回滚到最新备份
    $0 backups/20250129_143000          # 回滚到指定备份
    $0 --list                           # 列出所有备份

EOF
}

# 解析参数
BACKUP_PATH=""
NO_RESTART=false
LIST_ONLY=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --list)
            LIST_ONLY=true
            shift
            ;;
        --no-restart)
            NO_RESTART=true
            shift
            ;;
        *)
            if [ -z "$BACKUP_PATH" ]; then
                BACKUP_PATH="$1"
            else
                print_error "未知参数: $1"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# 确定项目根目录
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
PROJECT_ROOT="$(cd "${SCRIPT_DIR}/.." && pwd)"
cd "${PROJECT_ROOT}"

# 列出备份
if [ "$LIST_ONLY" = true ]; then
    print_info "可用备份列表:"
    if [ -d "backups" ]; then
        ls -lhd backups/*/ 2>/dev/null | while read line; do
            backup=$(echo $line | awk '{print $NF}')
            if [ -f "$backup/backup_info.txt" ]; then
                echo ""
                echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
                echo "📁 $(basename $backup)"
                cat "$backup/backup_info.txt" | sed 's/^/   /'
            fi
        done
        echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    else
        print_warning "没有找到备份目录"
    fi
    exit 0
fi

# 确定备份路径
if [ -z "$BACKUP_PATH" ]; then
    # 查找最新备份
    BACKUP_PATH=$(ls -td backups/*/ 2>/dev/null | head -1)
    if [ -z "$BACKUP_PATH" ]; then
        print_error "未找到任何备份"
        print_info "运行 '$0 --list' 查看可用备份"
        exit 1
    fi
    BACKUP_PATH=$(echo $BACKUP_PATH | sed 's:/$::')  # 移除末尾斜杠
    print_info "自动选择最新备份: $BACKUP_PATH"
fi

# 验证备份路径
if [ ! -d "$BACKUP_PATH" ]; then
    print_error "备份路径不存在: $BACKUP_PATH"
    print_info "运行 '$0 --list' 查看可用备份"
    exit 1
fi

BACKUP_ARCHIVE="$BACKUP_PATH/app_backup.tar.gz"
if [ ! -f "$BACKUP_ARCHIVE" ]; then
    print_error "备份文件不存在: $BACKUP_ARCHIVE"
    exit 1
fi

# 显示备份信息
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "↩️  开始回滚"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
if [ -f "$BACKUP_PATH/backup_info.txt" ]; then
    cat "$BACKUP_PATH/backup_info.txt" | sed 's/^/   /'
fi
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 确认回滚
read -p "确认回滚? (yes/no): " CONFIRM
if [ "$CONFIRM" != "yes" ]; then
    print_info "取消回滚"
    exit 0
fi

# 停止服务
if [ "$NO_RESTART" = false ]; then
    print_info "⏸️  停止当前服务..."
    if command -v pm2 &> /dev/null && [ -d "app" ]; then
        cd app
        pm2 stop all 2>/dev/null || true
        pm2 delete all 2>/dev/null || true
        cd ..
    fi
    print_success "服务已停止"
fi

# 备份当前失败版本
print_info "💾 备份当前版本..."
if [ -d "app" ]; then
    FAILED_BACKUP="backups/failed_$(date +%Y%m%d_%H%M%S)"
    mkdir -p "$FAILED_BACKUP"
    tar -czf "$FAILED_BACKUP/app_failed.tar.gz" app/ 2>/dev/null || true
    if [ -f "app/VERSION" ]; then
        cp app/VERSION "$FAILED_BACKUP/"
    fi
    print_success "失败版本已备份到: $FAILED_BACKUP"
fi

# 恢复代码
print_info "🔄 恢复代码..."
if [ -d "app" ]; then
    rm -rf app_rollback_temp 2>/dev/null || true
    mv app app_rollback_temp
fi

tar -xzf "$BACKUP_ARCHIVE"
print_success "代码已恢复"

# 恢复配置（从临时目录复制回来）
if [ -d "app_rollback_temp" ]; then
    print_info "💾 恢复当前配置..."
    if [ -f "app_rollback_temp/.env" ]; then
        cp app_rollback_temp/.env app/.env
        print_success "  恢复 .env"
    fi
    for keyfile in app_rollback_temp/APIKey*.json*; do
        if [ -f "$keyfile" ]; then
            cp "$keyfile" app/
            print_success "  恢复 $(basename $keyfile)"
        fi
    done
    rm -rf app_rollback_temp
fi

# 重启服务
if [ "$NO_RESTART" = false ]; then
    print_info "🚀 重启服务..."
    cd app
    if command -v pm2 &> /dev/null && [ -f "ecosystem.config.js" ]; then
        pm2 start ecosystem.config.js
        pm2 save
        print_success "服务已重启"

        # 健康检查
        sleep 5
        print_info "🔍 健康检查..."
        pm2 status
    else
        print_warning "PM2未安装或配置文件不存在，需要手动启动"
    fi
    cd ..
fi

print_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_success "✅ 回滚完成！"
print_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "🔍 验证命令:"
echo "   pm2 status"
echo "   pm2 logs"
echo ""
echo "📝 回滚信息:"
echo "   备份路径: $BACKUP_PATH"
if [ -f "app/VERSION" ]; then
    echo "   恢复版本: $(cat app/VERSION)"
fi
echo ""
print_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
