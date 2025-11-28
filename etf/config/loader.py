# -*- coding: utf-8 -*-
"""
共享的配置加载模块
支持从本地目录或包内加载配置文件

统一管理：
- 策略配置 (strategies.yaml)
- 环境变量 (.env)
- API 密钥 (仅从 .env 或环境变量加载)
- 数据库配置
"""

import json
import logging
import os
import yaml
from pathlib import Path
from typing import Dict, Any, Optional, List

# 模块级别的环境变量初始化标志
_env_initialized = False
_env_file_path: Optional[str] = None


def find_config_file(config_file: str = "config/strategies.yaml") -> Optional[str]:
    """查找配置文件路径
    
    查找顺序：
    1. 环境变量 XT_ETF_CONFIG 指定的路径
    2. 当前目录的 config/strategies.yaml
    3. 项目根目录的 config/strategies.yaml（相对于此文件）
    4. 用户配置目录 ~/.config/xt_etf/strategies.yaml
    
    Args:
        config_file: 配置文件相对路径
        
    Returns:
        配置文件的绝对路径，如果找不到则返回 None
    """
    # 提取文件名用于备选路径查找
    config_filename = Path(config_file).name
    
    # 1. 环境变量指定的路径（最高优先级）
    env_config = os.getenv("XT_ETF_CONFIG")
    if env_config and os.path.exists(env_config):
        return env_config
    
    # 2. 当前目录的配置文件
    if os.path.exists(config_file):
        return config_file
    
    # 3. 项目根目录（相对于 loader.py 向上3级: etf/config/loader.py -> 项目根）
    project_root = Path(__file__).parent.parent.parent
    project_config = project_root / "config" / config_filename
    if project_config.exists():
        return str(project_config)
    
    # 4. 用户配置目录
    user_config = Path.home() / ".config" / "xt_etf" / config_filename
    if user_config.exists():
        return str(user_config)
    
    return None


def load_config(config_file: str = "config/strategies.yaml") -> Dict[str, Any]:
    """加载完整配置文件（包括策略和全局配置）
    
    Args:
        config_file: 配置文件相对路径
        
    Returns:
        配置字典
        
    Raises:
        SystemExit: 如果配置文件不存在
    """
    import sys
    
    config_path = find_config_file(config_file)
    
    if config_path is None:
        logging.error(f"配置文件 {config_file} 不存在")
        sys.exit(1)

    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)

    logging.info(f"成功加载配置文件: {config_path}")
    return config


def load_strategy_config(
    strategy_name: str, 
    config_file: str = "config/strategies.yaml",
    exit_on_error: bool = False
) -> Dict[str, Any]:
    """加载策略配置
    
    Args:
        strategy_name: 策略名称
        config_file: 配置文件相对路径
        exit_on_error: 如果为 True，找不到策略时退出程序；否则返回空字典
        
    Returns:
        策略配置字典，如果策略不存在且 exit_on_error=False 则返回空字典
    """
    import sys
    
    config_path = find_config_file(config_file)
    
    if config_path is None:
        if exit_on_error:
            logging.error(f"配置文件 {config_file} 不存在")
            sys.exit(1)
        else:
            logging.warning(f"配置文件 {config_file} 不存在，使用默认配置")
            return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)

        if "strategies" in config and strategy_name in config["strategies"]:
            logging.info(f"成功加载策略配置: {strategy_name} (from {config_path})")
            return config["strategies"][strategy_name]
        else:
            if exit_on_error:
                logging.error(f"策略 {strategy_name} 在配置文件中不存在")
                sys.exit(1)
            else:
                logging.warning(f"策略 {strategy_name} 在配置文件中不存在")
                return {}
    except Exception as e:
        logging.error(f"加载配置文件失败: {e}")
        if exit_on_error:
            sys.exit(1)
        return {}


def get_available_strategies(config_file: str = "config/strategies.yaml") -> List[str]:
    """从配置文件动态获取所有可用策略
    
    Args:
        config_file: 配置文件相对路径
        
    Returns:
        策略名称列表
    """
    config_path = find_config_file(config_file)
    if config_path is None:
        return []
    try:
        with open(config_path, "r", encoding="utf-8") as f:
            config = yaml.safe_load(f)
        return list(config.get("strategies", {}).keys())
    except Exception as e:
        logging.error(f"加载策略列表失败: {e}")
        return []


# ============================================================================
# 环境变量管理
# ============================================================================

def init_env(force: bool = False) -> Optional[str]:
    """
    统一初始化环境变量（整个项目只需调用一次）
    
    查找顺序：
    1. 当前工作目录的 .env
    2. 项目根目录的 .env（相对于此文件）
    3. 用户主目录 ~/.config/xt_etf/.env
    
    Args:
        force: 强制重新加载（即使已初始化）
        
    Returns:
        加载的 .env 文件路径，未找到则返回 None
    """
    global _env_initialized, _env_file_path
    
    if _env_initialized and not force:
        return _env_file_path
    
    try:
        from dotenv import load_dotenv
    except ImportError:
        logging.warning("python-dotenv 未安装，无法加载 .env 文件")
        _env_initialized = True
        return None
    
    # 查找 .env 文件
    env_paths = [
        Path.cwd() / ".env",
        Path(__file__).parent.parent.parent / ".env",  # 项目根目录
        Path.home() / ".config" / "xt_etf" / ".env",
    ]
    
    for env_path in env_paths:
        if env_path.exists():
            load_dotenv(env_path, override=True)
            _env_file_path = str(env_path)
            _env_initialized = True
            logging.info(f"✅ 已加载环境变量: {env_path}")
            return _env_file_path
    
    # 未找到 .env，使用默认查找
    load_dotenv()
    _env_initialized = True
    logging.debug("未找到 .env 文件，使用默认环境变量")
    return None


def get_env(key: str, default: str = None) -> Optional[str]:
    """
    获取环境变量（自动初始化环境）
    
    Args:
        key: 环境变量名
        default: 默认值
        
    Returns:
        环境变量值
    """
    init_env()  # 确保环境已初始化
    return os.getenv(key, default)


# ============================================================================
# API 密钥管理
# ============================================================================

def load_api_keys(
    strategy_name: Optional[str] = None,
    env: str = "prod",
) -> Dict[str, str]:
    """
    统一的 API 密钥加载（仅从 .env 或环境变量）
    
    Args:
        strategy_name: 策略名称（已废弃，保留用于兼容）
        env: 环境（已废弃，保留用于兼容）
        
    Returns:
        包含 access_key 和 secret_key 的字典
        
    Raises:
        ValueError: 未找到有效的 API 密钥
    """
    init_env()  # 确保环境已初始化
    
    access_key = os.getenv("access_key")
    secret_key = os.getenv("secret_key")
    
    if access_key and secret_key:
        logging.info("✅ 从环境变量加载 API 密钥")
        return {"access_key": access_key, "secret_key": secret_key}
    
    raise ValueError(
        "未找到有效的 API 密钥。请配置：\n"
        "  1. 在 .env 文件中设置: access_key=xxx 和 secret_key=xxx\n"
        "  2. 或设置环境变量: export access_key=xxx && export secret_key=xxx"
    )


def load_binance_api_keys() -> Dict[str, str]:
    """
    加载 Binance API 密钥（用于对冲）
    
    从 .env 或环境变量加载:
    - BN_ACCESS_KEY / bn_access_key
    - BN_SECRET_KEY / bn_secret_key
    
    Returns:
        包含 access_key 和 secret_key 的字典
        
    Raises:
        ValueError: 未找到有效的 Binance API 密钥
    """
    init_env()
    
    access_key = os.getenv("BN_ACCESS_KEY") or os.getenv("bn_access_key")
    secret_key = os.getenv("BN_SECRET_KEY") or os.getenv("bn_secret_key")
    
    if access_key and secret_key:
        logging.info("✅ 从环境变量加载 Binance API 密钥")
        return {"access_key": access_key, "secret_key": secret_key}
    
    raise ValueError(
        "未找到 Binance API 密钥。请配置：\n"
        "  1. 在 .env 文件中设置: bn_access_key=xxx 和 bn_secret_key=xxx\n"
        "  2. 或设置环境变量: export BN_ACCESS_KEY=xxx && export BN_SECRET_KEY=xxx"
    )


# ============================================================================
# 数据库配置
# ============================================================================

def get_db_config() -> Dict[str, Any]:
    """
    获取数据库配置
    
    从环境变量读取 PostgreSQL 配置
    
    Returns:
        数据库配置字典
    """
    init_env()
    
    return {
        "host": os.getenv("POSTGRES_HOST", "localhost"),
        "port": int(os.getenv("POSTGRES_PORT", "5432")),
        "user": os.getenv("POSTGRES_USER", "postgres"),
        "password": os.getenv("POSTGRES_PASSWORD", ""),
        "database": os.getenv("POSTGRES_DB", "xt_etf"),
    }


def get_db_url(async_driver: bool = False) -> str:
    """
    获取数据库连接 URL
    
    Args:
        async_driver: 是否使用异步驱动
        
    Returns:
        SQLAlchemy 连接 URL
    """
    config = get_db_config()
    driver = "postgresql+asyncpg" if async_driver else "postgresql+psycopg2"
    
    return (
        f"{driver}://{config['user']}:{config['password']}"
        f"@{config['host']}:{config['port']}/{config['database']}"
    )


def get_redis_config() -> Dict[str, Any]:
    """
    获取 Redis 配置
    
    Returns:
        Redis 配置字典
    """
    init_env()
    
    return {
        "host": os.getenv("REDIS_HOST", "localhost"),
        "port": int(os.getenv("REDIS_PORT", "6379")),
        "db": int(os.getenv("REDIS_DB", "0")),
        "password": os.getenv("REDIS_PASSWORD", None),
    }
