# -*- coding: utf-8 -*-
"""
共享的配置加载模块
支持从本地目录或包内加载配置文件

统一管理：
- 策略配置 (strategies.yaml)
- 环境变量 (.env)
- API 密钥 (APIKey.json / APIKey.enc / 环境变量)
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
    1. 当前目录的 config/strategies.yaml
    2. 包内的 etf/config/strategies.yaml（uvx 安装时使用）
    
    Args:
        config_file: 配置文件相对路径
        
    Returns:
        配置文件的绝对路径，如果找不到则返回 None
    """
    # 1. 首先检查当前目录
    if os.path.exists(config_file):
        return config_file
    
    # 2. 检查包内配置文件
    try:
        try:
            from importlib.resources import files
            pkg_config = files("etf").joinpath("config", "strategies.yaml")
            if pkg_config.is_file():
                return str(pkg_config)
        except (ImportError, AttributeError, TypeError):
            # Python 3.8 降级方案
            import pkg_resources as pkg_res
            config_path = pkg_res.resource_filename("etf", "config/strategies.yaml")
            if os.path.exists(config_path):
                return config_path
    except Exception:
        pass
    
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
    apikey_file: str = "APIKey.json"
) -> Dict[str, str]:
    """
    统一的 API 密钥加载
    
    加载优先级：
    1. 环境变量 (access_key / secret_key)
    2. 加密文件 (APIKey.enc) - 生产环境优先
    3. JSON 文件 (APIKey.json) - 开发/测试环境
    
    Args:
        strategy_name: 策略名称（如 "stg3l"），用于从多策略配置中选择
        env: 环境 ("prod" / "qa")
        apikey_file: API 密钥文件路径
        
    Returns:
        包含 access_key 和 secret_key 的字典
        
    Raises:
        ValueError: 未找到有效的 API 密钥
    """
    init_env()  # 确保环境已初始化
    
    # 方式1: 环境变量（最高优先级）
    access_key = os.getenv("access_key")
    secret_key = os.getenv("secret_key")
    
    if access_key and secret_key:
        logging.info("✅ 从环境变量加载 API 密钥")
        return {"access_key": access_key, "secret_key": secret_key}
    
    # 方式2: 加密文件（生产环境）
    if env == "prod":
        enc_file = Path(apikey_file).with_suffix('.enc')
        if enc_file.exists():
            try:
                from etf.utils.crypto import load_api_keys as crypto_load
                apikey = crypto_load(apikey_file)
                
                # 如果指定策略名，从多策略配置中选择
                if strategy_name:
                    key_name = f"xt_{strategy_name}"
                    if key_name in apikey:
                        logging.info(f"✅ 从加密文件加载 API 密钥: {key_name}")
                        return apikey[key_name]
                
                # 返回第一个有效的密钥
                for key, value in apikey.items():
                    if isinstance(value, dict) and "access_key" in value:
                        logging.info(f"✅ 从加密文件加载 API 密钥: {key}")
                        return value
                        
            except Exception as e:
                logging.warning(f"加载加密文件失败: {e}")
    
    # 方式3: JSON 文件
    json_paths = [
        Path(apikey_file),
        Path.cwd() / apikey_file,
        Path(__file__).parent.parent.parent / apikey_file,
        Path.home() / ".config" / "xt_etf" / "APIKey.json",
    ]
    
    for json_path in json_paths:
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    apikey = json.load(f)
                
                # 如果指定策略名，从多策略配置中选择
                if strategy_name:
                    key_name = f"xt_{strategy_name}"
                    if key_name in apikey:
                        logging.info(f"✅ 从 {json_path} 加载 API 密钥: {key_name}")
                        return apikey[key_name]
                
                # 单策略文件格式
                if "access_key" in apikey:
                    logging.info(f"✅ 从 {json_path} 加载 API 密钥（单策略格式）")
                    return apikey
                
                # 返回第一个有效的密钥
                for key, value in apikey.items():
                    if isinstance(value, dict) and "access_key" in value:
                        logging.info(f"✅ 从 {json_path} 加载 API 密钥: {key}")
                        return value
                        
            except Exception as e:
                logging.warning(f"读取 {json_path} 失败: {e}")
    
    raise ValueError(
        "未找到有效的 API 密钥。请确保以下任一方式配置：\n"
        "  1. 环境变量: access_key 和 secret_key\n"
        "  2. .env 文件: access_key=xxx 和 secret_key=xxx\n"
        f"  3. JSON 文件: {apikey_file}"
    )


def load_binance_api_keys() -> Dict[str, str]:
    """
    加载 Binance API 密钥（用于对冲）
    
    加载优先级：
    1. 环境变量 (BN_ACCESS_KEY / BN_SECRET_KEY)
    2. .env 文件 (bn_access_key / bn_secret_key)
    3. APIKey.json 中的 "bn" 配置
    
    Returns:
        包含 access_key 和 secret_key 的字典
        
    Raises:
        ValueError: 未找到有效的 Binance API 密钥
    """
    init_env()
    
    # 方式1: 环境变量
    access_key = os.getenv("BN_ACCESS_KEY") or os.getenv("bn_access_key")
    secret_key = os.getenv("BN_SECRET_KEY") or os.getenv("bn_secret_key")
    
    if access_key and secret_key:
        logging.info("✅ 从环境变量加载 Binance API 密钥")
        return {"access_key": access_key, "secret_key": secret_key}
    
    # 方式2: APIKey.json
    json_paths = [
        Path("APIKey.json"),
        Path.cwd() / "APIKey.json",
        Path.home() / ".config" / "xt_etf" / "APIKey.json",
    ]
    
    for json_path in json_paths:
        if json_path.exists():
            try:
                with open(json_path, "r", encoding="utf-8") as f:
                    apikey = json.load(f)
                
                if "bn" in apikey and "access_key" in apikey["bn"]:
                    logging.info(f"✅ 从 {json_path} 加载 Binance API 密钥")
                    return apikey["bn"]
                    
            except Exception as e:
                logging.warning(f"读取 {json_path} 失败: {e}")
    
    raise ValueError(
        "未找到 Binance API 密钥。请配置以下任一方式：\n"
        "  1. 环境变量: BN_ACCESS_KEY 和 BN_SECRET_KEY\n"
        "  2. .env 文件: bn_access_key=xxx 和 bn_secret_key=xxx\n"
        "  3. APIKey.json 中添加 \"bn\" 配置"
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
