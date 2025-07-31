#!/usr/bin/env python3
# run_node.py (Hybrid P2P & Permissionless with Genesis/Regular roles)
# -*- coding: utf-8 -*-

import os
import sys
import logging
import time
import threading
import requests
import random
import json
import socket
from urllib.parse import urlparse

# Cài đặt thư viện cần thiết: pip install waitress requests
from waitress import serve

# --- THIẾT LẬP MÔI TRƯỜNG & ĐƯỜNG DẪN ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

if sys.stdout.encoding != 'utf-8':
    sys.stdout.reconfigure(encoding='utf-8')
    sys.stderr.reconfigure(encoding='utf-8')

# --- IMPORT CÁC THÀNH PHẦN CỐT LÕI ---
try:
    from sok.node_api import create_app
    from sok.utils import Config
    from sok.wallet import Wallet
    from sok.blockchain import Blockchain, Block
except ImportError as e:
    print(f"\n[LỖI IMPORT] Không thể tải các thành phần cần thiết: {e}")
    sys.exit(1)

# --- ĐỊNH NGHĨA CÁC ĐƯỜNG DẪN CẤU HÌNH ---
DB_FILE_PATH = os.path.join(project_root, 'blockchain.sqlite')
NODE_WALLET_PATH = os.path.join(project_root, 'node_wallet.pem')
GENESIS_WALLET_PATH = os.path.join(project_root, 'genesis_wallet.pem') # <-- ĐỔI TÊN
LIVE_NETWORK_CONFIG_FILE = os.path.join(project_root, 'live_network_nodes.json')


# --- BỘ NÃO P2P LAI (HYBRID) ---
class HybridP2PManager:
    DISCOVERY_PORT = 5005 

    def __init__(self, blockchain: Blockchain, node_wallet: Wallet, node_port: int, host_ip: str):
        self.blockchain = blockchain
        self.node_wallet = node_wallet
        self.node_port = node_port
        self.host_ip = host_ip
        self.logger = logging.getLogger("HybridP2PManager")
        self.is_running = True
        
        self.threads = [
            threading.Thread(target=self._run_lan_discovery, daemon=True, name="LAN-Discovery"),
            threading.Thread(target=self._run_map_file_sync, daemon=True, name="Map-FileSync"),
            threading.Thread(target=self._run_peer_exchange, daemon=True, name="Peer-Exchange(PEX)")
        ]

    def start(self):
        self.logger.info("Đang khởi động dịch vụ P2P với mô hình lai (LAN + Map + PEX)...")
        for thread in self.threads:
            thread.start()
    
    def stop(self):
        self.logger.info("Đang dừng dịch vụ P2P...")
        self.is_running = False

    def broadcast_transaction(self, transaction: dict):
        self._broadcast_message('/transactions/add_from_peer', transaction)

    def broadcast_block(self, block: Block):
        self._broadcast_message('/blocks/add_from_peer', block.to_dict())

    def _broadcast_message(self, endpoint: str, data: dict):
        with self.blockchain.peer_lock:
            peers_to_broadcast = list(self.blockchain.peers.values())
        
        for peer in peers_to_broadcast:
            try:
                requests.post(f"{peer['address']}{endpoint}", json=data, timeout=2)
            except requests.exceptions.RequestException:
                continue

    # (Các hàm P2P còn lại giữ nguyên, không cần thay đổi)
    def _run_lan_discovery(self):
        self.logger.info(f"[Lớp 1 - LAN] Đang lắng nghe khám phá trên UDP port {self.DISCOVERY_PORT}.")
        listener_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        listener_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
        listener_socket.bind(('', self.DISCOVERY_PORT))
        broadcast_socket = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        broadcast_socket.setsockopt(socket.SOL_SOCKET, socket.SO_BROADCAST, 1)

        broadcast_payload = json.dumps({
            "protocol": "sokchain_discovery", 
            "node_id": self.node_wallet.get_address(), 
            "port": self.node_port
        }).encode('utf-8')

        last_broadcast_time = 0
        while self.is_running:
            if time.time() - last_broadcast_time > 60:
                try:
                    broadcast_socket.sendto(broadcast_payload, ('<broadcast>', self.DISCOVERY_PORT))
                    last_broadcast_time = time.time()
                except Exception: pass
            
            listener_socket.settimeout(1.0)
            try:
                data, addr = listener_socket.recvfrom(1024)
                message = json.loads(data.decode('utf-8'))
                if message.get("protocol") == "sokchain_discovery":
                    new_node_id, new_node_port, new_node_ip = message.get("node_id"), message.get("port"), addr[0]
                    if new_node_id != self.node_wallet.get_address():
                        self.blockchain.register_node(new_node_id, f"http://{new_node_ip}:{new_node_port}")
            except socket.timeout: continue
            except (json.JSONDecodeError, KeyError, UnicodeDecodeError): pass

    def _run_map_file_sync(self):
        self.logger.info(f"[Lớp 2 - Map Sync] Đang theo dõi tệp '{LIVE_NETWORK_CONFIG_FILE}'...")
        while self.is_running:
            if os.path.exists(LIVE_NETWORK_CONFIG_FILE):
                try:
                    with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f: data = json.load(f)
                    active_node_urls = data.get("active_nodes", [])
                    if active_node_urls:
                        for url in active_node_urls:
                            self._handshake_and_register(url)
                except (json.JSONDecodeError, IOError): pass
            time.sleep(3 * 60)

    def _run_peer_exchange(self):
        self.logger.info("[Lớp 3 - PEX] Luồng trao đổi peer đã sẵn sàng.")
        time.sleep(45)
        while self.is_running:
            with self.blockchain.peer_lock:
                all_peers = list(self.blockchain.peers.values())
            
            if not all_peers:
                time.sleep(30)
                continue

            random_peer = random.choice(all_peers)
            peer_address = random_peer['address']
            
            try:
                response = requests.get(f"{peer_address}/nodes/peers", timeout=5)
                if response.status_code == 200:
                    peers_from_node = response.json()
                    self.blockchain.merge_peers(peers_from_node, self.node_wallet.get_address())
            except requests.RequestException: pass 
            time.sleep(5 * 60)
            
    def _handshake_and_register(self, base_url: str):
        try:
            full_url = f"http://{base_url.replace('http://', '').replace('https://', '')}"
            response = requests.get(f'{full_url}/handshake', timeout=3)
            if response.status_code == 200:
                node_id = response.json().get('node_id')
                if node_id and node_id != self.node_wallet.get_address():
                    self.blockchain.register_node(node_id, full_url)
        except requests.RequestException: pass

# --- ĐIỂM VÀO CHÍNH CỦA CHƯƠNG TRÌNH ---
if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO, format='%(asctime)s [%(levelname)s] (%(threadName)s) - %(message)s')

    # Tải hoặc tạo ví định danh của Node (bắt buộc cho mọi node)
    if not os.path.exists(NODE_WALLET_PATH):
        logging.info("Không tìm thấy ví Node. Đang tạo mới...")
        node_wallet = Wallet()
        with open(NODE_WALLET_PATH, 'w', encoding='utf-8') as f: f.write(node_wallet.get_private_key_pem())
        logging.info(f"Đã tạo ví mới. ID Node: {node_wallet.get_address()}")
    else:
        with open(NODE_WALLET_PATH, 'r', encoding='utf-8') as f: node_wallet = Wallet(private_key_pem=f.read())
    
    # === TÍCH HỢP LOGIC NODE SÁNG THẾ/PHỤ ===
    genesis_wallet = None # <-- ĐỔI TÊN
    is_genesis_node = False # <-- ĐỔI TÊN
    if os.path.exists(GENESIS_WALLET_PATH): # <-- ĐỔI TÊN
        try:
            with open(GENESIS_WALLET_PATH, 'r', encoding='utf-8') as f: # <-- ĐỔI TÊN
                genesis_wallet = Wallet(private_key_pem=f.read()) # <-- ĐỔI TÊN
            
            if genesis_wallet.get_address() == Config.FOUNDER_ADDRESS:
                is_genesis_node = True # <-- ĐỔI TÊN
            else:
                logging.critical(f"!!! LỖI: Ví trong '{GENESIS_WALLET_PATH}' không khớp với FOUNDER_ADDRESS trong 'sok/utils.py'.")
                sys.exit(1)
        except Exception as e:
            logging.error(f"Không thể tải Ví Sáng thế từ '{GENESIS_WALLET_PATH}': {e}")
            sys.exit(1)
    
    port = int(os.environ.get('PORT', Config.DEFAULT_NODE_PORT))
    
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(('8.8.8.8', 1)); host_ip = s.getsockname()[0]
    except Exception: host_ip = '127.0.0.1'
    finally: s.close()
        
    blockchain_instance = Blockchain(db_path=DB_FILE_PATH)
    p2p_manager = HybridP2PManager(blockchain=blockchain_instance, node_wallet=node_wallet, node_port=port, host_ip=host_ip)
    
    app = create_app(
        blockchain=blockchain_instance,
        p2p_manager=p2p_manager,
        node_wallet=node_wallet,
        genesis_wallet=genesis_wallet  # <-- ĐỔI TÊN: Truyền ví sáng thế
    )
    
    p2p_manager.start()
    
    print("=" * 60)
    print("      --- Khởi động Node Sokchain (Mô hình P2P Lai - Phi tập trung) ---")
    if is_genesis_node: # <-- ĐỔI TÊN
        print("      ---   LOẠI NODE: NODE SÁNG THẾ (GENESIS NODE)   ---")
        logging.info("Đã tải thành công Ví Sáng thế. Đang khởi chạy ở chế độ [GENESIS NODE].")
    else:
        print("      ---   LOẠI NODE: NODE PHỤ (REGULAR NODE)      ---")
        logging.info("Không tìm thấy 'genesis_wallet.pem'. Đang khởi chạy ở chế độ [NODE PHỤ].")
    print(f"      ---   Node ID: {node_wallet.get_address()} ---")
    print(f"      ---   Lắng nghe API tại: http://{host_ip}:{port}        ---")
    print(f"      ---   P2P: LAN (UDP:{HybridP2PManager.DISCOVERY_PORT}) + Map File + PEX ---")
    print("=" * 60)
    serve(app, host='0.0.0.0', port=port, threads=16)
