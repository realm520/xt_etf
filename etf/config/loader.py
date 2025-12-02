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
    1. 环境变量 ETF_CONFIG_PATH 指定的绝对路径（最高优先级）
    2. 环境变量 XT_ETF_CONFIG 指定的路径（向后兼容）
    3. 当前目录的 config/strategies.yaml
    4. 项目根目录的 config/strategies.yaml（相对于此文件）
    5. 用户配置目录 ~/.config/xt_etf/strategies.yaml
    
    Args:
        config_file: 配置文件相对路径
        
    Returns:
        配置文件的绝对路径，如果找不到则返回 None
    """
    # 提取文件名用于备选路径查找
    config_filename = Path(config_file).name
    
    # 1. ETF_CONFIG_PATH 环境变量（最高优先级，支持绝对路径）
    env_config_path = os.getenv("ETF_CONFIG_PATH")
    if env_config_path:
        if os.path.exists(env_config_path):
            logging.info(f"使用 ETF_CONFIG_PATH 环境变量: {env_config_path}")
            return env_config_path
        else:
            logging.warning(f"ETF_CONFIG_PATH 指定的文件不存在: {env_config_path}")
    
    # 2. XT_ETF_CONFIG 环境变量（向后兼容）
    env_config = os.getenv("XT_ETF_CONFIG")
    if env_config and os.path.exists(env_config):
        logging.info(f"使用 XT_ETF_CONFIG 环境变量: {env_config}")
        return env_config
    
    # 3. 当前目录的配置文件
    if os.path.exists(config_file):
        return config_file
    
    # 4. 项目根目录（相对于 loader.py 向上2级: etf/config/loader.py -> 项目根）
    project_root = Path(__file__).parent.parent.parent
    project_config = project_root / "config" / config_filename
    if project_config.exists():
        return str(project_config)
    
    # 5. 用户配置目录
    user_config = Path.home() / ".config" / "xt_etf" / config_filename
    if user_config.exists():
        return str(user_config)
    
    return None



def _deep_merge(base: Dict[str, Any], override: Dict[str, Any]) -> Dict[str, Any]:
    """深度合并两个字典，override 覆盖 base
    
    Args:
        base: 基础字典
        override: 覆盖字典
        
    Returns:
        合并后的新字典
    """
    result = dict(base)
    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            result[key] = _deep_merge(result[key], value)
        else:
            result[key] = value
    return result


def _find_strategy_file(strategy_name: str, global_config_path: str) -> Optional[str]:
    """查找策略特定配置文件
    
    Args:
        strategy_name: 策略名称
        global_config_path: 全局配置文件路径
        
    Returns:
        策略配置文件路径，如果不存在则返回 None
    """
    config_dir = Path(global_config_path).parent
    strategy_file = config_dir / f"{strategy_name}.yaml"
    
    if strategy_file.exists():
        return str(strategy_file)
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
    """加载策略配置（全局默认 + strategies配置 + 预设 + 策略特定文件覆盖）
    
    配置合并优先级（从低到高）：
    1. 全局默认配置 (defaults)
    2. strategies.yaml 中的策略配置 (strategies.<strategy_name>)
    3. 订单簿预设 (orderbook_presets)
    4. 策略特定配置文件 (config/<strategy>.yaml)
    
    Args:
        strategy_name: 策略名称
        config_file: 全局配置文件相对路径
        exit_on_error: 如果为 True，找不到策略时退出程序
        
    Returns:
        合并后的策略配置字典
    """
    import sys
    
    config_path = find_config_file(config_file)
    
    if config_path is None:
        if exit_on_error:
            logging.error(f"配置文件 {config_file} 不存在")
            sys.exit(1)
        else:
            logging.warning(f"配置文件 {config_file} 不存在")
            return {}

    try:
        with open(config_path, "r", encoding="utf-8") as f:
            global_config = yaml.safe_load(f)

        # 1. 从全局默认配置开始
        result = dict(global_config.get("defaults", {}))
        
        # 2. 应用 strategies.yaml 中的策略特定配置
        strategies_section = global_config.get("strategies", {})
        if strategy_name in strategies_section:
            strategy_in_yaml = strategies_section[strategy_name]
            result = _deep_merge(result, strategy_in_yaml)
            logging.info(f"应用 strategies.yaml 中的 {strategy_name} 配置")
        
        # 3. 加载策略特定配置文件（如果存在）
        strategy_file = _find_strategy_file(strategy_name, config_path)
        
        if strategy_file:
            with open(strategy_file, "r", encoding="utf-8") as f:
                strategy_data = yaml.safe_load(f)
                strategy_config = strategy_data.get("strategy", {})
            
            logging.info(f"加载策略配置文件: {strategy_file}")
            
            # 4. 应用订单簿预设
            orderbook_preset = strategy_config.get("orderbook_preset")
            if orderbook_preset and "orderbook_presets" in global_config:
                preset = global_config["orderbook_presets"].get(orderbook_preset, {})
                result = _deep_merge(result, preset)
                logging.debug(f"应用订单簿预设: {orderbook_preset}")
            
            # 5. 应用策略特定配置文件（最高优先级）
            strategy_overrides = {k: v for k, v in strategy_config.items() 
                                if k not in ("orderbook_preset",)}
            result = _deep_merge(result, strategy_overrides)
        elif strategy_name not in strategies_section:
            # 既没有 strategies 配置，也没有策略文件
            if exit_on_error:
                logging.error(f"策略 {strategy_name} 配置不存在（无 strategies.yaml 配置，无 config/{strategy_name}.yaml 文件）")
                sys.exit(1)
            else:
                logging.warning(f"策略 {strategy_name} 使用默认配置")
        
        return result
        
    except Exception as e:
        logging.error(f"加载配置文件失败: {e}")
        if exit_on_error:
            sys.exit(1)
        return {}


def get_available_strategies(config_file: str = "config/strategies.yaml") -> List[str]:
    """从配置目录获取所有可用策略
    
    扫描 config/ 目录下的 <strategy>.yaml 文件
    如果找不到配置文件，返回默认策略列表
    
    Args:
        config_file: 全局配置文件相对路径
        
    Returns:
        策略名称列表
    """
    # 默认策略列表（当配置文件不存在时使用，如 pip 安装场景）
    DEFAULT_STRATEGIES = ["stg3l", "stg3s", "stg5l", "stg5s", "ton3l", "ton3s"]
    
    strategies = []
    config_path = find_config_file(config_file)
    
    if config_path is None:
        logging.warning(f"配置文件 {config_file} 未找到，使用默认策略列表")
        return DEFAULT_STRATEGIES
    
    config_dir = Path(config_path).parent
    
    for yaml_file in config_dir.glob("*.yaml"):
        if yaml_file.name == "strategies.yaml":
            continue
        try:
            with open(yaml_file, "r", encoding="utf-8") as f:
                data = yaml.safe_load(f)
                if data and "strategy" in data:
                    strategies.append(yaml_file.stem)
        except Exception:
            pass
    
    # 如果没有找到任何策略配置文件，返回默认列表
    if not strategies:
        logging.warning("未找到策略配置文件，使用默认策略列表")
        return DEFAULT_STRATEGIES
    
    return sorted(strategies)


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
# Redis 配置
# ============================================================================

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
