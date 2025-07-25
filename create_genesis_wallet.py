# create_genesis_wallet.py
# -*- coding: utf-8 -*-
import os
from sok.wallet import Wallet
from sok.utils import Config

GENESIS_WALLET_FILE = "genesis_wallet.pem"

if os.path.exists(GENESIS_WALLET_FILE):
    print(f"Tệp ví '{GENESIS_WALLET_FILE}' đã tồn tại.")
    with open(GENESIS_WALLET_FILE, 'r', encoding='utf-8') as f:
        wallet = Wallet(private_key_pem=f.read())
    if wallet.get_address() == Config.FOUNDER_ADDRESS:
        print("Địa chỉ ví khớp với cấu hình. Hoàn tất.")
    else:
        print("LỖI: Địa chỉ ví không khớp với FOUNDER_ADDRESS trong sok/utils.py!")
    exit()

print("Đang tạo Ví Sáng thế...")
wallet = Wallet()
address = wallet.get_address()

# Cập nhật tệp cấu hình
utils_path = os.path.join('sok', 'utils.py')
with open(utils_path, 'r', encoding='utf-8') as f:
    lines = f.readlines()
with open(utils_path, 'w', encoding='utf-8') as f:
    for line in lines:
        if line.strip().startswith('FOUNDER_ADDRESS ='):
            f.write(f"    FOUNDER_ADDRESS = \"{address}\"\n")
            print(f"Đã cập nhật FOUNDER_ADDRESS trong {utils_path}")
        else:
            f.write(line)

with open(GENESIS_WALLET_FILE, "w", encoding='utf-8') as f:
    f.write(wallet.get_private_key_pem())

print(f"✅ Đã tạo ví Sáng thế thành công. Khóa riêng tư đã lưu vào '{GENESIS_WALLET_FILE}'.")
print(f"   Địa chỉ: {address}")
