# -*- coding: utf-8 -*-
"""
API 密钥加密工具

使用 AES-256-GCM 加密算法保护敏感的 API 密钥
支持从环境变量或交互式输入获取密码

Author: ETF Trading System
Date: 2024-01-09
"""

import os
import json
import base64
import getpass
from typing import Dict, Any, Optional
from pathlib import Path
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes
from cryptography.hazmat.primitives.kdf.pbkdf2 import PBKDF2HMAC
from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.backends import default_backend
import secrets


class KeyEncryptor:
    """API 密钥加密器"""
    
    def __init__(self, password: Optional[str] = None):
        """
        初始化加密器
        
        Args:
            password: 加密密码，如果不提供则从环境变量或交互式输入获取
        """
        self.password = password or self._get_password()
        self.backend = default_backend()
        
    def _get_password(self) -> str:
        """获取密码"""
        # 优先从环境变量获取
        password = os.environ.get("ETF_KEY_PASSWORD")
        if password:
            return password
            
        # 交互式输入
        password = getpass.getpass("请输入 API 密钥加密密码: ")
        if not password:
            raise ValueError("密码不能为空")
            
        return password
        
    def _derive_key(self, salt: bytes) -> bytes:
        """从密码派生密钥"""
        kdf = PBKDF2HMAC(
            algorithm=hashes.SHA256(),
            length=32,  # 256 bits
            salt=salt,
            iterations=100000,
            backend=self.backend
        )
        return kdf.derive(self.password.encode())
        
    def encrypt_data(self, data: Dict[str, Any]) -> Dict[str, str]:
        """
        加密数据
        
        Args:
            data: 要加密的数据字典
            
        Returns:
            包含加密数据和元信息的字典
        """
        # 生成随机盐和 nonce
        salt = secrets.token_bytes(16)
        nonce = secrets.token_bytes(12)
        
        # 派生密钥
        key = self._derive_key(salt)
        
        # 创建加密器
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce),
            backend=self.backend
        )
        encryptor = cipher.encryptor()
        
        # 加密数据
        plaintext = json.dumps(data, ensure_ascii=False).encode('utf-8')
        ciphertext = encryptor.update(plaintext) + encryptor.finalize()
        
        # 返回加密结果
        return {
            "version": "1.0",
            "algorithm": "AES-256-GCM",
            "salt": base64.b64encode(salt).decode('utf-8'),
            "nonce": base64.b64encode(nonce).decode('utf-8'),
            "tag": base64.b64encode(encryptor.tag).decode('utf-8'),
            "ciphertext": base64.b64encode(ciphertext).decode('utf-8')
        }
        
    def decrypt_data(self, encrypted_data: Dict[str, str]) -> Dict[str, Any]:
        """
        解密数据
        
        Args:
            encrypted_data: 加密的数据字典
            
        Returns:
            解密后的原始数据
        """
        # 检查版本
        if encrypted_data.get("version") != "1.0":
            raise ValueError(f"不支持的加密版本: {encrypted_data.get('version')}")
            
        # 解码数据
        salt = base64.b64decode(encrypted_data["salt"])
        nonce = base64.b64decode(encrypted_data["nonce"])
        tag = base64.b64decode(encrypted_data["tag"])
        ciphertext = base64.b64decode(encrypted_data["ciphertext"])
        
        # 派生密钥
        key = self._derive_key(salt)
        
        # 创建解密器
        cipher = Cipher(
            algorithms.AES(key),
            modes.GCM(nonce, tag),
            backend=self.backend
        )
        decryptor = cipher.decryptor()
        
        # 解密数据
        plaintext = decryptor.update(ciphertext) + decryptor.finalize()
        
        # 返回原始数据
        return json.loads(plaintext.decode('utf-8'))
        
    def encrypt_file(self, input_path: str, output_path: Optional[str] = None):
        """
        加密文件
        
        Args:
            input_path: 输入文件路径
            output_path: 输出文件路径，默认为 input_path + '.enc'
        """
        input_file = Path(input_path)
        if not input_file.exists():
            raise FileNotFoundError(f"文件不存在: {input_path}")
            
        # 读取原始数据
        with open(input_file, 'r', encoding='utf-8') as f:
            data = json.load(f)
            
        # 加密数据
        encrypted_data = self.encrypt_data(data)
        
        # 写入加密文件
        output_file = Path(output_path) if output_path else input_file.with_suffix('.enc')
        with open(output_file, 'w', encoding='utf-8') as f:
            json.dump(encrypted_data, f, indent=2, ensure_ascii=False)
            
        print(f"加密完成: {output_file}")
        
    def decrypt_file(self, input_path: str) -> Dict[str, Any]:
        """
        解密文件
        
        Args:
            input_path: 加密文件路径
            
        Returns:
            解密后的数据
        """
        input_file = Path(input_path)
        if not input_file.exists():
            raise FileNotFoundError(f"文件不存在: {input_path}")
            
        # 读取加密数据
        with open(input_file, 'r', encoding='utf-8') as f:
            encrypted_data = json.load(f)
            
        # 解密并返回
        return self.decrypt_data(encrypted_data)


class SecureAPIKeyLoader:
    """安全的 API 密钥加载器"""
    
    def __init__(self, password: Optional[str] = None):
        self.encryptor = KeyEncryptor(password)
        
    def load_keys(self, file_path: str) -> Dict[str, Any]:
        """
        加载 API 密钥（支持加密和明文格式）
        
        Args:
            file_path: 密钥文件路径
            
        Returns:
            API 密钥字典
        """
        path = Path(file_path)
        
        # 优先尝试加载加密文件
        enc_path = path.with_suffix('.enc')
        if enc_path.exists():
            try:
                return self.encryptor.decrypt_file(str(enc_path))
            except Exception as e:
                print(f"解密失败: {e}")
                raise
                
        # 如果没有加密文件，尝试加载明文文件
        if path.exists():
            print(f"警告: 使用明文 API 密钥文件 {path}")
            print("建议使用 scripts/encrypt_apikeys.py 加密您的 API 密钥")
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
                
        raise FileNotFoundError(f"找不到 API 密钥文件: {path} 或 {enc_path}")


# 便捷函数
def encrypt_api_keys(input_file: str, output_file: Optional[str] = None, password: Optional[str] = None):
    """加密 API 密钥文件"""
    encryptor = KeyEncryptor(password)
    encryptor.encrypt_file(input_file, output_file)
    
    
def load_api_keys(file_path: str, password: Optional[str] = None) -> Dict[str, Any]:
    """加载 API 密钥（自动处理加密/明文）"""
    loader = SecureAPIKeyLoader(password)
    return loader.load_keys(file_path)