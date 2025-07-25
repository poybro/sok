#!/usr/bin/env python3
# wallet_cli.py - Giao diện dòng lệnh cho Ví

# -*- coding: utf-8 -*-

"""
Giao diện dòng lệnh (CLI) để quản lý ví:
- Kiểm tra số dư của ví hiện tại.
- Kiểm tra số dư của bất kỳ địa chỉ ví nào khác.
- Gửi tiền (tạo và phát hành giao dịch).

Chạy song song với thợ mỏ.
"""

import os
import sys
import requests
import json
import logging
from typing import List, Dict, Any

# Thêm đường dẫn dự án để có thể import từ 'sok'
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from sok.wallet import Wallet
    from sok.transaction import Transaction
except ImportError as e:
    print(f"[LỖI] Không thể import thư viện cần thiết: {e}")
    sys.exit(1)

# --- CẤU HÌNH ---
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"

# Cấu hình logging cơ bản
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [WalletCLI] [%(levelname)s] - %(message)s'
)

def load_nodes_from_config() -> List[str]:
    """
    Tải danh sách các node đang hoạt động.
    Ưu tiên tệp 'live' do Ranger tạo, nếu không có thì dùng tệp bootstrap tĩnh.
    (Hàm này được sao chép từ resilient_miner để đảm bảo tính nhất quán)
    """
    if os.path.exists(LIVE_NETWORK_CONFIG_FILE):
        try:
            with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                active_nodes = data.get("active_nodes", [])
                if active_nodes:
                    return active_nodes
        except Exception as e:
            logging.error(f"Lỗi khi đọc tệp bản đồ mạng: {e}.")

    if os.path.exists(BOOTSTRAP_CONFIG_FILE):
        try:
            with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                peers = data.get("trusted_bootstrap_peers", {})
                if peers:
                    return [p.get("last_known_address") for p in peers.values() if p.get("last_known_address")]
        except Exception as e:
            logging.error(f"Lỗi khi đọc tệp cấu hình bootstrap: {e}.")
    
    return []

class WalletCLI:
    def __init__(self, wallet_file: str):
        self.wallet = self._load_or_create_wallet(wallet_file)
        self.nodes = load_nodes_from_config()
        if not self.nodes:
            logging.critical("Không tìm thấy node nào đang hoạt động. Không thể kết nối với mạng lưới.")
            sys.exit(1)
        # Tạm thời chỉ dùng node đầu tiên tìm được
        self.active_node = self.nodes[0]
        logging.info(f"Đang sử dụng node: {self.active_node}")

    def _load_or_create_wallet(self, wallet_file: str) -> Wallet:
        """Tải ví từ tệp hoặc tạo một ví mới nếu tệp không tồn tại."""
        if os.path.exists(wallet_file):
            logging.info(f"Đang tải ví từ: {wallet_file}")
            with open(wallet_file, 'r', encoding='utf-8') as f:
                return Wallet(private_key_pem=f.read())
        else:
            logging.warning(f"Không tìm thấy tệp ví '{wallet_file}'. Đang tạo một ví mới...")
            wallet = Wallet()
            private_key_pem = wallet.get_private_key_pem()
            with open(wallet_file, 'w', encoding='utf-8') as f:
                f.write(private_key_pem)
            logging.info(f"Đã tạo ví mới và lưu vào '{wallet_file}'.")
            logging.info(f"ĐỊA CHỈ VÍ MỚI CỦA BẠN: {wallet.get_address()}")
            return wallet

    def _make_api_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Thực hiện một yêu cầu API tới node đang hoạt động."""
        url = f"{self.active_node}{endpoint}"
        try:
            if method.upper() == 'GET':
                response = requests.get(url, timeout=10, **kwargs)
            elif method.upper() == 'POST':
                response = requests.post(url, timeout=10, **kwargs)
            else:
                raise ValueError(f"Phương thức không được hỗ trợ: {method}")

            response.raise_for_status()  # Ném lỗi nếu mã trạng thái là 4xx hoặc 5xx
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Lỗi kết nối tới node {self.active_node}: {e}")
            return None
        except json.JSONDecodeError:
            logging.error("Phản hồi từ node không phải là JSON hợp lệ.")
            return None

    def check_balance(self, address: str):
        """Kiểm tra và hiển thị số dư cho một địa chỉ ví cụ thể."""
        print(f"\nĐang kiểm tra số dư cho địa chỉ: {address}...")
        data = self._make_api_request('GET', f"/balance", params={'address': address})
        if data:
            balance = data.get('balance', 'Không xác định')
            print("-" * 40)
            print(f"  Số dư: {balance}")
            print("-" * 40)
        else:
            print("Không thể lấy thông tin số dư.")

    def send_transaction(self):
        """Hướng dẫn người dùng tạo và gửi một giao dịch."""
        print("\n--- Tạo Giao Dịch Mới ---")
        sender = self.wallet.get_address()
        print(f"Ví gửi: {sender}")
        
        recipient = input("Nhập địa chỉ người nhận: ").strip()
        if not recipient:
            print("Địa chỉ người nhận không được để trống.")
            return

        try:
            amount = float(input("Nhập số tiền muốn gửi: "))
            fee = float(input("Nhập phí giao dịch (gợi ý: 0.1): "))
        except ValueError:
            print("Số tiền và phí phải là số.")
            return

        tx = Transaction(sender, recipient, amount, fee=fee)
        self.wallet.sign_transaction(tx)
        
        print("\nĐang gửi giao dịch đến mạng lưới...")
        response_data = self._make_api_request(
            'POST',
            '/transactions/new',
            json=tx.to_dict()
        )
        
        if response_data:
            print("✅ Giao dịch đã được gửi thành công!")
            print(f"   Message từ node: {response_data.get('message')}")
        else:
            print("❌ Gửi giao dịch thất bại.")

    def run(self):
        """Vòng lặp chính của giao diện CLI."""
        print("\n--- Giao diện Ví SOK (SOK Wallet CLI) ---")
        print(f"Địa chỉ ví của bạn: {self.wallet.get_address()}")
        
        while True:
            print("\nChọn một hành động:")
            print("  1. Hiển thị số dư của tôi")
            print("  2. Kiểm tra số dư của ví khác")
            print("  3. Gửi tiền")
            print("  4. Thoát")
            
            choice = input("> ").strip()
            
            if choice == '1':
                self.check_balance(self.wallet.get_address())
            elif choice == '2':
                other_address = input("Nhập địa chỉ ví cần kiểm tra: ").strip()
                if other_address:
                    self.check_balance(other_address)
                else:
                    print("Địa chỉ không hợp lệ.")
            elif choice == '3':
                self.send_transaction()
            elif choice == '4':
                print("Tạm biệt!")
                break
            else:
                print("Lựa chọn không hợp lệ, vui lòng thử lại.")

if __name__ == "__main__":
    # Sử dụng ví của thợ mỏ làm mặc định, hoặc bạn có thể tạo ví khác
    default_wallet_file = "resilient_miner_wallet.pem"
    wallet_path = input(f"Nhập đường dẫn đến tệp ví (mặc định: {default_wallet_file}): ").strip()
    if not wallet_path:
        wallet_path = default_wallet_file

    cli = WalletCLI(wallet_file=wallet_path)
    cli.run()
