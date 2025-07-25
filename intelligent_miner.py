#!/usr/bin/env python3
# intelligent_miner.py - Thợ mỏ Thông minh với cơ chế Tìm kiếm & Chuyển đổi Node (Phiên bản Hoàn thiện)

# -*- coding: utf-8 -*-

"""
Tác nhân Thợ mỏ AI Thông minh & Linh hoạt (Phiên bản "Lựa chọn Ngẫu nhiên trong Nhóm Tốt nhất").

Hành vi:
- Giai đoạn 1: TÌM KIẾM
  - Quét tất cả các node đã biết từ các tệp cấu hình.
  - Tìm ra "nhóm dẫn đầu" (các node khỏe mạnh có chiều cao chuỗi gần như cao nhất).
  - Chọn ngẫu nhiên một node từ nhóm này để khai thác, giúp phân tán tải cho mạng lưới.
- Giai đoạn 2: KHAI THÁC
  - "Khóa" mục tiêu vào node đã chọn và liên tục khai thác.
- Tự động phục hồi:
  - Nếu kết nối hoặc quá trình khai thác thất bại, tự động quay lại Giai đoạn 1 để tìm node mới.
"""

import os
import sys
import requests
import json
import time
import logging
import random
from typing import List, Optional

# Thêm đường dẫn dự án để có thể import từ 'sok'
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

try:
    from sok.wallet import Wallet
except ImportError as e:
    print(f"[LỖI] Không thể import thư viện 'sok.wallet'. Hãy đảm bảo bạn đang ở đúng thư mục dự án. Lỗi: {e}")
    sys.exit(1)

# --- CẤU HÌNH ---
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"
MINER_WALLET_FILE = "resilient_miner_wallet.pem"
LOG_FILE = "intelligent_miner.log"
NODE_HEALTH_CHECK_TIMEOUT = 4  # Giây

# --- CẤU HÌNH THỜI GIAN ---
MINING_INTERVAL_SECONDS = 60            # Thời gian chờ giữa các lần khai thác thành công
RETRY_SEARCH_INTERVAL_SECONDS = 30      # Thời gian chờ nếu không tìm thấy node nào
POST_FAILURE_DELAY_SECONDS = 5          # Thời gian chờ ngắn sau khi một lần khai thác thất bại
CRITICAL_ERROR_DELAY_SECONDS = 60       # Thời gian chờ sau khi gặp lỗi nghiêm trọng

# [CẢI TIẾN] Chênh lệch chiều cao khối chấp nhận được để một node được coi là trong "nhóm dẫn đầu"
TOP_TIER_BLOCK_HEIGHT_TOLERANCE = 1

# Cấu hình Logging chi tiết, ghi ra tệp và cả màn hình
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [IntelligentMiner] [%(levelname)s] - %(message)s',
    encoding='utf-8',
    handlers=[
        logging.FileHandler(LOG_FILE, 'w', encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

def load_all_known_nodes() -> List[str]:
    """
    Tải danh sách tất cả các node tiềm năng từ các tệp cấu hình.
    Hàm này được thiết kế để tương thích với nhiều định dạng tệp cấu hình.
    """
    nodes = set()
    config_files = {
        # Tệp này thường do Ranger Agent tạo, chứa danh sách các node đang hoạt động
        LIVE_NETWORK_CONFIG_FILE: "active_nodes",
        # Tệp này là cấu hình khởi đầu, chứa các node đáng tin cậy
        BOOTSTRAP_CONFIG_FILE: "bootstrap_nodes"
    }

    for file_path, primary_key in config_files.items():
        if os.path.exists(file_path):
            try:
                with open(file_path, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    # Lấy danh sách node từ key chính (ví dụ: "active_nodes")
                    node_list = data.get(primary_key, [])
                    nodes.update(node_list)

                    # Hỗ trợ thêm định dạng cũ từ bootstrap_config.json
                    if file_path == BOOTSTRAP_CONFIG_FILE:
                        trusted_peers = data.get("trusted_bootstrap_peers", {})
                        nodes.update([p.get("last_known_address") for p in trusted_peers.values() if p.get("last_known_address")])

            except json.JSONDecodeError:
                logging.error(f"Lỗi phân tích cú pháp JSON trong tệp '{file_path}'. Vui lòng kiểm tra định dạng.")
            except Exception as e:
                logging.error(f"Lỗi khi đọc tệp cấu hình '{file_path}': {e}.")
    
    if not nodes:
        logging.warning("Không tìm thấy địa chỉ node nào trong các tệp cấu hình.")
        
    return list(nodes)

class IntelligentMinerClient:
    def __init__(self):
        self.wallet = self._initialize_wallet()
        self.current_node: Optional[str] = None

    def _initialize_wallet(self) -> Wallet:
        """Tải ví của thợ mỏ. Thoát nếu không tìm thấy ví."""
        if not os.path.exists(MINER_WALLET_FILE):
            logging.critical(f"LỖI: Không tìm thấy ví thợ mỏ '{MINER_WALLET_FILE}'.")
            logging.critical("Vui lòng chạy 'create_miner_wallet.py' hoặc đảm bảo tệp ví ở đúng vị trí.")
            sys.exit(1)
        with open(MINER_WALLET_FILE, 'r', encoding='utf-8') as f:
            return Wallet(private_key_pem=f.read())

    def find_best_node(self) -> Optional[str]:
        """
        Quét các node, tìm nhóm dẫn đầu và chọn ngẫu nhiên một node từ nhóm đó.
        Đây là logic cốt lõi giúp cân bằng giữa hiệu quả và tính phi tập trung.
        """
        logging.info("--- CHẾ ĐỘ TÌM KIẾM: Đang quét mạng lưới để tìm các node tối ưu... ---")
        known_nodes = load_all_known_nodes()
        if not known_nodes:
            return None

        healthy_nodes = []
        for node_url in known_nodes:
            try:
                response = requests.get(f'{node_url}/chain/stats', timeout=NODE_HEALTH_CHECK_TIMEOUT)
                if response.status_code == 200:
                    stats = response.json()
                    block_height = stats.get('block_height', -1)
                    if block_height != -1:
                        healthy_nodes.append({"url": node_url, "block_height": block_height})
                        logging.info(f"  [ONLINE] Node {node_url} - Chiều cao: {block_height}")
                    else:
                        logging.warning(f"  [INVALID] Node {node_url} phản hồi nhưng không có thông tin chiều cao khối.")
                else:
                    logging.warning(f"  [ERROR] Node {node_url} phản hồi với mã lỗi {response.status_code}.")
            except json.JSONDecodeError:
                logging.warning(f"  [INVALID] Node {node_url} trả về dữ liệu không hợp lệ (không phải JSON).")
            except requests.exceptions.RequestException as e:
                logging.warning(f"  [OFFLINE] Không thể kết nối đến node {node_url} (Lỗi: {type(e).__name__}).")

        if not healthy_nodes:
            logging.error("Quét hoàn tất. Không tìm thấy node nào đang hoạt động và hợp lệ.")
            return None

        max_height = max(node['block_height'] for node in healthy_nodes)
        top_tier_nodes = [node for node in healthy_nodes if node['block_height'] >= max_height - TOP_TIER_BLOCK_HEIGHT_TOLERANCE]
        
        chosen_node = random.choice(top_tier_nodes)
        
        logging.info(f"Tìm thấy {len(top_tier_nodes)} node trong nhóm dẫn đầu (chiều cao >= {max_height - TOP_TIER_BLOCK_HEIGHT_TOLERANCE}).")
        logging.info(f"✅ Đã chọn ngẫu nhiên node để khai thác: {chosen_node['url']} (Block: {chosen_node['block_height']})")
        return chosen_node['url']

    def _perform_mining_cycle(self) -> bool:
        """Thực hiện một chu kỳ khai thác trên node hiện tại."""
        if not self.current_node:
            logging.error("Lỗi nội bộ: Cố gắng khai thác mà không có node mục tiêu.")
            return False

        try:
            logging.info(f"Gửi yêu cầu khai thác tới {self.current_node}...")
            response = requests.get(f'{self.current_node}/mine', params={'miner_address': self.wallet.get_address()}, timeout=MINING_INTERVAL_SECONDS + 5)
            
            if response.status_code == 200:
                data = response.json()
                block = data.get('block', {})
                block_index = block.get('index', '#?')
                reward_tx = (block.get('transactions') or [{}])[0]
                reward_amount = reward_tx.get('amount', 'N/A')
                
                logging.info(f"⛏️ THÀNH CÔNG! Đã khai thác Khối #{block_index}. Phần thưởng: {reward_amount} SOK.")
                return True
            else:
                logging.error(f"Lỗi từ node {self.current_node}: {response.status_code} - {response.text}")
                return False
        except json.JSONDecodeError:
            logging.error(f"Node {self.current_node} trả về phản hồi không hợp lệ sau khi khai thác.")
            return False
        except requests.exceptions.RequestException as e:
            logging.error(f"Mất kết nối đến node đang khai thác ({self.current_node}). Lỗi: {e}")
            return False

    def run(self):
        """Vòng lặp chính quản lý trạng thái của thợ mỏ."""
        logging.info("--- Khởi động Thợ mỏ Thông minh (Intelligent Miner) ---")
        logging.info(f"Địa chỉ Thợ mỏ: {self.wallet.get_address()}")
        
        while True:
            try:
                if self.current_node is None:
                    self.current_node = self.find_best_node()
                    
                    if self.current_node is None:
                        logging.info(f"Sẽ thử tìm kiếm lại sau {RETRY_SEARCH_INTERVAL_SECONDS} giây...")
                        time.sleep(RETRY_SEARCH_INTERVAL_SECONDS)
                        continue
                    
                    logging.info(f"--- CHẾ ĐỘ KHAI THÁC: Đã khóa mục tiêu vào node {self.current_node} ---")
                
                success = self._perform_mining_cycle()
                
                if not success:
                    logging.warning("Khai thác thất bại. Chuyển về chế độ tìm kiếm node mới...")
                    self.current_node = None
                    time.sleep(POST_FAILURE_DELAY_SECONDS)
                else:
                    logging.info(f"Đang chờ {MINING_INTERVAL_SECONDS} giây cho chu kỳ tiếp theo...")
                    time.sleep(MINING_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                logging.info("\nĐã nhận tín hiệu dừng. Thợ mỏ sẽ tắt.")
                break
            except Exception as e:
                logging.error(f"Lỗi nghiêm trọng không xác định trong vòng lặp chính: {e}", exc_info=True)
                self.current_node = None
                logging.info(f"Sẽ thử lại sau {CRITICAL_ERROR_DELAY_SECONDS} giây.")
                time.sleep(CRITICAL_ERROR_DELAY_SECONDS)

if __name__ == "__main__":
    miner = IntelligentMinerClient()
    miner.run()
