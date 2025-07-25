# PeerHarvesterAgent.py
# AI Agent tự động khám phá các node đang hoạt động và cập nhật tệp bootstrap_config.json.

# -*- coding: utf-8 -*-  # <<< THÊM DÒNG NÀY: Khai báo encoding cho tệp Python

import os
import sys
import time
import requests
import json
import logging

# --- THÊM ĐƯỜNG DẪN DỰ ÁN SOKCHAIN ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- CẤU HÌNH ---
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"
HARVEST_INTERVAL_SECONDS = 10 * 60
NODE_HANDSHAKE_TIMEOUT = 5

# --- CẤU HÌNH LOGGING (Đã có encoding='utf-8') ---
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [HarvesterAgent] [%(levelname)s] - %(message)s',
    encoding='utf-8', # <<< ĐIỂM QUAN TRỌNG 1
    handlers=[
        logging.FileHandler("harvester_agent.log", 'w', 'utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# =========================================================================
# === CÁC HÀM TIỆN ÍCH ===================================================
# =========================================================================

def load_live_nodes() -> list[str]:
    """Chỉ đọc danh sách các node đang hoạt động từ tệp bản đồ mạng."""
    if not os.path.exists(LIVE_NETWORK_CONFIG_FILE):
        logging.warning(f"Không tìm thấy tệp bản đồ mạng '{LIVE_NETWORK_CONFIG_FILE}'.")
        return []
    try:
        # Luôn chỉ định encoding='utf-8' khi đọc file
        with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f: # <<< ĐIỂM QUAN TRỌNG 2
            data = json.load(f)
            return data.get("active_nodes", [])
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"Lỗi khi đọc tệp bản đồ mạng: {e}")
        return []

def load_bootstrap_config() -> dict:
    """Tải tệp bootstrap hiện có."""
    if not os.path.exists(BOOTSTRAP_CONFIG_FILE):
        return {"trusted_bootstrap_peers": {}}
    try:
        with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f: # <<< ĐIỂM QUAN TRỌNG 2
            data = json.load(f)
            if "trusted_bootstrap_peers" not in data:
                data["trusted_bootstrap_peers"] = {}
            return data
    except (IOError, json.JSONDecodeError) as e:
        logging.error(f"Lỗi khi đọc tệp bootstrap, sẽ tạo một cấu trúc mới: {e}")
        return {"trusted_bootstrap_peers": {}}

def save_bootstrap_config(data: dict):
    """Lưu dữ liệu vào tệp bootstrap một cách an toàn."""
    try:
        temp_file = BOOTSTRAP_CONFIG_FILE + ".tmp"
        # Luôn chỉ định encoding='utf-8' khi ghi file
        with open(temp_file, 'w', encoding='utf-8') as f: # <<< ĐIỂM QUAN TRỌNG 2
            # ensure_ascii=False để ghi ký tự tiếng Việt (nếu có) một cách tự nhiên
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(temp_file, BOOTSTRAP_CONFIG_FILE)
        logging.info(f"✅ Đã cập nhật thành công tệp '{BOOTSTRAP_CONFIG_FILE}'")
    except Exception as e:
        logging.error(f"LỖI: Không thể lưu tệp cấu hình bootstrap. Lỗi: {e}")

# ===================================================================
# === LOGIC CỐT LÕI CỦA AGENT =======================================
# ===================================================================

def run_harvest_cycle():
    """Chạy một chu kỳ thu hoạch và cập nhật."""
    logging.info("Bắt đầu chu kỳ thu hoạch peer...")
    
    live_node_urls = load_live_nodes()
    if not live_node_urls:
        return

    discovered_peers = {}
    logging.info(f"Đang tiến hành handshake với {len(live_node_urls)} node...")

    for node_url in live_node_urls:
        try:
            response = requests.get(f"{node_url}/handshake", timeout=NODE_HANDSHAKE_TIMEOUT)
            if response.status_code == 200:
                data = response.json()
                node_id = data.get('node_id')
                if node_id:
                    logging.info(f"  [THÀNH CÔNG] Thu thập được Node ID: {node_id[:15]}... tại {node_url}")
                    discovered_peers[node_id] = { "last_known_address": node_url }
            else:
                logging.warning(f"  [THẤT BẠI] Node {node_url} phản hồi lỗi {response.status_code}.")

        except requests.RequestException:
            logging.warning(f"  [OFFLINE] Không thể kết nối đến node {node_url}.")

    if not discovered_peers:
        logging.warning("Không thu thập được thông tin từ bất kỳ node nào. Bỏ qua cập nhật.")
        return

    bootstrap_data = load_bootstrap_config()
    bootstrap_data["trusted_bootstrap_peers"].update(discovered_peers)
    save_bootstrap_config(bootstrap_data)

# ============================================================
# === HÀM CHÍNH ==============================================
# ============================================================

if __name__ == "__main__":
    logging.info("--- Khởi động Tác nhân Thu hoạch Peer (Peer Harvester Agent) ---")
    while True:
        try:
            run_harvest_cycle()
            logging.info(f"Chu kỳ hoàn tất. Sẽ chạy lại sau {HARVEST_INTERVAL_SECONDS // 60} phút.")
            time.sleep(HARVEST_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logging.info("\nĐã dừng Harvester Agent.")
            break
        except Exception as e:
            logging.error(f"Lỗi nghiêm trọng trong vòng lặp chính: {e}", exc_info=True)
            time.sleep(60)
