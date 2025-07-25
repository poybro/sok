#!/usr/bin/env python3
# smart_wallet_interactive.py - Ví thông minh SOKchain với giao diện tương tác
# Phiên bản này được thiết kế để trực quan và dễ sử dụng cho người dùng cuối.

# -*- coding: utf-8 -*-

import os
import sys
import requests
import json
import time
from typing import Optional

# Thư viện để tạo giao diện màu sắc
try:
    import colorama
    from colorama import Fore, Style
    colorama.init(autoreset=True)
except ImportError:
    print("Thư viện 'colorama' chưa được cài đặt. Giao diện sẽ không có màu.")
    print("Để có trải nghiệm tốt nhất, vui lòng chạy: pip install colorama")
    # Tạo các lớp giả để chương trình không bị lỗi
    class Fore:
        GREEN = RED = YELLOW = CYAN = ""
    class Style:
        BRIGHT = RESET_ALL = ""

# --- THÊM ĐƯỜNG DẪN DỰ ÁN ---
project_root = os.path.abspath(os.path.dirname(__file__))
if os.path.join(project_root, 'sok') not in sys.path:
    sys.path.insert(0, project_root)

try:
    from sok.wallet import Wallet, sign_data
    from sok.transaction import Transaction
except ImportError:
    print(f"{Fore.RED}LỖI: Không thể import thư viện 'sok'. Vui lòng kiểm tra cấu trúc thư mục.")
    sys.exit(1)

# --- CẤU HÌNH ---
DEFAULT_WALLET_FILE = "my_smart_wallet.pem"
INTELLIGENCE_AGENT_URL = "http://127.0.0.1:8080" # URL của NetworkIntelligenceAgent
REQUEST_TIMEOUT = 5

class InteractiveWallet:
    """Quản lý ví và cung cấp các hàm giao diện người dùng."""
    def __init__(self, wallet_file: str):
        self.wallet_file = wallet_file
        self.wallet: Optional[Wallet] = None
        self.load_wallet()

    def load_wallet(self):
        try:
            with open(self.wallet_file, 'r', encoding='utf-8') as f:
                self.wallet = Wallet(private_key_pem=f.read())
        except FileNotFoundError:
            print(f"{Fore.YELLOW}Không tìm thấy tệp ví '{self.wallet_file}'.")
            self.wallet = None
        except Exception as e:
            print(f"{Fore.RED}Lỗi không xác định khi tải ví: {e}")
            self.wallet = None

    def _make_request(self, method: str, endpoint: str, json_data: Optional[dict] = None) -> Optional[dict]:
        """Hàm trợ giúp để gửi yêu cầu đến Agent một cách an toàn."""
        url = f"{INTELLIGENCE_AGENT_URL}{endpoint}"
        try:
            print(f"{Fore.YELLOW}Đang kết nối đến Dịch vụ Tình báo...")
            if method.upper() == 'GET':
                response = requests.get(url, timeout=REQUEST_TIMEOUT)
            else:
                response = requests.post(url, json=json_data, timeout=REQUEST_TIMEOUT)

            if response.status_code >= 400:
                print(f"{Fore.RED}Lỗi từ Dịch vụ Tình báo (Mã: {response.status_code}):")
                print(f"  -> {response.json().get('error', response.text)}")
                return None
            return response.json()
        except requests.exceptions.ConnectionError:
            print(f"{Fore.RED}\nLỖI KẾT NỐI: Không thể kết nối đến {INTELLIGENCE_AGENT_URL}.")
            print("Vui lòng đảm bảo NetworkIntelligenceAgent đang chạy.")
            return None
        except Exception as e:
            print(f"{Fore.RED}Lỗi mạng không xác định: {e}")
            return None

    def handle_get_balance(self):
        """Xử lý logic và hiển thị số dư."""
        clear_screen()
        print_header("KIỂM TRA SỐ DƯ")
        response_data = self._make_request('GET', f'/wallet/{self.wallet.get_address()}/balance')
        if response_data and 'balance' in response_data:
            balance = response_data['balance']
            print(f"\n{Style.BRIGHT}Số dư hiện tại của bạn là:")
            print(f"{Fore.GREEN}{balance:.8f} SOK")
        else:
            print(f"{Fore.RED}Không thể lấy thông tin số dư.")
        pause_for_user()

    def handle_send_sok(self):
        """Xử lý logic và giao diện để gửi SOK."""
        clear_screen()
        print_header("GỬI SOK")
        recipient = input(f"{Fore.YELLOW}Nhập địa chỉ ví người nhận: {Style.RESET_ALL}").strip()
        if not recipient:
            print(f"{Fore.RED}Địa chỉ người nhận không được để trống.")
            pause_for_user(); return

        while True:
            try:
                amount_str = input(f"{Fore.YELLOW}Nhập số lượng SOK muốn gửi: {Style.RESET_ALL}").strip()
                amount = float(amount_str)
                if amount <= 0:
                    print(f"{Fore.RED}Số lượng phải là một số dương.")
                    continue
                break
            except ValueError:
                print(f"{Fore.RED}Số lượng không hợp lệ. Vui lòng nhập một con số.")

        print("\n--- XÁC NHẬN GIAO DỊCH ---")
        print(f"  Gửi:   {Fore.CYAN}{amount} SOK")
        print(f"  Đến:   {Fore.CYAN}{recipient[:25]}...")
        confirm = input(f"{Fore.YELLOW}Bạn có chắc chắn muốn thực hiện giao dịch này? (y/n): {Style.RESET_ALL}").lower()

        if confirm != 'y':
            print("Đã hủy giao dịch.")
            pause_for_user(); return

        try:
            tx = Transaction(self.wallet.get_public_key_pem(), recipient, amount)
            tx.signature = sign_data(self.wallet.private_key, tx.calculate_hash())
            response_data = self._make_request('POST', '/transactions/new', json_data=tx.to_dict())
            if response_data:
                print(f"\n{Fore.GREEN}Phản hồi từ mạng lưới: {response_data.get('message', 'Thành công!')}")
        except Exception as e:
            print(f"{Fore.RED}Lỗi khi tạo giao dịch cục bộ: {e}")
        
        pause_for_user()

    def handle_display_address(self):
        """Hiển thị địa chỉ ví."""
        clear_screen()
        print_header("ĐỊA CHỈ VÍ CỦA BẠN")
        print("Sử dụng địa chỉ dưới đây để nhận SOK từ người khác.")
        print(f"\n{Fore.CYAN}{Style.BRIGHT}{self.wallet.get_address()}")
        pause_for_user()

def create_wallet_flow(wallet_file: str):
    """Quy trình hướng dẫn người dùng tạo ví mới."""
    clear_screen()
    print_header("CHÀO MỪNG ĐẾN VỚI VÍ SOKCHAIN")
    print(f"Không tìm thấy tệp ví '{wallet_file}'.")
    choice = input(f"{Fore.YELLOW}Bạn có muốn tạo một ví mới ngay bây giờ không? (y/n): {Style.RESET_ALL}").lower()
    if choice == 'y':
        try:
            new_wallet = Wallet()
            with open(wallet_file, 'w', encoding='utf-8') as f:
                f.write(new_wallet.get_private_key_pem())
            print(f"\n{Fore.GREEN}✅ TẠO VÍ THÀNH CÔNG!{Style.RESET_ALL}")
            print(f"   Đã lưu khóa riêng tư vào: '{wallet_file}'")
            print(f"   Địa chỉ công khai của bạn: {Fore.CYAN}{new_wallet.get_address()}")
            print(f"\n{Fore.RED}{Style.BRIGHT}*** QUAN TRỌNG: Hãy giữ an toàn cho tệp '{wallet_file}'! ***")
            pause_for_user()
            return True
        except Exception as e:
            print(f"{Fore.RED}Lỗi khi tạo ví: {e}")
            pause_for_user()
            return False
    else:
        print("Bạn cần tạo ví để sử dụng các chức năng. Chương trình sẽ thoát.")
        time.sleep(2)
        return False

def print_header(title: str):
    """In tiêu đề cho mỗi màn hình."""
    print(f"{Fore.GREEN}{Style.BRIGHT}{'='*50}")
    print(f"| {title:^46} |")
    print(f"{'='*50}{Style.RESET_ALL}")

def display_menu():
    """Hiển thị menu chính."""
    clear_screen()
    print_header("VÍ THÔNG MINH SOKCHAIN - MENU CHÍNH")
    print(f"{Fore.GREEN}1. {Style.RESET_ALL}Kiểm tra số dư")
    print(f"{Fore.GREEN}2. {Style.RESET_ALL}Gửi SOK")
    print(f"{Fore.GREEN}3. {Style.RESET_ALL}Hiển thị địa chỉ ví của tôi")
    print(f"{Fore.RED}0. {Style.RESET_ALL}Thoát chương trình")
    print("-" * 50)

def clear_screen():
    """Xóa màn hình console."""
    os.system('cls' if os.name == 'nt' else 'clear')

def pause_for_user():
    """Tạm dừng chương trình chờ người dùng nhấn Enter."""
    input(f"\n{Fore.YELLOW}Nhấn Enter để quay lại menu chính...{Style.RESET_ALL}")

def main():
    """Hàm chính điều khiển toàn bộ ứng dụng."""
    if not os.path.exists(DEFAULT_WALLET_FILE):
        if not create_wallet_flow(DEFAULT_WALLET_FILE):
            return

    wallet_app = InteractiveWallet(DEFAULT_WALLET_FILE)

    while True:
        display_menu()
        choice = input(f"{Fore.YELLOW}Chọn một chức năng (0-3): {Style.RESET_ALL}").strip()
        
        if choice == '1':
            wallet_app.handle_get_balance()
        elif choice == '2':
            wallet_app.handle_send_sok()
        elif choice == '3':
            wallet_app.handle_display_address()
        elif choice == '0':
            print("Cảm ơn bạn đã sử dụng Ví SOKchain. Tạm biệt!")
            break
        else:
            print(f"{Fore.RED}Lựa chọn không hợp lệ. Vui lòng chọn một số từ 0 đến 3.")
            time.sleep(2)

if __name__ == "__main__":
    main()
