#!/usr/bin/env python3
# create_miner_wallet.py
# -*- coding: utf-8 -*-

"""
Tạo ra một ví mới cho Thợ mỏ (Miner) hoặc Người dùng thông thường.
"""

import os, sys

project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from sok.wallet import Wallet
except ImportError as e:
    print(f"[LỖI] Không thể import từ thư viện 'sok'. Lỗi: {e}")
    sys.exit(1)

MINER_WALLET_FILE = "resilient_miner_wallet.pem"

print("--- Công cụ tạo Ví cho Thợ mỏ/Người dùng Sokchain ---")

if os.path.exists(MINER_WALLET_FILE):
    print(f"\n[THÔNG BÁO] Tệp ví '{MINER_WALLET_FILE}' đã tồn tại. Bỏ qua việc tạo mới.")
    sys.exit(0)

print(f"\nĐang tạo ví mới và lưu vào '{MINER_WALLET_FILE}'...")
miner_wallet = Wallet()
miner_address = miner_wallet.get_address()

with open(MINER_WALLET_FILE, "w", encoding='utf-8') as f:
    f.write(miner_wallet.get_private_key_pem())

print("\n" + "="*70)
print("✅ HOÀN TẤT!")
print(f"\n1. Đã lưu khóa riêng tư của bạn vào tệp: '{MINER_WALLET_FILE}'")
print(f"\n2. ĐỊA CHỈ VÍ (để nhận SOK và được thêm vào whitelist) là:")
print(f"\n   >> {miner_address} <<\n")
print("   Hãy cung cấp địa chỉ này cho quản trị viên mạng lưới.")
print("="*70)
