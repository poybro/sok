#!/usr/bin/env python3
# prime_agent_v6.py (Phiên bản 6.1 - Final Patched)
# Tương thích UTF-8, bền bỉ và tự chủ hoàn toàn.

import os
import sys
import time
import requests
import json
import threading
import logging
import socket
from flask import Flask, request, jsonify
from queue import Queue, Empty
from waitress import serve
from typing import List, Dict, Optional

# --- THÊM ĐƯỜNG DẪN DỰ ÁN SOKCHAIN ---
# Giả định file này nằm trong thư mục gốc của dự án, ngang hàng với 'sok'
project_root = os.path.abspath(os.path.dirname(__file__))
if os.path.join(project_root, 'sok') not in sys.path:
    sys.path.insert(0, project_root)

try:
    from sok.wallet import Wallet, sign_data
    from sok.transaction import Transaction
except ImportError as e:
    # Ghi lỗi ra file nếu không thể import, giúp gỡ lỗi dễ hơn
    with open("PRIME_AGENT_CRITICAL_ERROR.log", "w", encoding='utf-8') as f:
        f.write(f"Không thể import 'sok': {e}\n sys.path: {sys.path}")
    sys.exit(1)

# =================================================================
# === CẤU HÌNH AGENT ==============================================
# =================================================================
PRIME_WALLET_FILE = "prime_agent_wallet.pem"
ACTIVE_WORKERS_STATE_FILE = "active_workers_state.json"
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"

PRIME_API_PORT = 9000
REWARD_AMOUNT = 0.1
PAYMENT_COOLDOWN_SECONDS = 180
WORKER_TIMEOUT_SECONDS = 180
NODE_HEALTH_CHECK_TIMEOUT = 5

MINING_INTERVAL_SECONDS = 10
MINING_THREADS_PER_N_WORKERS = 5
MAX_MINING_THREADS = 10

# =================================================================
# === CẤU HÌNH LOGGING ============================================
# =================================================================
def setup_logging():
    log_format = '%(asctime)s [PrimeAgent] [%(threadName)-13s] [%(levelname)s] - %(message)s'
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.hasHandlers(): logger.handlers.clear()
    
    formatter = logging.Formatter(log_format)
    
    # Ghi ra file với UTF-8
    file_handler = logging.FileHandler("prime_agent.log", 'w', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    # Hiển thị trên console với UTF-8
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

# --- Tắt log mặc định của Flask/Waitress để giữ giao diện sạch sẽ ---
app = Flask(__name__)
log = logging.getLogger('werkzeug')
log.disabled = True
app.logger.disabled = True

class PrimeAgent:
    def __init__(self):
        self.wallet = self._initialize_wallet()
        self.reward_queue = Queue()
        self.active_workers: Dict[str, Dict] = {}
        self.last_reward_times: Dict[str, float] = {}
        self.worker_lock = threading.Lock()
        
        self.current_best_node: Optional[str] = None
        self.mining_threads: List[threading.Thread] = []
        self.mining_control_lock = threading.Lock()
        
        self.is_running = threading.Event()
        self.is_running.set()

    def _initialize_wallet(self) -> Wallet:
        logging.info("Đang khởi tạo ví cho Prime Agent...")
        try:
            if not os.path.exists(PRIME_WALLET_FILE):
                logging.warning(f"Tạo ví mới cho Prime Agent tại '{PRIME_WALLET_FILE}'...")
                wallet = Wallet()
                with open(PRIME_WALLET_FILE, "w", encoding='utf-8') as f: f.write(wallet.get_private_key_pem())
                return wallet
            else:
                with open(PRIME_WALLET_FILE, 'r', encoding='utf-8') as f: return Wallet(private_key_pem=f.read())
        except Exception as e:
            logging.critical(f"Không thể tải/tạo ví Prime Agent: {e}", exc_info=True); sys.exit(1)
            
    def _load_all_known_nodes(self) -> List[str]:
        nodes = set()
        for config_file in [LIVE_NETWORK_CONFIG_FILE, BOOTSTRAP_CONFIG_FILE]:
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        if "active_nodes" in data: nodes.update(data.get("active_nodes", []))
                        if "trusted_bootstrap_peers" in data:
                            peers = data.get("trusted_bootstrap_peers", {})
                            nodes.update([p.get("last_known_address") for p in peers.values() if p.get("last_known_address")])
                except Exception as e: logging.error(f"Lỗi khi đọc tệp cấu hình '{config_file}': {e}.")
        return list(nodes)

    def find_best_node_loop(self):
        logging.info("Luồng Tìm kiếm Node đã bắt đầu.")
        while self.is_running.is_set():
            logging.info("Đang quét mạng lưới để tìm node tối ưu...")
            known_nodes = self._load_all_known_nodes()
            if not known_nodes:
                logging.error("Không tìm thấy bất kỳ node nào trong các tệp cấu hình."); time.sleep(60); continue

            healthy_nodes = []
            for node_url in known_nodes:
                try:
                    # Giả sử node có endpoint /chain/stats hoặc một endpoint nhẹ để kiểm tra
                    response = requests.get(f'{node_url}/chain', timeout=NODE_HEALTH_CHECK_TIMEOUT)
                    if response.status_code == 200:
                        stats = response.json()
                        block_height = stats.get('length', -1)
                        healthy_nodes.append({"url": node_url, "block_height": block_height})
                        logging.info(f"  [ONLINE] Node {node_url} - Chiều cao: {block_height}")
                except requests.exceptions.RequestException: logging.warning(f"  [OFFLINE] Không thể kết nối đến node {node_url}.")

            if healthy_nodes:
                best_node = max(healthy_nodes, key=lambda x: x['block_height'])
                if self.current_best_node != best_node['url']:
                    logging.info(f"✅ Đã tìm thấy node tốt nhất mới: {best_node['url']} (Block: {best_node['block_height']})")
                    self.current_best_node = best_node['url']
            else:
                logging.error("Quét hoàn tất. Không tìm thấy node nào đang hoạt động."); self.current_best_node = None
            time.sleep(300)

    def mining_loop(self, thread_id: int):
        logging.info(f"Luồng Khai thác #{thread_id} đã bắt đầu.")
        while self.is_running.is_set():
            if not self.current_best_node: time.sleep(15); continue
            try:
                logging.info(f"[Miner #{thread_id}] Đang thử khai thác trên {self.current_best_node}...")
                response = requests.get(f'{self.current_best_node}/mine', params={'miner_address': self.wallet.get_address()}, timeout=60)
                if response.status_code == 200 and 'block' in response.json():
                    block = response.json().get('block', {})
                    logging.info(f"💰 [Miner #{thread_id}] THÀNH CÔNG! Đã khai thác Khối #{block.get('index', '?')}.")
                elif response.status_code == 200:
                    logging.info(f"[Miner #{thread_id}] Không có giao dịch để khai thác.")
                else: logging.error(f"[Miner #{thread_id}] Lỗi từ node: {response.status_code} - {response.text}")
            except requests.exceptions.RequestException as e: logging.error(f"[Miner #{thread_id}] Mất kết nối đến node. Lỗi: {e}")
            time.sleep(MINING_INTERVAL_SECONDS)

    def adjust_mining_power_loop(self):
        logging.info("Luồng Điều chỉnh Sức mạnh Khai thác đã bắt đầu.")
        while self.is_running.is_set():
            with self.worker_lock: num_workers = len(self.active_workers)
            desired_threads = min(max(1, num_workers // MINING_THREADS_PER_N_WORKERS), MAX_MINING_THREADS)
            with self.mining_control_lock:
                current_threads = len(self.mining_threads)
                if current_threads < desired_threads:
                    new_thread_id = current_threads + 1
                    thread = threading.Thread(target=self.mining_loop, name=f"Miner-{new_thread_id}", args=(new_thread_id,), daemon=True)
                    thread.start(); self.mining_threads.append(thread)
                    logging.info(f"📈 Sức mạnh khai thác tăng. Đã khởi động luồng đào #{new_thread_id}. (Tổng: {len(self.mining_threads)})")
            time.sleep(60)

    def payment_loop(self):
        logging.info("Luồng Trả thưởng đã bắt đầu.")
        while self.is_running.is_set():
            worker_address = None
            try:
                worker_address = self.reward_queue.get(timeout=1)
                current_time = time.time()
                with self.worker_lock: last_paid = self.last_reward_times.get(worker_address, 0)
                if current_time - last_paid < PAYMENT_COOLDOWN_SECONDS:
                    logging.warning(f"Worker {worker_address[:10]}... yêu cầu thưởng quá nhanh. Bỏ qua."); continue
                
                if not self.current_best_node:
                    logging.error("Không có node để gửi giao dịch, thử lại sau."); self.reward_queue.put(worker_address); time.sleep(10); continue

                logging.info(f"Đang xử lý trả thưởng {REWARD_AMOUNT} SOK cho {worker_address[:10]}...")
                
                tx = Transaction(
                    sender_public_key_pem=self.wallet.get_public_key_pem(),
                    recipient_address=worker_address,
                    amount=REWARD_AMOUNT
                )
                tx.signature = sign_data(self.wallet.private_key, tx.calculate_hash())
                
                response = requests.post(f"{self.current_best_node}/transactions/new", data=json.dumps(tx.to_dict()), headers={'Content-Type': 'application/json'}, timeout=10)
                
                if response.status_code == 201:
                    logging.info(f"🚀 Giao dịch trả thưởng cho {worker_address[:10]}... đã được gửi thành công!")
                    with self.worker_lock: self.last_reward_times[worker_address] = current_time
                else:
                    logging.error(f"Lỗi khi gửi giao dịch: {response.status_code} - {response.text}"); self.reward_queue.put(worker_address); time.sleep(5)
            except Empty: continue
            except Exception as e:
                logging.error(f"Lỗi nghiêm trọng trong luồng trả thưởng: {e}", exc_info=True)
                if worker_address: self.reward_queue.put(worker_address)
                time.sleep(10)

    def cleanup_workers_loop(self):
        logging.info("Luồng Dọn dẹp Worker đã bắt đầu.")
        while self.is_running.is_set():
            with self.worker_lock:
                inactive = [addr for addr, data in self.active_workers.items() if time.time() - data.get("last_seen", 0) > WORKER_TIMEOUT_SECONDS]
                for addr in inactive:
                    del self.active_workers[addr]; logging.warning(f"Worker {addr[:10]}... đã offline (timeout). Đã xóa.")
            time.sleep(60)
            
    def _load_state(self):
        if os.path.exists(ACTIVE_WORKERS_STATE_FILE):
            try:
                with open(ACTIVE_WORKERS_STATE_FILE, 'r', encoding='utf-8') as f: state = json.load(f)
                self.active_workers = state.get("active_workers", {}); self.last_reward_times = state.get("last_reward_times", {})
                logging.info(f"Đã khôi phục trạng thái của {len(self.active_workers)} worker.")
            except Exception as e: logging.error(f"Không thể tải tệp trạng thái: {e}")

    def _save_state(self):
        logging.info("Đang lưu trạng thái...")
        with self.worker_lock: state = {"active_workers": self.active_workers, "last_reward_times": self.last_reward_times}
        try:
            with open(ACTIVE_WORKERS_STATE_FILE, 'w', encoding='utf-8') as f: json.dump(state, f, indent=2)
            logging.info(f"Đã lưu trạng thái của {len(self.active_workers)} worker.")
        except Exception as e: logging.error(f"Lỗi khi lưu trạng thái: {e}")

    def run(self):
        try: lan_ip = socket.gethostbyname(socket.gethostname())
        except: lan_ip = '127.0.0.1'
        print("="*65); print(f"      PRIME AGENT - HỆ THỐNG TỰ CHỦ (ID: {self.wallet.get_address()[:15]}...)"); print(f"      API lắng nghe tại: http://{lan_ip}:{PRIME_API_PORT}"); print("="*65)
        self._load_state()
        threads = [
            threading.Thread(target=self.find_best_node_loop, name="Node-Finder", daemon=True),
            threading.Thread(target=self.payment_loop, name="Payer", daemon=True),
            threading.Thread(target=self.cleanup_workers_loop, name="Cleaner", daemon=True),
            threading.Thread(target=self.adjust_mining_power_loop, name="Power-Control", daemon=True)
        ]
        for t in threads: t.start()
        logging.info(f"API Server bắt đầu phục vụ trên 0.0.0.0:{PRIME_API_PORT}")
        serve(app, host='0.0.0.0', port=PRIME_API_PORT, threads=8)

    def shutdown(self):
        if self.is_running.is_set():
            print("\n\nĐang dừng Prime Agent..."); self.is_running.clear()
            self._save_state(); logging.info("Prime Agent đã dừng.")

# --- Điểm cuối API ---
agent = PrimeAgent()
@app.route('/ping', methods=['GET'])
def ping(): return jsonify({"status": "alive"}), 200
@app.route('/request_reward', methods=['POST'])
def request_reward(): data = request.get_json(); agent.reward_queue.put(data.get('worker_address')); return jsonify({"message": "Yêu cầu đã được ghi nhận."}), 202
@app.route('/heartbeat', methods=['POST'])
def heartbeat(): data = request.get_json(); agent.active_workers[data.get('worker_address')] = {"last_seen": time.time(), "ip": request.remote_addr}; return jsonify({"status": "ok"}), 200

def main():
    setup_logging()
    try: agent.run()
    except KeyboardInterrupt: pass
    finally: agent.shutdown()

if __name__ == '__main__':
    main()
