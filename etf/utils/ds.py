# -*- coding:utf-8 -*-

"""
Author: AllenBrother
Date:   2023/2/3
Email:  huangyongjie088@gmail.com
"""

import numpy as np


class Queue:
    def __init__(self, max_size=2):
        self.length = max_size
        self.list = []

    def __str__(self):
        return str(self.list)

    def __len__(self):
        return len(self.list)

    def put(self, data):
        if len(self.list) >= self.length:
            self.list.pop(0)
            self.list.append(data)
        else:
            self.list.append(data)

    def get(self, index):
        return self.list[index]

    def pop_last(self):
        self.list.pop(-1)

    def mean(self):
        return sum(self.list) / len(self)

    def is_full(self):
        if len(self.list) == self.length:
            return 1
        else:
            return 0

    def to_np_array(self):
        return np.array(self.list)

    def count_num(self, value):
        return self.list.count(value)
