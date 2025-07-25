#!/usr/bin/env python3
# run_seeder_node.py - Node Hạt giống cho Mạng lưới Sokchain

# -*- coding: utf-8 -*-

"""
Node Hạt giống (Seeder Node).
Nhiệm vụ duy nhất của node này là cung cấp một danh sách các peer đang hoạt động
cho bất kỳ client nào kết nối tới.

- Bên trong, nó chạy một phiên bản của Ranger Agent để liên tục làm mới
  danh sách các peer đang hoạt động.
- Nó cung cấp một API endpoint duy nhất: /get_active_peers
"""

import os
import sys
import json
import time
import logging
import threading
from flask import Flask, jsonify
from waitress import serve

# --- THÊM ĐƯỜNG DẪN DỰ ÁN ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# Tái sử dụng các hàm từ Ranger Agent
try:
    from run_ranger_agent import run_deep_discovery_cycle, load_bootstrap_peers
except ImportError:
    print("LỖI: Không thể import từ 'run_ranger_agent.py'. Đảm bảo tệp đó tồn tại.")
    sys.exit(1)

# --- CẤU HÌNH ---
# Seeder cần có một bản bootstrap riêng để bắt đầu, nhưng nó sẽ không phân phối bản này.
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"
# Seeder sẽ đọc kết quả của chính nó từ đây
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json" 
SEEDER_PORT = 8080 # Một cổng riêng biệt cho Seeder
REFRESH_INTERVAL_SECONDS = 5 * 60 # Quét lại mạng mỗi 5 phút

logging.basicConfig(level=logging.INFO, format='%(asctime)s [SeederNode] [%(levelname)s] - %(message)s')

# --- BỘ NÃO CỦA SEEDER ---
class SeederService:
    def __init__(self):
        self.is_running = True
        self.bootstrap_peers = load_bootstrap_peers()
        if not self.bootstrap_peers:
            logging.critical("Seeder không thể hoạt động nếu không có bootstrap_config.json ban đầu.")
            sys.exit(1)

        # Bắt đầu luồng khám phá trong nền
        self.discovery_thread = threading.Thread(target=self.run_discovery_loop, daemon=True)
        self.discovery_thread.start()

    def run_discovery_loop(self):
        """Liên tục chạy chu kỳ khám phá của Ranger."""
        logging.info("Luồng khám phá của Seeder đã bắt đầu.")
        while self.is_running:
            try:
                # Chạy logic quét mạng
                run_deep_discovery_cycle(self.bootstrap_peers)
                logging.info(f"Chu kỳ khám phá của Seeder hoàn tất. Sẽ chạy lại sau {REFRESH_INTERVAL_SECONDS} giây.")
                time.sleep(REFRESH_INTERVAL_SECONDS)
            except Exception as e:
                logging.error(f"Lỗi trong luồng khám phá của Seeder: {e}", exc_info=True)
                time.sleep(60)

    def get_active_peers(self) -> list:
        """Đọc và trả về danh sách các peer từ tệp live_network_nodes.json."""
        if os.path.exists(LIVE_NETWORK_CONFIG_FILE):
            try:
                with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    return data.get("active_nodes", [])
            except (IOError, json.JSONDecodeError) as e:
                logging.error(f"Không thể đọc hoặc phân tích tệp bản đồ mạng: {e}")
        return []

# --- TẠO MÁY CHỦ API ---
seeder_service = SeederService()
app = Flask(__name__)

@app.route('/get_active_peers', methods=['GET'])
def get_active_peers_api():
    """API endpoint để client lấy danh sách peer."""
    peers = seeder_service.get_active_peers()
    if not peers:
        return jsonify({"error": "Không có peer nào đang hoạt động hoặc dịch vụ đang khởi tạo."}), 503
    return jsonify({"active_nodes": peers}), 200

if __name__ == "__main__":
    print("=" * 60)
    print(f"--- Khởi động Sokchain Seeder Node ---")
    print(f"--- Lắng nghe tại: http://0.0.0.0:{SEEDER_PORT}      ---")
    print("=" * 60)
    try:
        serve(app, host='0.0.0.0', port=SEEDER_PORT, threads=8)
    except KeyboardInterrupt:
        seeder_service.is_running = False
        print("\nĐã dừng Seeder Node.")
