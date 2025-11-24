#!/usr/bin/env python3
"""
调试250档配置档位丢失问题
"""

import numpy as np

def test_layer_distribution():
    """测试250档时的分区逻辑"""
    n = 250  # 单边档位

    # 当前逻辑（from natural.py:113-123）
    if n < 100:
        near_ratio, mid_ratio = 0.3, 0.3
    elif n < 1000:
        near_ratio, mid_ratio = 0.2, 0.3
    elif n < 10000:
        near_ratio, mid_ratio = 0.1, 0.2
    else:
        near_ratio, mid_ratio = 0.02, 0.1

    n_near = max(1, int(n * near_ratio))
    n_mid = max(1, int(n * mid_ratio))
    n_far = max(1, n - n_near - n_mid)

    print("=" * 60)
    print(f"分区逻辑测试 (layer={n})")
    print("=" * 60)
    print(f"near_ratio: {near_ratio}, mid_ratio: {mid_ratio}")
    print(f"n_near: {n_near}")
    print(f"n_mid: {n_mid}")
    print(f"n_far: {n_far}")
    print(f"总计: {n_near + n_mid + n_far}")
    print(f"预期: {n}")
    print(f"差异: {n - (n_near + n_mid + n_far)}")

    # 生成价格（简化版本）
    mid_price = 1.0
    spread = 0.008
    base = mid_price * (1 - spread / 2)  # 买盘基准

    # Near区
    near_prices = base * (1 - np.linspace(0, 0.005, n_near))
    print(f"\nNear区价格范围: {near_prices[-1]:.6f} - {near_prices[0]:.6f}")

    # Mid区
    mid_start = near_prices[-1]
    mid_end = mid_start * 0.98
    mid_prices = np.geomspace(mid_start, mid_end, n_mid)
    print(f"Mid区价格范围: {mid_prices[-1]:.6f} - {mid_prices[0]:.6f}")

    # Far区
    far_start = mid_prices[-1]
    far_end = far_start * 0.95
    far_prices = np.geomspace(far_start, far_end, n_far)
    print(f"Far区价格范围: {far_prices[-1]:.6f} - {far_prices[0]:.6f}")

    # 合并
    all_prices = np.concatenate([near_prices, mid_prices, far_prices])
    print(f"\n总价格档位数: {len(all_prices)}")
    print(f"价格范围: {all_prices[-1]:.6f} - {all_prices[0]:.6f}")
    print("=" * 60)

if __name__ == "__main__":
    test_layer_distribution()
