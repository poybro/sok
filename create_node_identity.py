#!/usr/bin/env python3
# create_node_identity.py
# -*- coding: utf-8 -*-

"""
Tạo ra một danh tính mật mã duy nhất cho một Node.
CHỈ CHẠY MỘT LẦN DUY NHẤT TRÊN MỖI MÁY CHỦ SẼ CHẠY NODE.
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

NODE_WALLET_FILE = "node_wallet.pem"

print("--- Công cụ tạo Danh tính (ID) cho Node Sokchain ---")

if os.path.exists(NODE_WALLET_FILE):
    choice = input(f"\n[CẢNH BÁO] Tệp ví '{NODE_WALLET_FILE}' đã tồn tại.\nBạn có muốn ghi đè và tạo một danh tính mới không? (yes/no): ")
    if choice.lower() != 'yes':
        print("Đã hủy bỏ. Giữ lại danh tính hiện có.")
        sys.exit(0)

print("\nĐang tạo cặp khóa mới cho Node...")
node_wallet = Wallet()
new_node_id = node_wallet.get_address()

with open(NODE_WALLET_FILE, "w", encoding='utf-8') as f:
    f.write(node_wallet.get_private_key_pem())

print("\n" + "="*70)
print("✅ HOÀN TẤT!")
print(f"\n1. Đã lưu khóa riêng tư của Node vào tệp: '{NODE_WALLET_FILE}'")
print(f"   (Hãy giữ an toàn cho tệp này và không chia sẻ nó!)")
print(f"\n2. DANH TÍNH NODE (NODE ID) của bạn là (để chia sẻ):")
print(f"\n   >> {new_node_id} <<\n")
print("   Hãy cung cấp ID này và địa chỉ IP:Port cho quản trị viên mạng lưới.")
print("="*70)
