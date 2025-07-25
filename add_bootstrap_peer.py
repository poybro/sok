#!/usr/bin/env python3
# add_bootstrap_peer.py - Công cụ thêm Peer vào cấu hình Bootstrap

# -*- coding: utf-8 -*-

"""
Một công cụ dòng lệnh an toàn để thêm hoặc cập nhật các node
trong tệp 'bootstrap_config.json'.

- Đọc tệp cấu hình hiện có.
- Hỏi người dùng thông tin về node mới (ID, IP, Port).
- Kiểm tra trùng lặp Node ID.
- Cập nhật và ghi lại tệp JSON một cách chính xác.
"""

import os
import sys
import json

# --- CẤU HÌNH ---
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"

def load_or_create_bootstrap_config() -> dict:
    """Tải tệp bootstrap. Nếu không có hoặc bị lỗi, tạo một cấu trúc mới."""
    if os.path.exists(BOOTSTRAP_CONFIG_FILE):
        try:
            with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                # Đảm bảo cấu trúc cơ bản tồn tại
                if "trusted_bootstrap_peers" not in data:
                    data["trusted_bootstrap_peers"] = {}
                return data
        except json.JSONDecodeError:
            print(f"⚠️ CẢNH BÁO: Tệp '{BOOTSTRAP_CONFIG_FILE}' bị lỗi định dạng JSON.")
            choice = input("Bạn có muốn tạo một tệp mới không? (Hành động này sẽ xóa nội dung cũ) (yes/no): ").lower()
            if choice == 'yes':
                return {"trusted_bootstrap_peers": {}}
            else:
                print("❌ Đã hủy. Vui lòng sửa tệp JSON thủ công.")
                sys.exit(1)
    else:
        # Nếu tệp không tồn tại, tạo cấu trúc rỗng
        return {"trusted_bootstrap_peers": {}}

def save_bootstrap_config(data: dict):
    """Lưu dữ liệu vào tệp bootstrap một cách an toàn."""
    try:
        # Ghi vào tệp tạm trước để đảm bảo an toàn
        temp_file = BOOTSTRAP_CONFIG_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            # indent=2 giúp tệp dễ đọc hơn
            json.dump(data, f, indent=2)
        # Thay thế tệp cũ bằng tệp tạm một cách "nguyên tử"
        os.replace(temp_file, BOOTSTRAP_CONFIG_FILE)
        print(f"\n✅ Đã cập nhật thành công tệp '{BOOTSTRAP_CONFIG_FILE}'.")
    except Exception as e:
        print(f"\n❌ LỖI: Không thể lưu tệp cấu hình. Lỗi: {e}")

def main():
    """Hàm chính của công cụ."""
    print("--- 🔧 Công cụ Cập nhật Bootstrap Peers ---")
    
    # Tải dữ liệu hiện có hoặc tạo mới
    config_data = load_or_create_bootstrap_config()
    peers = config_data.get("trusted_bootstrap_peers", {})

    # Lấy thông tin từ người dùng
    print("\nNhập thông tin cho node mới:")
    new_node_id = input("  - Node ID: ").strip()
    new_node_ip = input("  - Địa chỉ IP (ví dụ: 192.168.1.100): ").strip()
    new_node_port_str = input("  - Port (ví dụ: 5000): ").strip()

    # Kiểm tra dữ liệu đầu vào
    if not all([new_node_id, new_node_ip, new_node_port_str]):
        print("\n❌ Lỗi: Tất cả các trường thông tin là bắt buộc.")
        return
        
    try:
        port = int(new_node_port_str)
    except ValueError:
        print("\n❌ Lỗi: Port phải là một con số.")
        return

    # Tạo địa chỉ chuẩn
    new_address = f"http://{new_node_ip}:{port}"

    # Kiểm tra xung đột (Trái tim của việc "không ảnh hưởng cấu trúc cũ")
    if new_node_id in peers:
        print("\n⚠️ THÔNG BÁO: Node ID này đã tồn tại trong cấu hình.")
        print(f"   Địa chỉ hiện tại là: {peers[new_node_id].get('last_known_address')}")
        update_choice = input(f"   Bạn có muốn cập nhật địa chỉ thành '{new_address}' không? (yes/no): ").lower()
        if update_choice != 'yes':
            print("ℹ️ Đã hủy bỏ, không có thay đổi nào được thực hiện.")
            return

    # Thêm hoặc cập nhật thông tin node
    peers[new_node_id] = {
        "last_known_address": new_address
    }
    
    # Đặt lại dữ liệu vào cấu trúc chính và lưu
    config_data["trusted_bootstrap_peers"] = peers
    save_bootstrap_config(config_data)

    print("\n--- Tóm tắt thay đổi ---")
    print(f"Node ID: {new_node_id}")
    print(f"Địa chỉ: {new_address}")
    print("------------------------")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n\nĐã hủy bởi người dùng.")
