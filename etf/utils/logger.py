"""
统一日志配置模块

提供专业的日志配置功能，支持：
- 控制台彩色输出
- 文件自动轮转（按大小和时间）
- 错误日志单独记录
- 策略级别的日志隔离
- 线程安全的日志处理

作者: Claude Code
日期: 2025-10-23
"""

import logging
import os
import sys
from logging.handlers import RotatingFileHandler, TimedRotatingFileHandler
from pathlib import Path
from typing import Optional


class ColoredFormatter(logging.Formatter):
    """彩色日志格式化器（仅控制台使用）"""

    # ANSI 颜色代码
    COLORS = {
        'DEBUG': '\033[36m',      # 青色
        'INFO': '\033[32m',       # 绿色
        'WARNING': '\033[33m',    # 黄色
        'ERROR': '\033[31m',      # 红色
        'CRITICAL': '\033[35m',   # 紫色
    }
    RESET = '\033[0m'

    def format(self, record):
        # 添加颜色
        levelname = record.levelname
        if levelname in self.COLORS:
            record.levelname = f"{self.COLORS[levelname]}{levelname}{self.RESET}"

        # 格式化
        result = super().format(record)

        # 恢复原始 levelname（避免影响其他 handler）
        record.levelname = levelname

        return result


def setup_logging(
    strategy_name: str,
    log_level: int = logging.INFO,
    log_dir: str = "logs",
    enable_console: bool = True,
    enable_file: bool = True,
    enable_error_file: bool = True,
    max_bytes: int = 10 * 1024 * 1024,  # 10MB
    backup_count: int = 7,
    retention_days: int = 30,
) -> logging.Logger:
    """
    设置统一的日志配置

    Args:
        strategy_name: 策略名称（如 "ton3l", "stg3l"）
        log_level: 日志级别（默认 INFO）
        log_dir: 日志目录（默认 "logs"）
        enable_console: 是否启用控制台输出
        enable_file: 是否启用文件日志
        enable_error_file: 是否启用错误日志文件
        max_bytes: 单个日志文件最大大小（字节）
        backup_count: 保留的日志文件备份数量
        retention_days: 按日期轮转时保留的天数

    Returns:
        配置好的 root logger
    """

    # 获取 root logger
    logger = logging.getLogger()
    logger.setLevel(log_level)

    # 清除已有的 handlers（避免重复）
    logger.handlers.clear()

    # ========================================
    # 1. 控制台处理器（彩色输出）
    # ========================================
    if enable_console:
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(logging.INFO)  # 控制台只显示 INFO 及以上

        console_format = ColoredFormatter(
            fmt="%(asctime)s | %(levelname)-8s | %(filename)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        console_handler.setFormatter(console_format)
        logger.addHandler(console_handler)

    # ========================================
    # 2. 文件处理器（完整日志）
    # ========================================
    if enable_file:
        # 创建策略专属日志目录
        strategy_log_dir = Path(log_dir) / strategy_name
        strategy_log_dir.mkdir(parents=True, exist_ok=True)

        # 按日期轮转的文件处理器（主日志）
        log_file = strategy_log_dir / f"{strategy_name}.log"
        file_handler = TimedRotatingFileHandler(
            filename=str(log_file),
            when="midnight",        # 每天午夜轮转
            interval=1,             # 每 1 天
            backupCount=retention_days,  # 保留 N 天
            encoding="utf-8",
        )
        file_handler.setLevel(log_level)  # 文件记录所有级别

        file_format = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        file_handler.setFormatter(file_format)
        logger.addHandler(file_handler)

        # 按大小轮转的文件处理器（备用，防止单日日志过大）
        rotating_log_file = strategy_log_dir / f"{strategy_name}_rotating.log"
        rotating_handler = RotatingFileHandler(
            filename=str(rotating_log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        rotating_handler.setLevel(log_level)
        rotating_handler.setFormatter(file_format)
        logger.addHandler(rotating_handler)

    # ========================================
    # 3. 错误日志处理器（单独记录错误）
    # ========================================
    if enable_error_file:
        strategy_log_dir = Path(log_dir) / strategy_name
        strategy_log_dir.mkdir(parents=True, exist_ok=True)

        error_log_file = strategy_log_dir / f"{strategy_name}_error.log"
        error_handler = TimedRotatingFileHandler(
            filename=str(error_log_file),
            when="midnight",
            interval=1,
            backupCount=retention_days,
            encoding="utf-8",
        )
        error_handler.setLevel(logging.ERROR)  # 只记录 ERROR 和 CRITICAL

        error_format = logging.Formatter(
            fmt="%(asctime)s | %(levelname)-8s | %(name)s | %(filename)s:%(lineno)d | %(message)s\n%(message)s\n",
            datefmt="%Y-%m-%d %H:%M:%S"
        )
        error_handler.setFormatter(error_format)
        logger.addHandler(error_handler)

    # 记录日志配置信息
    logger.info("=" * 70)
    logger.info(f"📊 日志系统初始化完成")
    logger.info(f"   策略名称: {strategy_name}")
    logger.info(f"   日志级别: {logging.getLevelName(log_level)}")
    logger.info(f"   日志目录: {Path(log_dir).resolve() / strategy_name}")
    logger.info(f"   控制台输出: {'启用' if enable_console else '禁用'}")
    logger.info(f"   文件日志: {'启用' if enable_file else '禁用'}")
    logger.info(f"   错误日志: {'启用' if enable_error_file else '禁用'}")
    logger.info(f"   文件大小限制: {max_bytes / (1024 * 1024):.1f} MB")
    logger.info(f"   保留天数: {retention_days} 天")
    logger.info("=" * 70)

    return logger


def get_logger(name: Optional[str] = None) -> logging.Logger:
    """
    获取指定名称的 logger

    Args:
        name: logger 名称（通常使用 __name__）

    Returns:
        Logger 实例
    """
    return logging.getLogger(name)


# 测试代码
if __name__ == "__main__":
    # 测试日志配置
    setup_logging(
        strategy_name="test",
        log_level=logging.DEBUG,
        log_dir="logs"
    )

    logger = get_logger(__name__)

    # 测试各级别日志
    logger.debug("这是 DEBUG 级别日志")
    logger.info("这是 INFO 级别日志")
    logger.warning("这是 WARNING 级别日志")
    logger.error("这是 ERROR 级别日志")
    logger.critical("这是 CRITICAL 级别日志")

    print("\n✅ 日志测试完成！请检查 logs/test/ 目录")
