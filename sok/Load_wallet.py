#!/usr/bin/env python3
# smart_wallet.py - Ví dòng lệnh Thông minh và Toàn diện

# -*- coding: utf-8 -*-

"""
Giao diện dòng lệnh (CLI) "thông minh" để tương tác với mạng lưới Sokchain.

Tính năng:
- Bảng điều khiển (Dashboard) hiển thị thông tin thời gian thực.
- Gửi tiền (tạo và phát hành giao dịch).
- Kiểm tra số dư của bất kỳ địa chỉ ví nào.
- Tự động tìm kiếm node mạng tốt nhất để tương tác.
"""

import os
import sys
import requests
import json
import logging
import time
from typing import List, Dict, Any, Optional

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
NODE_HEALTH_CHECK_TIMEOUT = 4  # Giây

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SmartWallet] [%(levelname)s] - %(message)s')

def load_all_known_nodes() -> List[str]:
    """Tải danh sách tất cả các node tiềm năng từ các tệp cấu hình."""
    nodes = []
    if os.path.exists(LIVE_NETWORK_CONFIG_FILE):
        try:
            with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f:
                nodes.extend(json.load(f).get("active_nodes", []))
        except Exception: pass
    
    if os.path.exists(BOOTSTRAP_CONFIG_FILE):
        try:
            with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                peers = json.load(f).get("trusted_bootstrap_peers", {})
                nodes.extend([p.get("last_known_address") for p in peers.values() if p.get("last_known_address")])
        except Exception: pass
        
    return sorted(list(set(nodes)))

class SmartWalletCLI:
    def __init__(self, wallet_file: str):
        self.wallet = self._load_or_create_wallet(wallet_file)
        self.active_node: Optional[str] = None
        self.find_and_set_best_node()

    def _load_or_create_wallet(self, wallet_file: str) -> Wallet:
        """Tải ví từ tệp hoặc tạo một ví mới nếu tệp không tồn tại."""
        if os.path.exists(wallet_file):
            logging.info(f"Đang tải ví từ: {wallet_file}")
            with open(wallet_file, 'r', encoding='utf-8') as f:
                return Wallet(private_key_pem=f.read())
        else:
            print(f"Không tìm thấy tệp ví '{wallet_file}'.")
            choice = input("Bạn có muốn tạo một ví mới và lưu vào đây không? (yes/no): ").lower()
            if choice != 'yes':
                print("Đã hủy. Tạm biệt!")
                sys.exit(0)
            
            logging.warning(f"Đang tạo một ví mới...")
            wallet = Wallet()
            with open(wallet_file, 'w', encoding='utf-8') as f:
                f.write(wallet.get_private_key_pem())
            print("-" * 50)
            print(f"✅ Đã tạo ví mới và lưu vào '{wallet_file}'.")
            print(f"ĐỊA CHỈ VÍ MỚI CỦA BẠN (để nhận SOK):")
            print(f" >> {wallet.get_address()} << ")
            print("-" * 50)
            return wallet

    def find_and_set_best_node(self):
        """Quét mạng và chọn node tốt nhất để tương tác."""
        print("\n🔄 Đang tìm kiếm node mạng tốt nhất...")
        known_nodes = load_all_known_nodes()
        if not known_nodes:
            logging.critical("Không tìm thấy node nào trong cấu hình. Không thể kết nối mạng lưới.")
            sys.exit(1)

        healthy_nodes = []
        for node_url in known_nodes:
            try:
                response = requests.get(f'{node_url}/chain/stats', timeout=NODE_HEALTH_CHECK_TIMEOUT)
                if response.status_code == 200:
                    stats = response.json()
                    healthy_nodes.append({"url": node_url, "block_height": stats.get('block_height', -1)})
            except requests.exceptions.RequestException:
                continue

        if not healthy_nodes:
            logging.critical("Không tìm thấy node nào đang hoạt động. Vui lòng kiểm tra lại mạng lưới.")
            sys.exit(1)

        sorted_nodes = sorted(healthy_nodes, key=lambda x: x['block_height'], reverse=True)
        self.active_node = sorted_nodes[0]['url']
        print(f"✅ Kết nối thành công tới node: {self.active_node}")

    def _make_api_request(self, method: str, endpoint: str, **kwargs) -> Any:
        """Thực hiện một yêu cầu API tới node đang hoạt động, có xử lý lỗi."""
        if not self.active_node:
            self.find_and_set_best_node()
            if not self.active_node: return None

        url = f"{self.active_node}{endpoint}"
        try:
            if method.upper() == 'GET':
                response = requests.get(url, timeout=10, **kwargs)
            elif method.upper() == 'POST':
                response = requests.post(url, timeout=10, **kwargs)
            else:
                raise ValueError(f"Phương thức không được hỗ trợ: {method}")

            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            logging.error(f"Lỗi kết nối tới node {self.active_node}: {e}")
            self.active_node = None
            return None
        except json.JSONDecodeError:
            logging.error("Phản hồi từ node không phải là JSON hợp lệ.")
            return None

    def refresh_dashboard(self):
        """Lấy và hiển thị thông tin tổng quan."""
        print("\n⟳ Đang làm mới dữ liệu...")
        my_address = self.wallet.get_address()
        balance_data = self._make_api_request('GET', f"/balance/{my_address}")
        stats_data = self._make_api_request('GET', '/chain/stats')

        print("\n" + "="*50)
        print("--- BẢNG ĐIỀU KHIỂN VÍ SOK (SOK WALLET DASHBOARD) ---")
        print("-" * 50)

        if balance_data:
            print(f"  Số dư của bạn:   {balance_data.get('balance', 'N/A'):,.8f} SOK")
        else:
            print("  Số dư của bạn:   Không thể tải")

        if stats_data:
            print(f"  Tổng cung:        {stats_data.get('total_supply', 'N/A'):,.8f} SOK")
            print(f"  Chiều cao khối:   {stats_data.get('block_height', 'N/A')}")
            print(f"  Node hoạt động:   {stats_data.get('peer_count', 'N/A')}")
        else:
            print("  Tổng cung:        Không thể tải")
            print("  Chiều cao khối:   Không thể tải")
            print("  Node hoạt động:   Không thể tải")

        print("="*50)

    def check_other_wallet(self):
        """Kiểm tra số dư của một địa chỉ ví khác."""
        other_address = input("\nNhập địa chỉ ví cần kiểm tra: ").strip()
        if not other_address:
            print("Địa chỉ không được để trống."); return

        print(f"Đang kiểm tra số dư cho: {other_address}...")
        data = self._make_api_request('GET', f"/balance/{other_address}")
        
        if data:
            print("-" * 40)
            print(f"  Địa chỉ: {data.get('address')}")
            print(f"  Số dư:   {data.get('balance', 'Không xác định'):,.8f} SOK")
            print("-" * 40)
        else:
            print("❌ Không thể lấy thông tin số dư. Vui lòng thử lại.")

    def send_transaction(self):
        """Hướng dẫn người dùng tạo và gửi một giao dịch."""
        print("\n--- 💸 TẠO GIAO DỊCH MỚI ---")
        print(f"Ví gửi: {self.wallet.get_address()}")
        
        recipient = input("Nhập địa chỉ người nhận: ").strip()
        if not recipient:
            print("Địa chỉ người nhận không được để trống."); return

        try:
            amount_str = input("Nhập số tiền muốn gửi: ")
            amount = float(amount_str)
        except ValueError:
            print("Lỗi: Số tiền phải là một con số."); return
        
        # --- ĐÂY LÀ PHẦN SỬA LỖI QUAN TRỌNG NHẤT ---
        # 1. Tạo đối tượng Transaction đầy đủ thông tin ngay từ đầu
        tx = Transaction(
            sender_public_key_pem=self.wallet.get_public_key_pem(),
            recipient_address=recipient,
            amount=amount,
            sender_address=self.wallet.get_address() # Cung cấp sender_address rõ ràng
        )
        
        # 2. Ký vào giao dịch
        tx.sign(self.wallet.private_key)
        
        print("\nĐang gửi giao dịch đến mạng lưới...")
        # 3. Gửi đi dictionary đã được chuẩn hóa
        response_data = self._make_api_request(
            'POST',
            '/transactions/new',
            json=tx.to_dict()
        )
        
        if response_data:
            print("✅ Giao dịch đã được gửi thành công!")
            print(f"   Thông điệp từ node: {response_data.get('message')}")
        else:
            print("❌ Gửi giao dịch thất bại. Vui lòng kiểm tra kết nối và thử lại.")

    def run(self):
        """Vòng lặp chính của giao diện ví."""
        print("\n--- Chào mừng đến với Ví Thông minh SOK! ---")
        if self.wallet:
            self.refresh_dashboard()
        else:
            return # Thoát nếu người dùng hủy tạo ví
        
        while True:
            print("\nChọn một hành động:")
            print("  1. Làm mới Bảng điều khiển")
            print("  2. Gửi SOK")
            print("  3. Kiểm tra số dư của ví khác")
            print("  4. Hiển thị địa chỉ của tôi")
            print("  5. Thoát")
            
            choice = input("> ").strip()
            
            if choice == '1':
                self.refresh_dashboard()
            elif choice == '2':
                self.send_transaction()
            elif choice == '3':
                self.check_other_wallet()
            elif choice == '4':
                print("\n" + "-"*20)
                print("Địa chỉ ví của bạn là:")
                print(f" >> {self.wallet.get_address()} << ")
                print("Bạn có thể chia sẻ địa chỉ này để nhận SOK.")
                print("-" * 20)
            elif choice == '5':
                print("Tạm biệt!")
                break
            else:
                print("Lựa chọn không hợp lệ, vui lòng thử lại.")

if __name__ == "__main__":
    default_wallet_file = "prime_agent_wallet.pem"
    wallet_path = input(f"Nhập đường dẫn đến tệp ví (để trống sẽ dùng '{default_wallet_file}'): ").strip()
    if not wallet_path:
        wallet_path = default_wallet_file

    try:
        cli = SmartWalletCLI(wallet_file=wallet_path)
        cli.run()
    except (KeyboardInterrupt):
        print("\nĐã thoát khỏi ví.")
    except Exception as e:
        logging.critical(f"Một lỗi nghiêm trọng đã xảy ra: {e}", exc_info=True)
