# -*- coding:utf-8 -*-

"""
Author: AllenBrother
Date:   2023/2/3
Email:  huangyongjie088@gmail.com
"""

import numpy as np
import random


def normal(mean, scale, size):
    return np.random.normal(mean, scale, size)


def normal_drift_delta(target, mean, scale, size):
    res = target + normal(mean, scale, size)
    return res


def uniform(min, max):
    return random.uniform(min, max)


def uniform_drift_perc(target, min, max):
    res = target * (1 + uniform(min, max))
    return res


def classical_prob(result: list, prob: list):
    assert sum(prob) == 1, print("probabilities do not sum to 1")
    pro_split = np.random.choice(result, p=np.array(prob).ravel())
    return pro_split





