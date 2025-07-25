#!/usr/bin/env python3
# prime_agent_v7_AI.py (Phiên bản 7 - AI Điều phối Chiến lược - Đã sửa lỗi)
# Tích hợp logic "Đi ngược Đám đông" vào lõi của Prime Agent.

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
project_root = os.path.abspath(os.path.dirname(__file__))
if os.path.join(project_root, 'sok') not in sys.path:
    sys.path.insert(0, project_root)

try:
    from sok.wallet import Wallet, sign_data
    from sok.transaction import Transaction
except ImportError as e:
    print(f"LỖI: Không thể import 'sok': {e}\nKiểm tra lại cấu trúc thư mục.")
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

# Cấu hình AI "Đi ngược Đám đông"
W_CROWD = 100.0
W_LATENCY = 1.5
W_PENDING_TX = 1.0
TOP_TIER_BLOCK_HEIGHT_TOLERANCE = 1
OPPORTUNITY_ANALYSIS_INTERVAL = 60

# --- CẤU HÌNH LOGGING & FLASK ---
def setup_logging():
    log_format = '%(asctime)s [PrimeAgent] [%(threadName)-18s] [%(levelname)s] - %(message)s'
    logger = logging.getLogger()
    logger.setLevel(logging.INFO)
    if logger.hasHandlers(): logger.handlers.clear()
    
    formatter = logging.Formatter(log_format)
    file_handler = logging.FileHandler("prime_agent.log", 'w', encoding='utf-8')
    file_handler.setFormatter(formatter)
    logger.addHandler(file_handler)
    
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter)
    logger.addHandler(console_handler)

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
        
        self.opportunity_nodes: List[Dict] = []
        self.network_data_lock = threading.Lock()
        
        self.mining_threads: List[threading.Thread] = []
        self.mining_control_lock = threading.Lock()
        
        self.is_running = threading.Event()
        self.is_running.set()

    # =================================================================
    # === CÁC HÀM NỘI BỘ (KHỞI TẠO, ĐỌC/GHI) - PHẦN BỊ THIẾU CỦA BẠN ===
    # =================================================================
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
            logging.critical(f"Không thể tải/tạo ví Prime Agent: {e}", exc_info=True)
            sys.exit(1)
            
    def _load_all_known_nodes(self) -> List[str]:
        nodes = set()
        for config_file in [LIVE_NETWORK_CONFIG_FILE, BOOTSTRAP_CONFIG_FILE]:
            if os.path.exists(config_file):
                try:
                    with open(config_file, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        nodes.update(data.get("active_nodes", []))
                        nodes.update(data.get("bootstrap_nodes", []))
                except Exception as e:
                    logging.error(f"Lỗi khi đọc tệp cấu hình '{config_file}': {e}.")
        return list(nodes)

    def _load_state(self):
        if os.path.exists(ACTIVE_WORKERS_STATE_FILE):
            try:
                with open(ACTIVE_WORKERS_STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.active_workers = state.get("active_workers", {})
                    self.last_reward_times = state.get("last_reward_times", {})
                    logging.info(f"Đã khôi phục trạng thái của {len(self.active_workers)} worker.")
            except Exception as e:
                logging.error(f"Không thể tải tệp trạng thái: {e}")

    def _save_state(self):
        with self.worker_lock:
            state = {"active_workers": self.active_workers, "last_reward_times": self.last_reward_times}
        try:
            with open(ACTIVE_WORKERS_STATE_FILE, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2)
            logging.info(f"Đã lưu trạng thái của {len(self.active_workers)} worker.")
        except Exception as e:
            logging.error(f"Lỗi khi lưu trạng thái: {e}")

    # =================================================================
    # === CÁC LUỒNG HOẠT ĐỘNG CHÍNH ===================================
    # =================================================================
    def opportunity_analysis_loop(self):
        logging.info("Luồng Phân tích Cơ hội đã bắt đầu.")
        while self.is_running.is_set():
            logging.info("Đang quét và phân tích toàn bộ mạng lưới...")
            known_nodes = self._load_all_known_nodes()
            candidate_nodes: List[Dict] = []
            for node_url in known_nodes:
                try:
                    start_time = time.time()
                    response = requests.get(f'{node_url}/chain/stats', timeout=NODE_HEALTH_CHECK_TIMEOUT)
                    latency = time.time() - start_time
                    if response.status_code == 200:
                        stats = response.json()
                        block_height = stats.get('block_height', -1)
                        miners_count = stats.get('current_miners_count', 999)
                        pending_tx = stats.get('pending_transactions', 0)
                        if block_height != -1:
                            congestion_score = (W_LATENCY * latency) + (W_PENDING_TX * pending_tx)
                            opportunity_score = (W_CROWD * miners_count) + congestion_score
                            candidate_nodes.append({"url": node_url, "block_height": block_height, "opportunity_score": opportunity_score})
                except Exception: continue

            if candidate_nodes:
                max_height = max(node['block_height'] for node in candidate_nodes)
                top_tier_nodes = [n for n in candidate_nodes if n['block_height'] >= max_height - TOP_TIER_BLOCK_HEIGHT_TOLERANCE]
                sorted_opportunities = sorted(top_tier_nodes, key=lambda x: x['opportunity_score'])
                with self.network_data_lock: self.opportunity_nodes = sorted_opportunities
                if self.opportunity_nodes:
                    best_opp = self.opportunity_nodes[0]
                    logging.info(f"Phân tích hoàn tất. Cơ hội tốt nhất là {best_opp['url']} (Điểm: {best_opp['opportunity_score']:.2f})")
            else:
                with self.network_data_lock: self.opportunity_nodes.clear()

            time.sleep(OPPORTUNITY_ANALYSIS_INTERVAL)

    def mining_loop(self, thread_id: int):
        logging.info(f"Luồng Khai thác #{thread_id} đã bắt đầu.")
        while self.is_running.is_set():
            target_node_url = None
            with self.network_data_lock:
                if self.opportunity_nodes: target_node_url = self.opportunity_nodes[0]['url']
            if not target_node_url: time.sleep(15); continue
            try:
                response = requests.get(f'{target_node_url}/mine', params={'miner_address': self.wallet.get_address()}, timeout=60)
                if response.status_code == 200 and 'block' in response.json():
                    logging.info(f"💰 [Miner #{thread_id}] THÀNH CÔNG! Đã khai thác trên {target_node_url}.")
            except Exception: pass
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
            worker_address = None; target_node_url = None
            try:
                worker_address = self.reward_queue.get(timeout=1)
                with self.worker_lock:
                    if time.time() - self.last_reward_times.get(worker_address, 0) < PAYMENT_COOLDOWN_SECONDS: continue
                with self.network_data_lock:
                    if self.opportunity_nodes: target_node_url = self.opportunity_nodes[0]['url']
                if not target_node_url: self.reward_queue.put(worker_address); time.sleep(10); continue
                
                tx = Transaction(self.wallet.get_public_key_pem(), worker_address, REWARD_AMOUNT)
                tx.signature = sign_data(self.wallet.private_key, tx.calculate_hash())
                response = requests.post(f"{target_node_url}/transactions/new", data=json.dumps(tx.to_dict()), headers={'Content-Type': 'application/json'}, timeout=10)
                if response.status_code == 201:
                    with self.worker_lock: self.last_reward_times[worker_address] = time.time()
                    logging.info(f"🚀 Giao dịch trả thưởng cho {worker_address[:10]} đã được gửi!")
                else: self.reward_queue.put(worker_address); time.sleep(5)
            except Empty: continue
            except Exception as e:
                if worker_address: self.reward_queue.put(worker_address)
                time.sleep(10)

    def cleanup_workers_loop(self):
        logging.info("Luồng Dọn dẹp Worker đã bắt đầu.")
        while self.is_running.is_set():
            with self.worker_lock:
                inactive = [addr for addr, data in self.active_workers.items() if time.time() - data.get("last_seen", 0) > WORKER_TIMEOUT_SECONDS]
                for addr in inactive:
                    del self.active_workers[addr]; logging.warning(f"Worker {addr[:10]}... đã offline. Đã xóa.")
            time.sleep(60)

    # =================================================================
    # === QUẢN LÝ VÒNG ĐỜI AGENT =======================================
    # =================================================================
    def run(self):
        try: lan_ip = socket.gethostbyname(socket.gethostname())
        except: lan_ip = '127.0.0.1'
        print("="*65); print(f"      PRIME AGENT - HỆ THỐNG ĐIỀU PHỐI AI"); print(f"      API lắng nghe tại: http://{lan_ip}:{PRIME_API_PORT}"); print("="*65)
        self._load_state()
        threads = [
            threading.Thread(target=self.opportunity_analysis_loop, name="Opportunity-Analyzer", daemon=True),
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

# --- ĐIỂM CUỐI API ---
agent = PrimeAgent()
@app.route('/ping', methods=['GET'])
def ping(): return jsonify({"status": "alive"}), 200

@app.route('/request_reward', methods=['POST'])
def request_reward():
    try: data = request.get_json(force=True)
    except: return jsonify({"error": "Yêu cầu phải ở định dạng JSON."}), 400
    if data and 'worker_address' in data:
        agent.reward_queue.put(data.get('worker_address')); return jsonify({"message": "Yêu cầu đã được ghi nhận."}), 202
    return jsonify({"error": "Dữ liệu không hợp lệ hoặc thiếu 'worker_address'."}), 400

@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    try: data = request.get_json(force=True)
    except: return jsonify({"error": "Yêu cầu phải ở định dạng JSON."}), 400
    if data and 'worker_address' in data:
        with agent.worker_lock: agent.active_workers[data.get('worker_address')] = {"last_seen": time.time(), "ip": request.remote_addr}
        return jsonify({"status": "ok"}), 200
    return jsonify({"error": "Dữ liệu không hợp lệ hoặc thiếu 'worker_address'."}), 400

# --- ĐIỂM KHỞI CHẠY CHÍNH ---
def main():
    setup_logging()
    try: agent.run()
    except KeyboardInterrupt: pass
    finally: agent.shutdown()

if __name__ == '__main__':
    main()
