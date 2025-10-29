#!/bin/bash
# XT ETF 项目自动化部署脚本
# 用途: 自动部署项目到目标服务器
# 使用: ./scripts/deploy.sh <host> <user> [version]

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
XT ETF 项目自动化部署脚本

用法:
    $0 <HOST> <USER> [VERSION] [OPTIONS]

参数:
    HOST            目标服务器地址（IP或域名）
    USER            SSH 用户名
    VERSION         版本号（默认: 从 build/ 目录查找最新）

选项:
    --deploy-path PATH   部署路径（默认: /opt/xt-etf）
    --skip-backup        跳过备份
    --no-restart         部署后不重启服务
    --dry-run            模拟运行，不实际执行
    --help, -h           显示此帮助信息

示例:
    $0 192.168.1.100 trader              # 部署最新版本
    $0 192.168.1.100 trader 1.0.0        # 部署指定版本
    $0 prod-server trader --skip-backup  # 跳过备份

环境变量:
    SSH_KEY         SSH私钥路径（默认使用默认密钥）
    DEPLOY_TIMEOUT  部署超时时间（秒，默认600）

EOF
}

# 解析参数
DEPLOY_HOST=""
DEPLOY_USER=""
VERSION=""
DEPLOY_PATH="/opt/xt-etf"
SKIP_BACKUP=false
NO_RESTART=false
DRY_RUN=false
SSH_KEY=""
DEPLOY_TIMEOUT=600

while [[ $# -gt 0 ]]; do
    case $1 in
        --help|-h)
            show_help
            exit 0
            ;;
        --deploy-path)
            DEPLOY_PATH="$2"
            shift 2
            ;;
        --skip-backup)
            SKIP_BACKUP=true
            shift
            ;;
        --no-restart)
            NO_RESTART=true
            shift
            ;;
        --dry-run)
            DRY_RUN=true
            shift
            ;;
        *)
            if [ -z "$DEPLOY_HOST" ]; then
                DEPLOY_HOST="$1"
            elif [ -z "$DEPLOY_USER" ]; then
                DEPLOY_USER="$1"
            elif [ -z "$VERSION" ]; then
                VERSION="$1"
            else
                print_error "未知参数: $1"
                show_help
                exit 1
            fi
            shift
            ;;
    esac
done

# 验证必需参数
if [ -z "$DEPLOY_HOST" ] || [ -z "$DEPLOY_USER" ]; then
    print_error "缺少必需参数: HOST 和 USER"
    show_help
    exit 1
fi

# 确定版本号
if [ -z "$VERSION" ]; then
    # 从 build 目录查找最新的 tar.gz 文件
    LATEST_PACKAGE=$(ls -t build/xt-etf-*.tar.gz 2>/dev/null | head -1)
    if [ -z "$LATEST_PACKAGE" ]; then
        print_error "未找到打包文件，请先运行 ./scripts/package.sh"
        exit 1
    fi
    VERSION=$(basename "$LATEST_PACKAGE" | sed 's/xt-etf-//;s/.tar.gz//')
    print_info "自动选择最新版本: $VERSION"
fi

PACKAGE_NAME="xt-etf-${VERSION}"
PACKAGE_FILE="build/${PACKAGE_NAME}.tar.gz"

# 检查打包文件
if [ ! -f "$PACKAGE_FILE" ]; then
    print_error "打包文件不存在: $PACKAGE_FILE"
    print_info "请先运行: ./scripts/package.sh $VERSION"
    exit 1
fi

# SSH配置
SSH_OPTS="-o StrictHostKeyChecking=no -o ConnectTimeout=10"
if [ -n "$SSH_KEY" ]; then
    SSH_OPTS="$SSH_OPTS -i $SSH_KEY"
fi

# Dry run 提示
if [ "$DRY_RUN" = true ]; then
    print_warning "🔍 模拟运行模式（不会实际执行）"
    SSH_PREFIX="echo [DRY-RUN]"
    SCP_PREFIX="echo [DRY-RUN] scp"
else
    SSH_PREFIX="ssh $SSH_OPTS"
    SCP_PREFIX="scp $SSH_OPTS"
fi

print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "🚀 开始部署 XT ETF"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_info "版本:       ${VERSION}"
print_info "目标服务器: ${DEPLOY_USER}@${DEPLOY_HOST}"
print_info "部署路径:   ${DEPLOY_PATH}"
print_info "包文件:     ${PACKAGE_FILE}"
print_info "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# 步骤1: 检查服务器连接
print_info "1️⃣  检查服务器连接..."
if ! $SSH_PREFIX ${DEPLOY_USER}@${DEPLOY_HOST} "echo '连接成功'" > /dev/null 2>&1; then
    print_error "无法连接到服务器 ${DEPLOY_HOST}"
    print_info "请检查:"
    print_info "  - SSH 配置是否正确"
    print_info "  - 服务器是否可达"
    print_info "  - 用户名和密钥是否正确"
    exit 1
fi
print_success "服务器连接正常"

# 步骤2: 检查目标目录权限
print_info "2️⃣  检查目标目录权限..."
$SSH_PREFIX ${DEPLOY_USER}@${DEPLOY_HOST} << ENDSSH
if [ ! -d "${DEPLOY_PATH}" ]; then
    sudo mkdir -p "${DEPLOY_PATH}"
    sudo chown -R ${DEPLOY_USER}:${DEPLOY_USER} "${DEPLOY_PATH}"
    echo "✓ 创建部署目录: ${DEPLOY_PATH}"
else
    echo "✓ 部署目录已存在"
fi

if [ ! -w "${DEPLOY_PATH}" ]; then
    echo "✗ 没有写入权限: ${DEPLOY_PATH}"
    exit 1
fi
ENDSSH
print_success "目录权限检查通过"

# 步骤3: 上传打包文件
print_info "3️⃣  上传打包文件..."
UPLOAD_START=$(date +%s)
$SCP_PREFIX "$PACKAGE_FILE" ${DEPLOY_USER}@${DEPLOY_HOST}:/tmp/
UPLOAD_END=$(date +%s)
UPLOAD_TIME=$((UPLOAD_END - UPLOAD_START))
print_success "上传完成（耗时 ${UPLOAD_TIME}秒）"

# 步骤4: 服务器端部署
print_info "4️⃣  开始服务器端部署..."
$SSH_PREFIX ${DEPLOY_USER}@${DEPLOY_HOST} << ENDSSH
set -e

DEPLOY_PATH="${DEPLOY_PATH}"
PACKAGE_NAME="${PACKAGE_NAME}"
SKIP_BACKUP=${SKIP_BACKUP}
NO_RESTART=${NO_RESTART}

echo "📍 进入部署目录: \${DEPLOY_PATH}"
cd "\${DEPLOY_PATH}"

# 备份当前版本
if [ -d "app" ] && [ "\${SKIP_BACKUP}" = false ]; then
    BACKUP_DIR="backups/\$(date +%Y%m%d_%H%M%S)"
    echo "💾 备份当前版本到: \${BACKUP_DIR}"
    mkdir -p "\${BACKUP_DIR}"

    # 备份代码
    tar -czf "\${BACKUP_DIR}/app_backup.tar.gz" app/ 2>/dev/null || true

    # 保存版本信息
    if [ -f "app/VERSION" ]; then
        cp app/VERSION "\${BACKUP_DIR}/VERSION"
    fi

    # 记录备份信息
    cat > "\${BACKUP_DIR}/backup_info.txt" << EOF
备份时间: \$(date)
备份类型: 自动部署备份
新版本: ${VERSION}
EOF

    echo "✓ 备份完成"

    # 清理旧备份（保留最近10个）
    BACKUP_COUNT=\$(ls -1d backups/* 2>/dev/null | wc -l)
    if [ \${BACKUP_COUNT} -gt 10 ]; then
        echo "🗑️  清理旧备份..."
        ls -1td backups/* | tail -n +11 | xargs rm -rf
    fi
else
    echo "⏭️  跳过备份"
fi

# 解压新版本
echo "📦 解压新版本..."
tar -xzf /tmp/\${PACKAGE_NAME}.tar.gz -C /tmp/

# 保留现有配置
echo "💾 保留现有配置..."
if [ -d "app" ]; then
    # 复制配置文件
    if [ -f "app/.env" ]; then
        cp app/.env /tmp/\${PACKAGE_NAME}/.env
        echo "  ✓ 保留 .env"
    fi

    # 复制API密钥
    for keyfile in app/APIKey*.json app/APIKey*.json.enc; do
        if [ -f "\${keyfile}" ]; then
            cp "\${keyfile}" /tmp/\${PACKAGE_NAME}/
            echo "  ✓ 保留 \$(basename \${keyfile})"
        fi
    done

    # 复制PM2配置（如果有自定义修改）
    if [ -f "app/ecosystem.config.js" ] && [ ! -f "app/ecosystem.config.js.template" ]; then
        cp app/ecosystem.config.js /tmp/\${PACKAGE_NAME}/
        echo "  ✓ 保留 ecosystem.config.js"
    fi
fi

# 停止现有服务
if [ "\${NO_RESTART}" = false ]; then
    echo "⏸️  停止现有服务..."
    if command -v pm2 &> /dev/null; then
        cd "\${DEPLOY_PATH}/app" 2>/dev/null || true
        pm2 stop all 2>/dev/null || echo "  ⏭️ 没有运行中的服务"
        pm2 delete all 2>/dev/null || true
    fi
fi

# 切换版本
echo "🔄 切换到新版本..."
if [ -d "app" ]; then
    mv app app_old_\$(date +%Y%m%d%H%M%S) 2>/dev/null || rm -rf app
fi
mv /tmp/\${PACKAGE_NAME} app

# 设置权限
echo "🔒 设置文件权限..."
chmod +x app/scripts/*.sh
chmod 600 app/APIKey*.json* 2>/dev/null || true
chmod 600 app/.env 2>/dev/null || true

# 设置Python环境
echo "🐍 设置Python环境..."
cd app
if [ -f "scripts/setup_uv.sh" ]; then
    bash scripts/setup_uv.sh || echo "  ⚠️ uv设置失败，尝试传统方式..."
fi

# 验证安装
echo "✔️  验证安装..."
source .venv/bin/activate 2>/dev/null || true
python --version || echo "  ⚠️ Python未找到"

# 启动服务
if [ "\${NO_RESTART}" = false ]; then
    echo "🚀 启动服务..."
    if command -v pm2 &> /dev/null; then
        if [ -f "ecosystem.config.js" ]; then
            pm2 start ecosystem.config.js
            pm2 save
            echo "  ✓ PM2服务已启动"
        else
            echo "  ⚠️ 未找到PM2配置文件"
        fi
    else
        echo "  ⚠️ PM2未安装，需要手动启动服务"
    fi
fi

# 清理临时文件
echo "🧹 清理临时文件..."
rm -f /tmp/\${PACKAGE_NAME}.tar.gz

echo "✅ 部署完成！"
ENDSSH

print_success "服务器端部署完成"

# 步骤5: 健康检查
if [ "$NO_RESTART" = false ] && [ "$DRY_RUN" = false ]; then
    print_info "5️⃣  健康检查..."
    sleep 5

    $SSH_PREFIX ${DEPLOY_USER}@${DEPLOY_HOST} << 'ENDSSH'
cd /opt/xt-etf/app
if command -v pm2 &> /dev/null; then
    pm2 status
    echo ""
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
    echo "服务状态检查:"

    # 检查每个进程
    FAILED=0
    for proc in etf-stg3l etf-stg3s etf-stg5l etf-stg5s etf-net-value; do
        if pm2 show $proc &>/dev/null; then
            STATUS=$(pm2 show $proc | grep 'status' | awk '{print $4}')
            if [ "$STATUS" = "online" ]; then
                echo "  ✓ $proc: 运行中"
            else
                echo "  ✗ $proc: $STATUS"
                FAILED=1
            fi
        fi
    done

    if [ $FAILED -eq 0 ]; then
        echo ""
        echo "✅ 所有服务运行正常"
    else
        echo ""
        echo "⚠️ 部分服务未正常运行，请检查日志"
        echo "查看日志: pm2 logs"
    fi
    echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
else
    echo "⚠️ PM2未安装，跳过服务状态检查"
fi
ENDSSH
    print_success "健康检查完成"
fi

# 部署总结
print_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
print_success "🎉 部署成功完成！"
print_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo ""
echo "📝 部署信息:"
echo "   版本: ${VERSION}"
echo "   服务器: ${DEPLOY_HOST}"
echo "   路径: ${DEPLOY_PATH}/app"
echo ""
echo "🔍 常用命令:"
echo "   ssh ${DEPLOY_USER}@${DEPLOY_HOST} \"cd ${DEPLOY_PATH}/app && pm2 status\""
echo "   ssh ${DEPLOY_USER}@${DEPLOY_HOST} \"cd ${DEPLOY_PATH}/app && pm2 logs\""
echo "   ssh ${DEPLOY_USER}@${DEPLOY_HOST} \"cd ${DEPLOY_PATH}/app && pm2 monit\""
echo ""
echo "↩️  回滚命令（如需要）:"
echo "   ssh ${DEPLOY_USER}@${DEPLOY_HOST} \"${DEPLOY_PATH}/app/scripts/rollback.sh\""
echo ""
print_success "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
