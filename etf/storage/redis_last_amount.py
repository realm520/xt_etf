"""
Redis-based storage for last_amount data
用于存储和管理各策略的最新持仓数量，支持故障恢复
"""

import redis
import logging
import json
from typing import Optional, Dict, Any
from datetime import datetime

logger = logging.getLogger(__name__)


class RedisLastAmountStorage:
    """Redis存储管理器，用于持久化last_amount数据"""

    def __init__(self, redis_client: redis.Redis = None, prefix: str = "last_amount"):
        """
        初始化Redis存储管理器

        Args:
            redis_client: Redis客户端实例，如果为None则创建新实例
            prefix: Redis key前缀，默认为"last_amount"
        """
        self.redis = redis_client or redis.Redis(
            host="localhost",
            port=6379,
            db=0,
            decode_responses=False,  # 返回bytes以便处理编码
        )
        self.prefix = prefix

    def _get_key(self, symbol: str) -> str:
        """生成Redis key"""
        return f"{self.prefix}:{symbol}"

    def _get_detail_key(self, symbol: str) -> str:
        """生成详细信息的Redis key"""
        return f"{self.prefix}:detail:{symbol}"

    def set_last_amount(self, symbol: str, amount: float, **kwargs) -> bool:
        """
        存储last_amount到Redis

        Args:
            symbol: 交易对符号 (例如: stg3l_usdt)
            amount: 持仓数量
            **kwargs: 其他要存储的元数据

        Returns:
            bool: 是否成功存储
        """
        try:
            # 存储简单值（向后兼容）
            self.redis.set(self._get_key(symbol), str(amount))

            # 存储详细信息（包含时间戳等）
            detail_data = {
                "amount": amount,
                "timestamp": datetime.now().isoformat(),
                "symbol": symbol,
                **kwargs,
            }
            self.redis.set(
                self._get_detail_key(symbol),
                json.dumps(detail_data),
                ex=30 * 24 * 60 * 60,  # 30天过期
            )

            logger.info(f"Stored last_amount for {symbol}: {amount}")
            return True

        except Exception as e:
            logger.error(f"Failed to store last_amount for {symbol}: {e}")
            return False

    def get_last_amount(self, symbol: str) -> Optional[float]:
        """
        从Redis获取last_amount

        Args:
            symbol: 交易对符号

        Returns:
            float: 持仓数量，如果不存在或出错返回None
        """
        try:
            # 尝试从简单值获取
            value = self.redis.get(self._get_key(symbol))
            if value:
                return float(value.decode("utf-8"))

            # 尝试从详细信息获取
            detail_value = self.redis.get(self._get_detail_key(symbol))
            if detail_value:
                detail_data = json.loads(detail_value.decode("utf-8"))
                return float(detail_data.get("amount", 0))

            return None

        except Exception as e:
            logger.error(f"Failed to get last_amount for {symbol}: {e}")
            return None

    def get_last_amount_detail(self, symbol: str) -> Optional[Dict[str, Any]]:
        """
        获取last_amount的详细信息

        Args:
            symbol: 交易对符号

        Returns:
            dict: 包含amount、timestamp等信息的字典
        """
        try:
            detail_value = self.redis.get(self._get_detail_key(symbol))
            if detail_value:
                return json.loads(detail_value.decode("utf-8"))
            return None

        except Exception as e:
            logger.error(f"Failed to get last_amount detail for {symbol}: {e}")
            return None

    def delete_last_amount(self, symbol: str) -> bool:
        """
        删除指定symbol的last_amount数据

        Args:
            symbol: 交易对符号

        Returns:
            bool: 是否成功删除
        """
        try:
            self.redis.delete(self._get_key(symbol))
            self.redis.delete(self._get_detail_key(symbol))
            logger.info(f"Deleted last_amount for {symbol}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete last_amount for {symbol}: {e}")
            return False

    def get_all_symbols(self) -> list:
        """
        获取所有存储的symbol列表

        Returns:
            list: symbol列表
        """
        try:
            # 使用scan避免keys命令的性能问题
            symbols = set()
            pattern = f"{self.prefix}:*"

            for key in self.redis.scan_iter(match=pattern):
                key_str = key.decode("utf-8") if isinstance(key, bytes) else key
                # 提取symbol部分
                if not key_str.endswith(":detail"):
                    symbol = key_str.replace(f"{self.prefix}:", "")
                    if symbol and ":" not in symbol:  # 排除detail keys
                        symbols.add(symbol)

            return list(symbols)

        except Exception as e:
            logger.error(f"Failed to get all symbols: {e}")
            return []

    def health_check(self) -> bool:
        """
        检查Redis连接是否正常

        Returns:
            bool: Redis是否可用
        """
        try:
            self.redis.ping()
            return True
        except:
            return False
