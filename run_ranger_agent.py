#!/usr/bin/env python3
# run_ranger_agent.py (Phiên bản "Khám phá & Lan truyền")
# -*- coding: utf-8 -*-

"""
Tác nhân Trinh sát Mạng - Phiên bản "Khám phá & Lan truyền".
- Quét sâu mạng lưới để tìm các node đang hoạt động.
- Ghi kết quả vào tệp live_network_nodes.json cục bộ.
- LAN TRUYỀN bản đồ này đến các node khác trong mạng lưới.
"""

import os
import sys
import requests
import json
import time
import logging
import random # <-- THÊM MỚI
from typing import Set, Dict, Any

# Thêm đường dẫn dự án
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- CẤU HÌNH ---
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
DISCOVERY_INTERVAL_SECONDS = 5 * 60
LOG_FILE = "ranger_agent.log"
BROADCAST_COUNT = 3 # Số lượng node ngẫu nhiên để gửi bản đồ tới

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [RangerAgent] [%(levelname)s] - %(message)s',
    encoding='utf-8',
    handlers=[
        logging.FileHandler(LOG_FILE, 'w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

# (Hàm load_bootstrap_peers và normalize_url giữ nguyên)
def load_bootstrap_peers() -> dict:
    if not os.path.exists(BOOTSTRAP_CONFIG_FILE):
        logging.critical(f"LỖI: Không tìm thấy tệp cấu hình bootstrap '{BOOTSTRAP_CONFIG_FILE}'.")
        return {}
    try:
        with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
            data = json.load(f)
            return data.get("trusted_bootstrap_peers", {})
    except Exception as e:
        logging.error(f"Lỗi khi đọc tệp cấu hình bootstrap: {e}.")
    return {}

def normalize_url(address: str) -> str:
    if not isinstance(address, str): return ""
    if address.startswith("http://") or address.startswith("https://"):
        return address
    return f"http://{address}"

def run_deep_discovery_cycle(bootstrap_peers: Dict[str, Any]):
    logging.info("Bắt đầu chu kỳ quét sâu mạng lưới...")
    
    initial_peers = {normalize_url(peer_info.get('last_known_address')) for peer_info in bootstrap_peers.values()}
    nodes_to_scan = {url for url in initial_peers if url}
    scanned_nodes = set()
    all_discovered_peers: Dict[str, Dict[str, Any]] = {}

    while nodes_to_scan:
        node_url = nodes_to_scan.pop()
        if node_url in scanned_nodes:
            continue
        
        scanned_nodes.add(node_url)
        logging.info(f"Đang quét peer tại: {node_url}...")
        
        try:
            response = requests.get(f"{node_url}/nodes/peers", timeout=5)
            if response.status_code == 200:
                peers_from_node = response.json()
                all_discovered_peers.update(peers_from_node)
                
                for peer_data in peers_from_node.values():
                    new_node_url = normalize_url(peer_data.get('address'))
                    if new_node_url and new_node_url not in scanned_nodes:
                        nodes_to_scan.add(new_node_url)
            else:
                logging.warning(f"Node {node_url} phản hồi với mã lỗi {response.status_code}.")
        except requests.exceptions.RequestException:
            logging.warning(f"Không thể kết nối đến node {node_url}.")

    if not all_discovered_peers:
        # Nếu không tìm thấy peer nào, hãy thử ping trực tiếp các bootstrap peer
        logging.warning("Không khám phá được peer nào qua PEX. Đang thử ping trực tiếp bootstrap peers...")
        for url in initial_peers:
            all_discovered_peers[url] = {"address": url}

    logging.info(f"Đã khám phá được tổng cộng {len(all_discovered_peers)} peer tiềm năng. Bắt đầu kiểm tra sức khỏe...")
    live_nodes = []
    for node_id, peer_data in all_discovered_peers.items():
        node_url = normalize_url(peer_data.get('address'))
        if not node_url: continue
        try:
            handshake_resp = requests.get(f'{node_url}/handshake', timeout=3)
            # Node ID từ handshake có thể khác với key trong `all_discovered_peers` nếu có xung đột
            actual_node_id = handshake_resp.json().get('node_id')
            if handshake_resp.status_code == 200 and actual_node_id:
                live_nodes.append(node_url)
                logging.info(f"  [OK] Node {actual_node_id[:15]}... tại {node_url} đang hoạt động.")
            else:
                logging.warning(f"  [FAIL] Node tại {node_url} không vượt qua kiểm tra sức khỏe.")
        except requests.exceptions.RequestException:
            logging.warning(f"  [OFFLINE] Node tại {node_url} không phản hồi.")
    
    # Loại bỏ các URL trùng lặp và sắp xếp
    live_nodes = sorted(list(set(live_nodes)))

    if not live_nodes:
        logging.error("KHÁM PHÁ THẤT BẠI! Không tìm thấy node nào đang hoạt động.")
        return

    # --- CẬP NHẬT CỤC BỘ VÀ LAN TRUYỀN ---
    try:
        logging.info(f"Tổng hợp được {len(live_nodes)} node đang hoạt động. Đang cập nhật tệp cục bộ...")
        # 1. Cập nhật tệp cục bộ (giống như trước)
        temp_file = LIVE_NETWORK_CONFIG_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump({"active_nodes": live_nodes}, f, indent=2)
        os.replace(temp_file, LIVE_NETWORK_CONFIG_FILE)
        logging.info(f"✅ Đã cập nhật thành công tệp cục bộ '{LIVE_NETWORK_CONFIG_FILE}'.")

        # 2. LAN TRUYỀN bản đồ mạng đến các node khác
        logging.info("Bắt đầu lan truyền bản đồ mạng đến các node khác...")
        nodes_to_notify = random.sample(live_nodes, min(len(live_nodes), BROADCAST_COUNT))
        
        payload = {"active_nodes": live_nodes}
        
        for node_url in nodes_to_notify:
            try:
                logging.info(f"  -> Đang gửi bản đồ đến {node_url}...")
                response = requests.post(f"{node_url}/nodes/update_map", json=payload, timeout=5)
                if response.status_code == 202:
                    logging.info(f"     [SUCCESS] Node {node_url} đã chấp nhận bản đồ.")
                else:
                    logging.warning(f"     [FAIL] Node {node_url} phản hồi: {response.status_code} - {response.text}")
            except requests.RequestException as e:
                logging.error(f"     [ERROR] Không thể gửi bản đồ đến {node_url}: {e}")

    except Exception as e:
        logging.error(f"Lỗi khi ghi và lan truyền tệp cấu hình: {e}")

# (Hàm main giữ nguyên)
def main():
    bootstrap_peers = load_bootstrap_peers()
    if not bootstrap_peers:
        logging.critical("Không có bootstrap peer nào trong cấu hình. Ranger không thể hoạt động.")
        return

    while True:
        try:
            run_deep_discovery_cycle(bootstrap_peers)
            logging.info(f"Chu kỳ khám phá và lan truyền hoàn tất. Sẽ chạy lại sau {DISCOVERY_INTERVAL_SECONDS} giây.")
            time.sleep(DISCOVERY_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logging.info("\nTác nhân Trinh sát Mạng đã được dừng bởi người dùng.")
            break
        except Exception as e:
            logging.error(f"Lỗi nghiêm trọng trong vòng lặp chính: {e}", exc_info=True)
            time.sleep(60)

if __name__ == "__main__":
    main()
