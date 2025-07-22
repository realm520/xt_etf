#!/bin/bash

# ETF测试运行脚本
# Author: Claude Code
# Date: 2025-01-22

set -e

echo "🧪 ETF交易系统测试套件"
echo "=========================="

# 颜色定义
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m' # No Color

# 检查Python环境
echo -e "${BLUE}检查Python环境...${NC}"
if ! command -v python3 &> /dev/null; then
    echo -e "${RED}错误: Python3 未安装${NC}"
    exit 1
fi

# 检查pytest
if ! python3 -c "import pytest" &> /dev/null; then
    echo -e "${RED}错误: pytest 未安装，请运行: pip install -e .[dev]${NC}"
    exit 1
fi

# 检查Redis (可选)
echo -e "${BLUE}检查Redis连接...${NC}"
if python3 -c "import redis; redis.Redis(host='localhost', port=6379, db=15).ping()" &> /dev/null; then
    echo -e "${GREEN}✓ Redis 可用${NC}"
    REDIS_AVAILABLE=true
else
    echo -e "${YELLOW}⚠ Redis 不可用，将跳过相关测试${NC}"
    REDIS_AVAILABLE=false
fi

# 解析命令行参数
TEST_TYPE="all"
COVERAGE=false
VERBOSE=false
PERFORMANCE=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --unit)
            TEST_TYPE="unit"
            shift
            ;;
        --integration)
            TEST_TYPE="integration"
            shift
            ;;
        --performance)
            TEST_TYPE="performance"
            PERFORMANCE=true
            shift
            ;;
        --coverage)
            COVERAGE=true
            shift
            ;;
        --verbose|-v)
            VERBOSE=true
            shift
            ;;
        --help|-h)
            echo "用法: $0 [选项]"
            echo "选项:"
            echo "  --unit        只运行单元测试"
            echo "  --integration 只运行集成测试"
            echo "  --performance 只运行性能测试"
            echo "  --coverage    生成覆盖率报告"
            echo "  --verbose     详细输出"
            echo "  --help        显示此帮助信息"
            exit 0
            ;;
        *)
            echo -e "${RED}未知选项: $1${NC}"
            exit 1
            ;;
    esac
done

# 构建pytest命令
PYTEST_CMD="python3 -m pytest"

# 添加详细输出
if [ "$VERBOSE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD -v -s"
fi

# 添加覆盖率
if [ "$COVERAGE" = true ]; then
    PYTEST_CMD="$PYTEST_CMD --cov=etf --cov=binance --cov-report=html --cov-report=term-missing"
fi

# 根据测试类型设置参数
case $TEST_TYPE in
    unit)
        echo -e "${BLUE}运行单元测试...${NC}"
        PYTEST_CMD="$PYTEST_CMD -m 'unit or (not integration and not performance)'"
        ;;
    integration)
        echo -e "${BLUE}运行集成测试...${NC}"
        PYTEST_CMD="$PYTEST_CMD -m integration"
        if [ "$REDIS_AVAILABLE" = false ]; then
            echo -e "${YELLOW}跳过需要Redis的集成测试${NC}"
            PYTEST_CMD="$PYTEST_CMD and not redis_required"
        fi
        ;;
    performance)
        echo -e "${BLUE}运行性能测试...${NC}"
        PYTEST_CMD="$PYTEST_CMD -m performance tests/test_performance_benchmarks.py"
        # 性能测试不使用并行
        PYTEST_CMD=$(echo $PYTEST_CMD | sed 's/-n [0-9]*//')
        ;;
    all)
        echo -e "${BLUE}运行所有测试...${NC}"
        if [ "$REDIS_AVAILABLE" = false ]; then
            PYTEST_CMD="$PYTEST_CMD -m 'not redis_required'"
        fi
        ;;
esac

# 特定测试文件
TEST_FILES=""
if [ "$TEST_TYPE" = "unit" ]; then
    TEST_FILES="tests/test_market_making.py tests/test_order_manager.py tests/test_risk.py tests/test_washing.py tests/test_orderbook.py tests/test_net_value_improved.py tests/test_low_frequency_strategy.py tests/test_redis_last_amount.py"
elif [ "$TEST_TYPE" = "integration" ]; then
    TEST_FILES="tests/test_etf_integration.py tests/test_exception_scenarios.py"
elif [ "$TEST_TYPE" = "performance" ]; then
    TEST_FILES="tests/test_performance_benchmarks.py"
fi

# 执行测试
echo -e "${BLUE}执行命令: $PYTEST_CMD $TEST_FILES${NC}"
echo ""

# 运行测试
if $PYTEST_CMD $TEST_FILES; then
    echo ""
    echo -e "${GREEN}✅ 测试完成${NC}"
    
    # 显示覆盖率报告位置
    if [ "$COVERAGE" = true ]; then
        echo -e "${BLUE}📊 覆盖率报告已生成:${NC}"
        echo "  - HTML报告: htmlcov/index.html"
        echo "  - 终端报告: 见上方输出"
        
        # 如果可以打开浏览器，提供快捷命令
        if command -v open &> /dev/null; then
            echo -e "${YELLOW}💡 运行 'open htmlcov/index.html' 查看详细覆盖率报告${NC}"
        elif command -v xdg-open &> /dev/null; then
            echo -e "${YELLOW}💡 运行 'xdg-open htmlcov/index.html' 查看详细覆盖率报告${NC}"
        fi
    fi
    
    # 性能测试后的建议
    if [ "$PERFORMANCE" = true ]; then
        echo -e "${YELLOW}💡 性能测试完成，请查看上方的基准测试结果${NC}"
    fi
    
else
    echo ""
    echo -e "${RED}❌ 测试失败${NC}"
    exit 1
fi

echo ""
echo -e "${BLUE}测试统计信息:${NC}"
echo "  - 测试类型: $TEST_TYPE"
echo "  - Redis可用: $REDIS_AVAILABLE"
echo "  - 覆盖率报告: $COVERAGE"
echo "  - 详细输出: $VERBOSE"

exit 0