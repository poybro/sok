# sok/utils.py
# -*- coding: utf-8 -*-

import hashlib
import json
from typing import Any

def hash_data(data: Any) -> str:
    """Tạo mã băm SHA256 cho bất kỳ dữ liệu đầu vào nào."""
    if isinstance(data, bytes):
        return hashlib.sha256(data).hexdigest()
    if not isinstance(data, str):
        data_string = json.dumps(data, sort_keys=True)
    else:
        data_string = data
    return hashlib.sha256(data_string.encode()).hexdigest()

class Config:
    """Lớp chứa tất cả các hằng số cấu hình cho blockchain."""
    # Cấu hình Kinh tế & Khai thác
    DIFFICULTY = 5
    MINING_REWARD = 0.1
    HALVING_BLOCK_INTERVAL = 210000

    # Các mục tiêu kinh tế vĩ mô cho AI Agent
    TARGET_BLOCK_TIME_SECONDS = 30
    PENDING_TX_THRESHOLD = 100

    # Cấu hình Khối Genesis
    INITIAL_SUPPLY_TOKENS = 10000000
    FOUNDER_ADDRESS = "SOa29d38da8236aae8ff4046d4476cd684dc8289694cecf73f1cf0db96e972f8faK"
    GENESIS_PREVIOUS_HASH = "0" * 64
    GENESIS_NONCE = 0

    # Cấu hình Mạng lưới
    DEFAULT_NODE_PORT = 5000
