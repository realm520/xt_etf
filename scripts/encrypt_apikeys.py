#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
API 密钥加密脚本

将明文的 APIKey.json 文件加密为 APIKey.enc
支持交互式密码输入或从环境变量读取

使用方法：
1. 设置环境变量: export ETF_KEY_PASSWORD='your-password'
2. 运行脚本: python scripts/encrypt_apikeys.py
3. 或者直接运行并输入密码: python scripts/encrypt_apikeys.py

Author: ETF Trading System
Date: 2024-01-09
"""

import os
import sys
import json
import getpass
from pathlib import Path

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from etf.utils.crypto import KeyEncryptor


def main():
    """主函数"""
    print("ETF Trading System - API 密钥加密工具")
    print("=" * 50)
    
    # 默认文件路径
    default_input = "APIKey.json"
    default_output = "APIKey.enc"
    
    # 获取输入文件
    input_file = input(f"请输入要加密的文件路径 [{default_input}]: ").strip()
    if not input_file:
        input_file = default_input
        
    # 检查文件是否存在
    if not Path(input_file).exists():
        print(f"错误: 文件 {input_file} 不存在")
        
        # 提供创建示例文件的选项
        create_example = input("是否创建示例文件? (y/n): ").lower()
        if create_example == 'y':
            example_data = {
                "xt_stg3l": {
                    "access_key": "your-access-key-here",
                    "secret_key": "your-secret-key-here"
                },
                "xt_stg3s": {
                    "access_key": "your-access-key-here",
                    "secret_key": "your-secret-key-here"
                },
                "xt_stg5l": {
                    "access_key": "your-access-key-here",
                    "secret_key": "your-secret-key-here"
                },
                "xt_stg5s": {
                    "access_key": "your-access-key-here",
                    "secret_key": "your-secret-key-here"
                }
            }
            
            with open(input_file, 'w', encoding='utf-8') as f:
                json.dump(example_data, f, indent=2, ensure_ascii=False)
                
            print(f"已创建示例文件: {input_file}")
            print("请编辑文件填入实际的 API 密钥后重新运行此脚本")
            return
        else:
            return
            
    # 获取输出文件
    output_file = input(f"请输入加密后的文件路径 [{default_output}]: ").strip()
    if not output_file:
        output_file = default_output
        
    # 检查是否会覆盖现有文件
    if Path(output_file).exists():
        overwrite = input(f"文件 {output_file} 已存在，是否覆盖? (y/n): ").lower()
        if overwrite != 'y':
            print("操作已取消")
            return
            
    # 获取密码
    password = os.environ.get("ETF_KEY_PASSWORD")
    if password:
        print("使用环境变量中的密码")
    else:
        print("\n请设置加密密码（建议使用强密码）")
        password = getpass.getpass("输入密码: ")
        confirm = getpass.getpass("确认密码: ")
        
        if password != confirm:
            print("错误: 两次输入的密码不一致")
            return
            
        if len(password) < 8:
            print("警告: 密码长度建议至少 8 位")
            proceed = input("是否继续? (y/n): ").lower()
            if proceed != 'y':
                return
                
    # 执行加密
    try:
        print(f"\n正在加密 {input_file}...")
        encryptor = KeyEncryptor(password)
        encryptor.encrypt_file(input_file, output_file)
        
        print(f"\n加密成功！")
        print(f"加密文件: {output_file}")
        print(f"\n重要提示:")
        print(f"1. 请妥善保管您的密码，丢失密码将无法解密")
        print(f"2. 建议将密码设置到环境变量: export ETF_KEY_PASSWORD='your-password'")
        print(f"3. 可以删除明文文件 {input_file} 以提高安全性")
        print(f"4. 程序会自动优先使用加密文件 {output_file}")
        
        # 询问是否删除明文文件
        delete_plain = input(f"\n是否删除明文文件 {input_file}? (y/n): ").lower()
        if delete_plain == 'y':
            Path(input_file).unlink()
            print(f"已删除明文文件: {input_file}")
            
    except Exception as e:
        print(f"\n加密失败: {e}")
        return 1
        
    return 0


if __name__ == "__main__":
    sys.exit(main())