"""
ETF 策略 CLI 入口点模块

提供便捷的命令行入口，支持 uvx 直接调用：
    uvx --from . etf-run --strategy stg3l
    uvx --from . etf-stg3l
    uvx --from . etf-stg3s
    uvx --from . etf-stg5l  
    uvx --from . etf-stg5s
"""

import sys


def run_with_strategy(strategy: str):
    """使用指定策略运行 ETF 交易系统"""
    # 注入策略参数到命令行
    sys.argv = [sys.argv[0], "--strategy", strategy] + sys.argv[1:]
    
    # 导入并运行主程序
    from run_etf import main
    main()


def run_stg3l():
    """运行 3x 做多策略 (TON3L)"""
    run_with_strategy("stg3l")


def run_stg3s():
    """运行 3x 做空策略 (TON3S)"""
    run_with_strategy("stg3s")


def run_stg5l():
    """运行 5x 做多策略"""
    run_with_strategy("stg5l")


def run_stg5s():
    """运行 5x 做空策略"""
    run_with_strategy("stg5s")


def run_ton3l():
    """运行 TON 3x 做多策略 (QA 环境)"""
    run_with_strategy("ton3l")


if __name__ == "__main__":
    # 测试用
    print("ETF CLI 模块")
    print("可用命令: etf-run, etf-stg3l, etf-stg3s, etf-stg5l, etf-stg5s")
