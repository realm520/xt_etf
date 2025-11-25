# -*- coding: utf-8 -*-
"""
共享的配置加载模块
支持从本地目录或包内加载配置文件

用于 run_etf.py 和 run_net_value.py 的统一配置加载
"""

import logging
import os
import yaml
from typing import Dict, Any, Optional, List


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
