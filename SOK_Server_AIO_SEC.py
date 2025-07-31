#!/usr/bin/env python3
# SOK_Server_All_In_One -v12.0_Secure_API.py (Tích hợp Lớp Bảo mật Giao dịch)
# -*- coding: utf-8 -*-

import os, sys, time, requests, json, threading, logging, socket, random, uuid, math
from flask import Flask, jsonify, request, render_template
from flask_cors import CORS
from queue import Queue, Empty
from waitress import serve
from typing import List, Dict, Optional
from decimal import Decimal, getcontext
from colorama import Fore, Style, init as colorama_init
import plotly.graph_objects as go
from datetime import datetime

# --- CẤU HÌNH & THIẾT LẬP ---
getcontext().prec = 50 
project_root = os.path.abspath(os.path.dirname(__file__))
if os.path.join(project_root, 'sok') not in sys.path: sys.path.insert(0, project_root)
try:
    from sok.wallet import Wallet, get_address_from_public_key_pem, verify_signature
    from sok.transaction import Transaction
except ImportError as e:
    with open("SERVER_CRITICAL_ERROR.log", "w", encoding='utf-8') as f:
        f.write(f"Timestamp: {time.ctime()}\nKhông thể import 'sok': {e}\nSys.path: {sys.path}")
    sys.exit(1)

# Cấu hình chung
PRIME_WALLET_FILE = "prime_agent_wallet.pem"
STATE_FILE = "prime_agent_state.json"
SERVER_PORT = 9000
BLOCKCHAIN_NODE_URL = "http://192.168.1.19:5000"

# Cấu hình Staking
STAKING_POOL_WALLET_FILE = "staking_pool_wallet.pem"
STAKING_APR = Decimal('15.0')
INTEREST_RATE_PER_SECOND = STAKING_APR / Decimal(100) / Decimal(365 * 24 * 60 * 60)
REWARD_CALCULATION_INTERVAL = 3600

# Mô hình kinh tế
P2P_FEE_PERCENT = Decimal('0.5')
PRICE_PER_100_VIEWS = Decimal('1.0')
PLATFORM_FEE_PERCENT = Decimal('20.0')
PRICE_PER_VIEW = PRICE_PER_100_VIEWS / 100
REWARD_AMOUNT = PRICE_PER_VIEW * (1 - PLATFORM_FEE_PERCENT / 100)

# Cấu hình Mô hình Kinh tế Bảo chứng
ECON_DATA_FILE = "sok_econ_data_v10.json"
ECON_CHART_FILE = os.path.join("static", "sok_valuation_chart.html")
ECON_ANALYSIS_INTERVAL = 300
ECON_INITIAL_TREASURY_USD = Decimal('10000.0')
ECON_INITIAL_TOTAL_SUPPLY = Decimal('10000000.0')
ECON_W_TX_GROWTH = Decimal('0.5')
ECON_W_WORKER_GROWTH = Decimal('0.3')
ECON_W_WEBSITE_GROWTH = Decimal('0.2')

# Cấu hình Logic khác
PAYMENT_COOLDOWN_SECONDS = 180
WORKER_TIMEOUT_SECONDS = 180
NODE_HEALTH_CHECK_TIMEOUT = 5
MINIMUM_FUNDING_AMOUNT = PRICE_PER_100_VIEWS / 2
SAVE_STATE_INTERVAL = 300
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"

def setup_logging():
    log_format = '%(asctime)s [SOK_Server] [%(threadName)-18s] [%(levelname)s] - %(message)s'
    logger = logging.getLogger(); logger.setLevel(logging.INFO)
    if logger.hasHandlers(): logger.handlers.clear()
    formatter = logging.Formatter(log_format)
    file_handler = logging.FileHandler("sok_server.log", 'w', encoding='utf-8')
    file_handler.setFormatter(formatter); logger.addHandler(file_handler)
    console_handler = logging.StreamHandler(sys.stdout)
    console_handler.setFormatter(formatter); logger.addHandler(console_handler)

app = Flask(__name__, static_folder='static', template_folder='templates')
CORS(app)
log = logging.getLogger('werkzeug'); log.disabled = True
app.logger.disabled = True

class CustomJSONEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj, Decimal): return str(obj)
        return super(CustomJSONEncoder, self).default(obj)

app.json_encoder = CustomJSONEncoder

class PrimeAgentLogic:
    # --- __init__ và các hàm khởi tạo/lưu/tải state giữ nguyên ---
    def __init__(self):
        self.wallet = self._initialize_wallet(PRIME_WALLET_FILE, "Kho bạc & Ký quỹ P2P")
        self.staking_pool_wallet = self._initialize_wallet(STAKING_POOL_WALLET_FILE, "Quỹ Staking")
        self.reward_queue = Queue()
        self.active_workers: Dict[str, Dict] = {}
        self.last_reward_times: Dict[str, float] = {}
        self.state_lock = threading.RLock()
        self.websites_db: Dict[str, Dict] = {}
        self.current_best_node: Optional[str] = None
        self.is_running = threading.Event(); self.is_running.set()
        self.last_scanned_block = -1
        self.total_views_completed_session = 0
        self.p2p_orders: Dict[str, Dict] = {}
        self.public_key_cache: Dict[str, str] = {}
        self.staking_records: Dict[str, Dict] = {}
        self.historical_econ_data = []
        self.treasury_value_usd = ECON_INITIAL_TREASURY_USD

    def _initialize_wallet(self, filename: str, wallet_name: str) -> Wallet:
        logging.info(f"Đang khởi tạo ví cho {wallet_name}...")
        try:
            if not os.path.exists(filename):
                wallet = Wallet()
                with open(filename, "w", encoding='utf-8') as f: f.write(wallet.get_private_key_pem())
            else:
                with open(filename, 'r', encoding='utf-8') as f: wallet = Wallet(private_key_pem=f.read())
            logging.info(f"ID của {wallet_name}: {wallet.get_address()}")
            return wallet
        except Exception as e:
            logging.critical(f"Không thể tải/tạo ví {wallet_name}: {e}", exc_info=True); sys.exit(1)

    def _load_state(self):
        if os.path.exists(STATE_FILE):
            try:
                with self.state_lock, open(STATE_FILE, 'r', encoding='utf-8') as f:
                    state = json.load(f)
                    self.active_workers = state.get("active_workers", {})
                    self.last_reward_times = state.get("last_reward_times", {})
                    raw_db = state.get("websites_db", {})
                    self.websites_db = {url: {k: Decimal(v) if k in ['views_funded', 'views_completed'] else v for k, v in data.items()} for url, data in raw_db.items()}
                    self.last_scanned_block = state.get("last_scanned_block", -1)
                    raw_p2p = state.get("p2p_orders", {})
                    self.p2p_orders = {oid: {k: Decimal(v) if k == 'sok_amount' else v for k, v in data.items()} for oid, data in raw_p2p.items()}
                    self.public_key_cache = state.get("public_key_cache", {})
                    raw_stake = state.get("staking_records", {})
                    self.staking_records = {addr: {k: Decimal(v) if k in ['principal', 'reward'] else v for k, v in data.items()} for addr, data in raw_stake.items()}
                    self.treasury_value_usd = Decimal(state.get('treasury_value_usd', str(ECON_INITIAL_TREASURY_USD)))
                    logging.info(f"Đã khôi phục trạng thái: {len(self.active_workers)} worker, {len(self.websites_db)} website, Quỹ=${float(self.treasury_value_usd):.2f}")
            except Exception as e: logging.error(f"Không thể tải tệp trạng thái: {e}")

    def _save_state(self):
        with self.state_lock:
            state = {
                "active_workers": self.active_workers, "last_reward_times": self.last_reward_times,
                "websites_db": self.websites_db, "last_scanned_block": self.last_scanned_block,
                "p2p_orders": self.p2p_orders, "public_key_cache": self.public_key_cache,
                "staking_records": self.staking_records, "treasury_value_usd": str(self.treasury_value_usd)
            }
        try:
            with open(STATE_FILE + ".tmp", 'w', encoding='utf-8') as f: json.dump(state, f, indent=2, cls=CustomJSONEncoder)
            os.replace(STATE_FILE + ".tmp", STATE_FILE)
            logging.info("Đã lưu trạng thái vào file.")
        except Exception as e: logging.error(f"Lỗi khi lưu trạng thái: {e}")

    # --- Các luồng nền giữ nguyên ---
    def start_background_threads(self):
        self._load_state()
        logging.info("="*60)
        logging.info("MÔ HÌNH KINH TẾ BẢO CHỨNG ĐANG CHẠY:")
        logging.info(f"- Tổng cung SOK: {ECON_INITIAL_TOTAL_SUPPLY:,.0f}")
        logging.info(f"- Quỹ Bảo chứng Ban đầu: ${ECON_INITIAL_TREASURY_USD:,.2f}")
        logging.info(f"- GIÁ SÀN TỐI THIỂU: ${float(ECON_INITIAL_TREASURY_USD/ECON_INITIAL_TOTAL_SUPPLY):.8f}")
        logging.info("="*60)
        threads = [
            threading.Thread(target=self.find_best_node_loop, name="Node-Finder", daemon=True),
            threading.Thread(target=self.payment_loop, name="Worker-Payer", daemon=True),
            threading.Thread(target=self.cleanup_workers_loop, name="Cleaner", daemon=True),
            threading.Thread(target=self.funding_scanner_loop, name="Funding-Scanner", daemon=True),
            threading.Thread(target=self.periodic_save_loop, name="State-Saver", daemon=True),
            threading.Thread(target=self._calculate_rewards_loop, name="Staking-Rewarder", daemon=True),
            threading.Thread(target=self._econ_cycle_loop, name="Economist-Agent", daemon=True)
        ]
        for t in threads: t.start()

    def periodic_save_loop(self):
        logging.info("Luồng Lưu trạng thái định kỳ đã bắt đầu.")
        while self.is_running.is_set():
            time.sleep(SAVE_STATE_INTERVAL)
            self._save_state()

    def find_best_node_loop(self):
        logging.info("Luồng Tìm kiếm Node đã bắt đầu.")
        while self.is_running.is_set():
            nodes = set([BLOCKCHAIN_NODE_URL])
            for config_file in [LIVE_NETWORK_CONFIG_FILE, BOOTSTRAP_CONFIG_FILE]:
                if os.path.exists(config_file):
                    try:
                        with open(config_file, 'r', encoding='utf-8') as f: data = json.load(f)
                        nodes.update(data.get("active_nodes", []))
                        if "trusted_bootstrap_peers" in data:
                            nodes.update([p.get("last_known_address") for p in data["trusted_bootstrap_peers"].values()])
                    except Exception: pass
            known_nodes = list(filter(None, nodes))
            if not known_nodes:
                logging.warning("Không có node nào trong cấu hình để quét."); time.sleep(60); continue
            healthy_nodes = []
            for node_url in known_nodes:
                try:
                    response = requests.get(f'{node_url}/chain', timeout=NODE_HEALTH_CHECK_TIMEOUT)
                    if response.status_code == 200: healthy_nodes.append({"url": node_url, "block_height": response.json().get('length', -1)})
                except: pass
            with self.state_lock:
                if healthy_nodes:
                    best_node = max(healthy_nodes, key=lambda x: x['block_height'])
                    if self.current_best_node != best_node['url']:
                        logging.info(f"✅ Node tốt nhất mới: {best_node['url']} (Block: {best_node['block_height']})")
                        self.current_best_node = best_node['url']
                else:
                    if self.current_best_node: logging.error("Mất kết nối với tất cả các node.")
                    self.current_best_node = None
            time.sleep(120)

    def payment_loop(self):
        logging.info("Luồng Trả thưởng đã bắt đầu.")
        while self.is_running.is_set():
            worker_address = None
            try:
                worker_address = self.reward_queue.get(timeout=1)
                with self.state_lock:
                    last_paid = self.last_reward_times.get(worker_address, 0)
                    node = self.current_best_node
                if time.time() - last_paid < PAYMENT_COOLDOWN_SECONDS: continue
                if not node:
                    self.reward_queue.put(worker_address); time.sleep(10); continue
                tx = Transaction(self.wallet.get_public_key_pem(), worker_address, float(REWARD_AMOUNT), sender_address=self.wallet.get_address())
                tx.sign(self.wallet.private_key)
                response = requests.post(f"{node}/transactions/new", json=tx.to_dict(), timeout=10)
                if response.status_code == 201:
                    logging.info(f"🚀 Giao dịch trả thưởng {float(REWARD_AMOUNT):.8f} SOK cho {worker_address[:10]}... đã được gửi!")
                    with self.state_lock: self.last_reward_times[worker_address] = time.time()
                else: self.reward_queue.put(worker_address); time.sleep(5)
            except Empty: continue
            except Exception as e:
                logging.error(f"Lỗi luồng trả thưởng: {e}", exc_info=True)
                if worker_address: self.reward_queue.put(worker_address)
                time.sleep(10)

    def cleanup_workers_loop(self):
        logging.info("Luồng Dọn dẹp Worker đã bắt đầu.")
        while self.is_running.is_set():
            with self.state_lock:
                inactive = [addr for addr, data in self.active_workers.items() if time.time() - data.get("last_seen", 0) > WORKER_TIMEOUT_SECONDS]
                for addr in inactive:
                    del self.active_workers[addr]
                    logging.warning(f"Worker {addr[:10]}... đã offline. Đã xóa.")
            time.sleep(60)

    def funding_scanner_loop(self):
        logging.info("Luồng Quét Thanh toán đã bắt đầu.")
        while self.is_running.is_set():
            with self.state_lock:
                node = self.current_best_node
                last_block = self.last_scanned_block
            if not node: time.sleep(30); continue
            try:
                response = requests.get(f"{node}/chain", timeout=10)
                if response.status_code != 200:
                    logging.warning(f"Scanner: Node {node} trả về lỗi {response.status_code}"); time.sleep(60); continue
                chain = response.json().get('chain', [])
            except requests.RequestException as e:
                logging.error(f"Scanner: Lỗi kết nối đến node: {e}"); time.sleep(60); continue
            with self.state_lock:
                p2p_escrow_address = self.wallet.get_address()
                staking_pool_address = self.staking_pool_wallet.get_address()
                latest_block_in_chain = last_block
                for block in chain:
                    if block['index'] > last_block:
                        latest_block_in_chain = max(latest_block_in_chain, block['index'])
                        txs = json.loads(block.get('transactions', '[]')) if isinstance(block.get('transactions'), str) else block.get('transactions', [])
                        for tx in txs:
                            sender, recipient = tx.get('sender_address'), tx.get('recipient_address')
                            if sender and sender != "0" and sender not in self.public_key_cache:
                                self.public_key_cache[sender] = tx.get('sender_public_key')
                            amount = Decimal(str(tx.get('amount', '0')))
                            if recipient == staking_pool_address and sender != "0": self._process_stake_deposit(sender, amount)
                            elif recipient == p2p_escrow_address and sender != "0":
                                if not self._check_and_process_p2p_deposit(sender, amount, tx.get('tx_hash')) and amount >= MINIMUM_FUNDING_AMOUNT:
                                    self.credit_views_to_owner(sender, amount)
                self.last_scanned_block = latest_block_in_chain
            time.sleep(60)
            
    def _calculate_rewards_loop(self):
        logging.info("Luồng tính lãi Staking đã bắt đầu.")
        while self.is_running.is_set():
            time.sleep(REWARD_CALCULATION_INTERVAL)
            with self.state_lock:
                if not self.staking_records: continue
                current_time = time.time()
                for record in self.staking_records.values():
                    time_diff = Decimal(current_time - record['last_update'])
                    new_reward = record['principal'] * INTEREST_RATE_PER_SECOND * time_diff
                    record['reward'] += new_reward
                    record['last_update'] = current_time
            logging.info("Hoàn tất chu kỳ tính lãi staking.")

    # --- Các hàm logic nghiệp vụ (P2P, Staking, Econ) giữ nguyên ---
    def _get_public_key_for_address(self, address: str) -> Optional[str]:
        with self.state_lock:
            if address in self.public_key_cache: return self.public_key_cache[address]
            node = self.current_best_node
        if not node: return None
        logging.warning(f"Không tìm thấy public key trong cache cho {address}. Đang quét blockchain...")
        try:
            chain_len_resp = requests.get(f"{node}/chain", timeout=5).json()
            start_block = max(0, chain_len_resp.get('length', 0) - 500)
            response = requests.get(f"{node}/chain?start={start_block}", timeout=10)
            for block in reversed(response.json().get('chain', [])):
                txs = json.loads(block.get('transactions', '[]')) if isinstance(block.get('transactions'), str) else block.get('transactions', [])
                for tx in txs:
                    if tx.get('sender_address') == address:
                        pub_key = tx.get('sender_public_key')
                        with self.state_lock: self.public_key_cache[address] = pub_key
                        logging.info(f"Đã tìm thấy và cache public key cho {address}.")
                        return pub_key
        except Exception as e: logging.error(f"Lỗi khi quét tìm public key cho {address}: {e}")
        return None

    def p2p_confirm_fiat_and_release(self, order_id: str, seller_address: str, signature: str):
        with self.state_lock:
            order = self.p2p_orders.get(order_id)
            if not order: return {"error": "Không tìm thấy lệnh."}, 404
            if order['seller_address'] != seller_address: return {"error": "Địa chỉ không khớp."}, 403
            if order['status'] != 'PENDING_PAYMENT': return {"error": "Trạng thái lệnh không hợp lệ."}, 409
        seller_public_key = self._get_public_key_for_address(seller_address)
        if not seller_public_key: return {"error": "Không thể xác định khóa công khai."}, 400
        message_to_verify = f"confirm_p2p_{order_id}"
        if not verify_signature(seller_public_key, signature, message_to_verify): return {"error": "Chữ ký không hợp lệ."}, 401
        with self.state_lock: node = self.current_best_node
        if not node: return {"error": "Không thể kết nối blockchain."}, 503
        amount_to_send = order['sok_amount']
        fee = amount_to_send * (P2P_FEE_PERCENT / 100)
        final_amount = float(amount_to_send - fee)
        try:
            tx = Transaction(self.wallet.get_public_key_pem(), order['buyer_address'], final_amount, sender_address=self.wallet.get_address())
            tx.sign(self.wallet.private_key)
            response = requests.post(f"{node}/transactions/new", json=tx.to_dict(), timeout=10)
            if response.status_code != 201: return {"error": "Lỗi gửi giao dịch."}, 500
        except Exception as e: return {"error": "Lỗi hệ thống."}, 500
        with self.state_lock: self.p2p_orders[order_id]['status'] = 'COMPLETED'
        logging.info(f"✅ Giao dịch P2P hoàn tất! Đã giải ngân {final_amount:.8f} SOK.")
        return {"message": f"Xác nhận thành công! {final_amount:.8f} SOK đã được chuyển."}, 200

    def credit_views_to_owner(self, owner_address: str, amount: Decimal):
        views_to_add = int(amount / PRICE_PER_VIEW)
        with self.state_lock:
            target_url = next((url for url, data in self.websites_db.items() if data.get("owner") == owner_address and data.get("views_funded", Decimal('0')) == 0), None)
            if target_url:
                self.websites_db[target_url]["views_funded"] += Decimal(views_to_add)
                logging.info(f"✅ Đã cộng {views_to_add} lượt xem cho {owner_address[:10]}...")
            else:
                logging.warning(f"Nhận {amount} SOK từ {owner_address[:10]} nhưng không có web chờ thanh toán.")

    def _check_and_process_p2p_deposit(self, sender_address, amount, tx_hash):
        with self.state_lock:
            for order in self.p2p_orders.values():
                if order['status'] == 'AWAITING_DEPOSIT' and order['seller_address'] == sender_address and Decimal(order['sok_amount']) == amount:
                    order['status'] = 'OPEN'; order['tx_hash_proof'] = tx_hash
                    logging.info(f"💰 Ký quỹ P2P thành công cho lệnh #{order['id'][:8]}.")
                    return True
        return False

    def p2p_create_order(self, seller_address, sok_amount_str, fiat_details):
        try: sok_amount = Decimal(sok_amount_str)
        except: return {"error": "Số SOK không hợp lệ"}, 400
        if sok_amount <= 0: return {"error": "Số SOK phải lớn hơn 0"}, 400
        order_id = str(uuid.uuid4())
        new_order = {"id": order_id, "seller_address": seller_address, "sok_amount": sok_amount, "fiat_details": fiat_details, "status": "AWAITING_DEPOSIT", "buyer_address": None, "created_at": time.time()}
        with self.state_lock: self.p2p_orders[order_id] = new_order
        logging.info(f"Lệnh P2P #{order_id[:8]} đã được tạo. Chờ ký quỹ.")
        return {"message": "Tạo lệnh thành công.", "order": new_order, "escrow_address": self.wallet.get_address()}, 201

    def p2p_accept_order(self, order_id, buyer_address):
        with self.state_lock:
            order = self.p2p_orders.get(order_id)
            if not order: return {"error": "Không tìm thấy lệnh."}, 404
            if order['status'] != 'OPEN': return {"error": "Lệnh này không có sẵn."}, 409
            if order['seller_address'] == buyer_address: return {"error": "Bạn không thể tự mua lệnh của mình."}, 403
            order['status'] = 'PENDING_PAYMENT'; order['buyer_address'] = buyer_address
        logging.info(f"Lệnh P2P #{order_id[:8]} đã được chấp nhận bởi {buyer_address[:10]}.")
        return {"message": "Chấp nhận lệnh thành công."}, 200

    def _process_stake_deposit(self, staker_address: str, amount: Decimal):
        with self.state_lock:
            logging.info(f"💰 STAKE DEPOSIT: Nhận được {amount} SOK từ {staker_address[:15]}...")
            if staker_address in self.staking_records:
                record = self.staking_records[staker_address]
                time_diff = Decimal(time.time() - record['last_update'])
                new_reward = record['principal'] * INTEREST_RATE_PER_SECOND * time_diff
                record['reward'] += new_reward; record['principal'] += amount
                record['last_update'] = time.time()
            else:
                self.staking_records[staker_address] = {"principal": amount, "reward": Decimal('0'), "last_update": time.time()}

    def stake_get_info(self):
        with self.state_lock: node = self.current_best_node
        balance = "0"
        if node:
            try:
                response = requests.get(f"{node}/balance/{self.staking_pool_wallet.get_address()}", timeout=5)
                if response.status_code == 200: balance = response.json().get("balance", "0")
            except: pass
        return {"apr": str(STAKING_APR), "staking_pool_address": self.staking_pool_wallet.get_address(), "total_staked": str(balance)}
        
    def stake_get_user_record(self, address: str):
        with self.state_lock:
            record = self.staking_records.get(address)
            if not record: return {"principal": "0", "reward": "0"}
            time_diff = Decimal(time.time() - record['last_update'])
            latest_reward = record['reward'] + (record['principal'] * INTEREST_RATE_PER_SECOND * time_diff)
        return {"principal": record['principal'], "reward": latest_reward}

    def stake_claim_rewards(self, staker_address: str, signature: str):
        with self.state_lock:
            record = self.staking_records.get(staker_address)
            if not record: return {"error": "Không tìm thấy khoản stake nào."}, 404
            time_diff = Decimal(time.time() - record['last_update'])
            final_reward = record['reward'] + (record['principal'] * INTEREST_RATE_PER_SECOND * time_diff)
            total_claim_amount = record['principal'] + final_reward
        pub_key = self._get_public_key_for_address(staker_address)
        if not pub_key: return {"error": "Không tìm thấy khóa công khai."}, 400
        message_to_verify = f"claim_stake_{staker_address}"
        if not verify_signature(pub_key, signature, message_to_verify): return {"error": "Chữ ký không hợp lệ."}, 401
        with self.state_lock: node = self.current_best_node
        if not node: return {"error": "Không thể kết nối blockchain."}, 503
        try:
            tx = Transaction(self.staking_pool_wallet.get_public_key_pem(), staker_address, float(total_claim_amount), sender_address=self.staking_pool_wallet.get_address())
            tx.sign(self.staking_pool_wallet.private_key)
            response = requests.post(f"{node}/transactions/new", json=tx.to_dict(), timeout=10)
            if response.status_code != 201: return {"error": f"Lỗi từ node: {response.text}"}, 500
        except Exception as e: return {"error": f"Lỗi hệ thống: {e}"}, 500
        with self.state_lock: del self.staking_records[staker_address]
        logging.info(f"✅ Đã giải ngân STAKE {float(total_claim_amount):.8f} SOK.")
        return {"message": f"Yêu cầu rút {float(total_claim_amount):.8f} SOK đã được xử lý!"}, 200

    def _econ_load_data(self):
        if not os.path.exists(ECON_DATA_FILE): return
        try:
            with open(ECON_DATA_FILE, 'r', encoding='utf-8') as f:
                self.historical_econ_data = json.load(f, parse_float=Decimal)
                logging.info(f"Agent Kinh tế: Đã tải {len(self.historical_econ_data)} điểm dữ liệu lịch sử.")
        except Exception as e: logging.error(f"Agent Kinh tế: Không thể tải dữ liệu lịch sử: {e}")

    def _econ_save_data(self):
        try:
            with open(ECON_DATA_FILE, 'w', encoding='utf-8') as f:
                json.dump(self.historical_econ_data, f, indent=2, cls=CustomJSONEncoder)
        except IOError as e: logging.error(f"Agent Kinh tế: Không thể lưu dữ liệu: {e}")

    def _econ_generate_chart(self):
        if len(self.historical_econ_data) < 2: return
        try:
            data_copy = self.historical_econ_data[:]
            timestamps = [datetime.fromtimestamp(float(d['timestamp'])) for d in data_copy]
            market_prices = [float(d['market_price_usd']) for d in data_copy]
            floor_prices = [float(d['floor_price_usd']) for d in data_copy]
            treasury_values = [float(d.get('treasury_value_usd', 0)) for d in data_copy]
            fig = go.Figure()
            fig.add_trace(go.Scatter(x=timestamps, y=floor_prices, mode='lines', name='Giá Sàn (Bảo chứng)', line=dict(color='green', dash='dot')))
            fig.add_trace(go.Scatter(x=timestamps, y=market_prices, mode='lines+markers', name='Giá Thị trường (Ước tính)', line=dict(color='blue')))
            fig.add_trace(go.Bar(x=timestamps, y=treasury_values, name='Tổng Quỹ Bảo chứng (USD)', yaxis='y2', marker_color='lightsalmon', opacity=0.6))
            fig.update_layout(title_text='<b>Mô hình Định giá Bảo chứng & Sức khỏe Mạng lưới Sokchain</b>', yaxis=dict(title='<b>Giá SOK (USD)</b>', type='log'), yaxis2=dict(title='Giá trị Quỹ (USD)', overlaying='y', side='right', showgrid=False), legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01), template='plotly_dark', hovermode='x unified')
            fig.write_html(ECON_CHART_FILE)
            logging.info(f"Agent Kinh tế: ✅ Biểu đồ đã được cập nhật.")
        except Exception as e:
            logging.error(f"Agent Kinh tế: Lỗi khi tạo biểu đồ: {e}", exc_info=True)

    def _econ_get_current_metrics(self):
        with self.state_lock:
            node = self.current_best_node
            staking_pool_addr = self.staking_pool_wallet.get_address()
        staked_balance, blockchain_height = Decimal('0'), 0
        if node:
            try:
                res = requests.get(f"{node}/balance/{staking_pool_addr}", timeout=5)
                if res.ok: staked_balance = Decimal(res.json().get("balance", "0"))
                res = requests.get(f"{node}/chain", timeout=5)
                if res.ok: blockchain_height = res.json().get("length", 0)
            except: pass
        with self.state_lock:
            total_p2p_escrow = sum(o['sok_amount'] for o in self.p2p_orders.values() if o['status'] == 'OPEN')
            return {"total_workers": len(self.active_workers), "total_websites": len(self.websites_db), "total_staked_sok": staked_balance, "total_p2p_escrow_sok": total_p2p_escrow, "total_transactions": blockchain_height}

    def _econ_run_cycle(self):
        logging.info("Agent Kinh tế: Bắt đầu chu kỳ phân tích...")
        current_metrics = self._econ_get_current_metrics()
        current_metrics["timestamp"] = time.time()
        last_analysis = self.historical_econ_data[-1] if self.historical_econ_data else None
        if last_analysis:
            last_market_price = Decimal(str(last_analysis.get('market_price_usd', ECON_INITIAL_TREASURY_USD / ECON_INITIAL_TOTAL_SUPPLY)))
            new_transactions = current_metrics['total_transactions'] - last_analysis.get('total_transactions', 0)
            avg_fee_percent = (PLATFORM_FEE_PERCENT + P2P_FEE_PERCENT) / 2 / 100
            revenue_sok = Decimal(str(new_transactions)) * Decimal('1.0') * avg_fee_percent
            revenue_usd = revenue_sok * last_market_price
            with self.state_lock:
                self.treasury_value_usd += revenue_usd
                if revenue_usd > 0: logging.info(f"Agent Kinh tế: Đã tích lũy thêm ${float(revenue_usd):.6f} vào Quỹ Bảo chứng.")
        with self.state_lock: current_treasury_usd = self.treasury_value_usd
        total_supply = ECON_INITIAL_TOTAL_SUPPLY
        floor_price_usd = current_treasury_usd / total_supply
        if not last_analysis:
            activity_multiplier = Decimal('0.0')
        else:
            tx_growth = (current_metrics['total_transactions'] - last_analysis.get('total_transactions', 0)) / (last_analysis.get('total_transactions', 1) or 1)
            worker_growth = (current_metrics['total_workers'] - last_analysis.get('total_workers', 0)) / (last_analysis.get('total_workers', 1) or 1)
            website_growth = (current_metrics['total_websites'] - last_analysis.get('total_websites', 0)) / (last_analysis.get('total_websites', 1) or 1)
            smoothed_tx_growth = Decimal(str(math.log1p(max(0, tx_growth))))
            smoothed_worker_growth = Decimal(str(math.log1p(max(0, worker_growth))))
            smoothed_website_growth = Decimal(str(math.log1p(max(0, website_growth))))
            activity_multiplier = (ECON_W_TX_GROWTH * smoothed_tx_growth) + (ECON_W_WORKER_GROWTH * smoothed_worker_growth) + (ECON_W_WEBSITE_GROWTH * smoothed_website_growth)
        current_price_usd = floor_price_usd * (Decimal('1.0') + activity_multiplier)
        analysis_result = {**current_metrics, "floor_price_usd": floor_price_usd, "market_price_usd": current_price_usd, "activity_multiplier": activity_multiplier, "treasury_value_usd": current_treasury_usd}
        logging.info(f"Agent Kinh tế: Quỹ=${float(analysis_result['treasury_value_usd']):.2f} | Giá Sàn=${float(analysis_result['floor_price_usd']):.8f} | Giá Thị trường=${float(analysis_result['market_price_usd']):.8f}")
        self.historical_econ_data.append(analysis_result)
        self._econ_save_data()
        self._econ_generate_chart()

    def _econ_cycle_loop(self):
        self._econ_load_data()
        while self.is_running.is_set():
            try:
                self._econ_run_cycle()
                time.sleep(ECON_ANALYSIS_INTERVAL)
            except Exception as e:
                logging.error(f"Agent Kinh tế: Lỗi nghiêm trọng trong vòng lặp: {e}", exc_info=True)
                time.sleep(60)

    def shutdown(self):
        if self.is_running.is_set():
            print("\n\nĐang dừng Server..."); self.is_running.clear()
            self._save_state(); logging.info("Server đã dừng.")

core_logic = PrimeAgentLogic()

# --- CÁC API ENDPOINTS ---

# --- Các routes render template giữ nguyên ---
@app.route('/')
def dashboard_page(): return render_template('dashboard.html')
@app.route('/manage')
def manage_page(): return render_template('manage.html')
@app.route('/market')
def market_page(): return render_template('p2p_market.html')
@app.route('/stake')
def stake_page(): return render_template('stake.html')

# --- Các API endpoint khác giữ nguyên, chỉ thêm các endpoint mới ---

# [BẢO MẬT NÂNG CAO] API Mới để nhận giao dịch đã ký sẵn
@app.route('/api/v1/transactions/broadcast', methods=['POST'])
def broadcast_signed_transaction():
    signed_tx_data = request.get_json()
    if not all(key in signed_tx_data for key in ['sender_address', 'recipient_address', 'amount', 'timestamp', 'tx_hash', 'signature']):
        return jsonify({"error": "Dữ liệu giao dịch không đầy đủ."}), 400
    try:
        sender_public_key = core_logic._get_public_key_for_address(signed_tx_data['sender_address'])
        if not sender_public_key:
            return jsonify({"error": "Không thể xác thực người gửi. Người dùng cần có ít nhất một giao dịch đã thực hiện trên mạng."}), 400
        tx_to_verify = Transaction(
            sender_public_key_pem=sender_public_key,
            recipient_address=signed_tx_data['recipient_address'],
            amount=float(signed_tx_data['amount']),
            timestamp=signed_tx_data['timestamp'],
            sender_address=signed_tx_data['sender_address']
        )
        if tx_to_verify.tx_hash != signed_tx_data['tx_hash']:
            return jsonify({"error": "Hash giao dịch không hợp lệ."}), 400
        if not tx_to_verify.verify_signature(signed_tx_data['signature']):
            logging.warning(f"XÁC THỰC GIAO DỊCH THẤT BẠI từ {signed_tx_data['sender_address']}")
            return jsonify({"error": "Chữ ký giao dịch không hợp lệ."}), 401
    except Exception as e:
        logging.error(f"Lỗi nghiêm trọng khi xác thực giao dịch đã ký: {e}", exc_info=True)
        return jsonify({"error": "Lỗi nội bộ khi xác thực giao dịch."}), 500
    with core_logic.state_lock:
        node_to_use = core_logic.current_best_node or BLOCKCHAIN_NODE_URL
    if not node_to_use:
        return jsonify({"error": "Không thể kết nối đến mạng lưới blockchain."}), 503
    try:
        response = requests.post(f"{node_to_use}/transactions/new", json=signed_tx_data, timeout=10)
        response.raise_for_status()
        logging.info(f"Đã gửi thành công giao dịch đã ký từ {signed_tx_data['sender_address'][:10]}...")
        return jsonify(response.json()), response.status_code
    except requests.RequestException as e:
        logging.error(f"Không thể gửi giao dịch đã ký đến node {node_to_use}: {e}")
        return jsonify({"error": f"Lỗi khi giao tiếp với node blockchain: {str(e)}"}), 504

# [TỐI ƯU HÓA] API Mới cho Biểu đồ Kinh tế
@app.route('/api/v1/econ_chart_data', methods=['GET'])
def get_econ_chart_data():
    with core_logic.state_lock:
        data_points = core_logic.historical_econ_data[-200:] # Giới hạn 200 điểm dữ liệu
    chart_data = {
        "timestamps": [d['timestamp'] for d in data_points],
        "market_prices": [d['market_price_usd'] for d in data_points],
        "floor_prices": [d['floor_price_usd'] for d in data_points],
        "treasury_values": [d.get('treasury_value_usd', 0) for d in data_points]
    }
    return jsonify(chart_data)


@app.route('/heartbeat', methods=['POST'])
def heartbeat():
    data = request.get_json()
    if data and 'worker_address' in data:
        worker_address = data['worker_address']
        worker_type = data.get('worker_type', 'view_worker')
        worker_status = data.get('status', 'AVAILABLE')
        with core_logic.state_lock:
            if worker_address not in core_logic.active_workers:
                logging.info(f"Worker MỚI ({worker_type}): {worker_address[:10]}...")
            core_logic.active_workers[worker_address] = {
                "last_seen": time.time(), "ip": request.remote_addr, "type": worker_type, "status": worker_status
            }
    return jsonify({"status": "ok"})

@app.route('/explorer')
def explorer_page():
    # Flask sẽ tự động tìm file 'sokchain_explorer.html' bên trong thư mục 'static'
    # mà chúng ta đã cấu hình khi khởi tạo app.
    return app.send_static_file('sokchain_explorer.html')

@app.route('/api/v1/workers/list_by_type', methods=['GET'])
def list_workers_by_type():
    with core_logic.state_lock:
        backlink_workers, view_workers = [], []
        for address, data in core_logic.active_workers.items():
            worker_info = { "address": address, "last_seen": data.get("last_seen", 0), "status": data.get("status", "AVAILABLE") }
            if data.get('type') == 'backlink_service': backlink_workers.append(worker_info)
            else: view_workers.append(worker_info)
    current_time = time.time()
    sort_key = lambda w: (current_time - w['last_seen']) > WORKER_TIMEOUT_SECONDS
    backlink_workers.sort(key=sort_key); view_workers.sort(key=sort_key)
    return jsonify({'backlink_service': backlink_workers, 'view_worker': view_workers})

@app.route('/api/v1/dashboard_stats')
def get_dashboard_stats():
    with core_logic.state_lock:
        active_workers = len(core_logic.active_workers)
        total_websites = len(core_logic.websites_db)
        views_completed = core_logic.total_views_completed_session
        open_p2p_orders = len([o for o in core_logic.p2p_orders.values() if o['status'] == 'OPEN'])
        total_stakers = len(core_logic.staking_records)
    chain_height = -1; node_to_use = core_logic.current_best_node or BLOCKCHAIN_NODE_URL
    try:
        response = requests.get(f"{node_to_use}/chain", timeout=3)
        if response.status_code == 200: chain_height = response.json().get('length', 0)
    except: pass 
    return jsonify({
        "active_workers": active_workers, "total_websites": total_websites,
        "views_completed_session": views_completed, "blockchain_height": chain_height,
        "status": "Online" if core_logic.current_best_node else "Connecting...",
        "open_p2p_orders": open_p2p_orders, "total_stakers": total_stakers
    })

@app.route('/api/create_wallet', methods=['POST'])
def create_wallet_api():
    wallet = Wallet()
    return jsonify({"address": wallet.get_address(), "public_key_pem": wallet.get_public_key_pem(), "private_key_pem": wallet.get_private_key_pem()})

@app.route('/api/wallet_from_pk', methods=['POST'])
def get_wallet_from_pk():
    data = request.get_json(); pk_pem = data.get('private_key_pem')
    if not pk_pem: return jsonify({"error": "Thiếu Private Key PEM."}), 400
    try:
        wallet = Wallet(private_key_pem=pk_pem)
        return jsonify({"address": wallet.get_address(), "public_key_pem": wallet.get_public_key_pem()})
    except Exception: return jsonify({"error": "Private Key không hợp lệ."}), 400

@app.route('/api/get_balance/<address>', methods=['GET'])
def get_balance_api(address):
    node_to_use = core_logic.current_best_node or BLOCKCHAIN_NODE_URL
    try:
        response = requests.get(f"{node_to_use}/balance/{address}", timeout=5)
        response.raise_for_status(); return jsonify(response.json())
    except requests.exceptions.RequestException:
        return jsonify({"error": "Không thể kết nối đến node blockchain"}), 503

# [KHÔNG AN TOÀN - SẼ ĐƯỢC LOẠI BỎ] Giữ lại để tương thích ngược tạm thời.
# Cảnh báo: Endpoint này nhận private key và rất không an toàn.
# Nâng cấp frontend để sử dụng /api/v1/transactions/broadcast thay thế.
@app.route('/api/direct_fund', methods=['POST'])
def direct_fund_api():
    logging.warning("!!! CẢNH BÁO BẢO MẬT: Endpoint không an toàn /api/direct_fund đã được gọi.")
    data = request.get_json(); pk_pem = data.get('private_key_pem'); recipient = data.get('recipient_address'); amount_str = data.get('amount')
    if not all([pk_pem, recipient, amount_str]): return jsonify({"error": "Thiếu thông tin."}), 400
    try:
        sender_wallet = Wallet(private_key_pem=pk_pem); sender_address = sender_wallet.get_address(); amount = float(amount_str)
        node_to_use = core_logic.current_best_node or BLOCKCHAIN_NODE_URL
        balance_resp = requests.get(f"{node_to_use}/balance/{sender_address}", timeout=5)
        if balance_resp.json().get('balance', 0) < amount: return jsonify({"error": "Số dư không đủ."}), 402
        tx = Transaction(sender_wallet.get_public_key_pem(), recipient, amount, sender_address=sender_address)
        tx.sign(sender_wallet.private_key)
        broadcast_resp = requests.post(f"{node_to_use}/transactions/new", json=tx.to_dict(), timeout=10)
        broadcast_resp.raise_for_status()
        return jsonify({"message": f"Đã gửi thành công {amount} SOK!"}), 201
    except Exception: return jsonify({"error": "Lỗi server khi xử lý giao dịch."}), 500

@app.route('/ping', methods=['GET'])
def ping(): return jsonify({"status": "alive"})

@app.route('/api/v1/payment_info', methods=['GET'])
def get_payment_info():
    return jsonify({ 
        "treasury_address": core_logic.wallet.get_address(), "price_per_100_views": str(PRICE_PER_100_VIEWS), 
        "minimum_funding": str(MINIMUM_FUNDING_AMOUNT), "p2p_fee_percent": str(P2P_FEE_PERCENT)
    })

@app.route('/api/v1/websites/add', methods=['POST'])
def add_website():
    data = request.get_json(); new_url = data.get('url', '').strip(); owner_pk_pem = data.get('owner_pk_pem')
    if not (new_url and owner_pk_pem): return jsonify({"error": "Thiếu URL hoặc Public Key."}), 400
    if not (new_url.startswith('http://') or new_url.startswith('https://')): new_url = 'https://' + new_url
    try: owner_address = get_address_from_public_key_pem(owner_pk_pem)
    except Exception: return jsonify({"error": "Public Key không hợp lệ."}), 400
    with core_logic.state_lock:
        if any(w_url == new_url for w_url in core_logic.websites_db): return jsonify({"error": "Website đã tồn tại."}), 409
        core_logic.websites_db[new_url] = {"owner": owner_address, "views_funded": Decimal('0'), "views_completed": Decimal('0')}
    return jsonify({"message": f"Thêm website thành công! Vui lòng nạp SOK để kích hoạt."}), 201

@app.route('/api/v1/websites/list', methods=['GET'])
def list_websites():
    owner_address = request.args.get('owner')
    if not owner_address: return jsonify({"error": "Thiếu địa chỉ chủ sở hữu."}), 400
    with core_logic.state_lock:
        owner_sites = [{"url": url, "info": info} for url, info in core_logic.websites_db.items() if info.get("owner") == owner_address]
    return jsonify(owner_sites)

@app.route('/api/v1/websites/remove', methods=['POST'])
def remove_website():
    data = request.get_json(); url_to_remove = data.get('url'); owner_address = data.get('owner_address')
    if not (url_to_remove and owner_address): return jsonify({"error": "Thiếu thông tin."}), 400
    with core_logic.state_lock:
        if url_to_remove not in core_logic.websites_db: return jsonify({"error": "Website không tồn tại."}), 404
        if core_logic.websites_db[url_to_remove].get("owner") != owner_address: return jsonify({"error": "Bạn không có quyền xóa."}), 403
        del core_logic.websites_db[url_to_remove]; logging.info(f"🗑️  Website đã được xóa: {url_to_remove}")
    return jsonify({"message": f"Đã xóa thành công: {url_to_remove}"}), 200

@app.route('/api/v1/websites/get_one', methods=['GET'])
def get_website_to_view():
    with core_logic.state_lock:
        funded_websites = [url for url, data in core_logic.websites_db.items() if data.get("views_funded", Decimal('0')) > 0]
        if not funded_websites: return jsonify({"error": "Hiện tại đã hết website để xem."}), 404
        random_url = random.choice(funded_websites)
    return jsonify({"url": random_url, "viewId": f"view_{random_url}_{int(time.time() * 1000)}"})

@app.route('/api/v1/views/submit_proof', methods=['POST'])
def submit_view_proof():
    data = request.get_json(); view_id = data.get('viewId'); worker_address = data.get('worker_address')
    if not (view_id and worker_address): return jsonify({"error": "Dữ liệu không hợp lệ."}), 400
    try:
        url_viewed = "_".join(view_id.split('_')[1:-1])
        with core_logic.state_lock:
            website_data = core_logic.websites_db.get(url_viewed)
            if website_data and website_data.get("views_funded", Decimal('0')) > 0:
                website_data["views_funded"] -= 1
                website_data["views_completed"] = website_data.get("views_completed", Decimal('0')) + 1
                core_logic.total_views_completed_session += 1
                core_logic.reward_queue.put(worker_address)
                return jsonify({"message": "Xác nhận thành công! Phần thưởng đang được xử lý."}), 200
            return jsonify({"error": "Website đã hết tín dụng hoặc không tồn tại."}), 402
    except Exception: return jsonify({"error": "Lỗi nội bộ server."}), 500

@app.route('/api/v1/p2p/orders/create', methods=['POST'])
def p2p_create_order_api():
    data = request.get_json()
    response, code = core_logic.p2p_create_order(data.get('seller_address'), data.get('sok_amount'), data.get('fiat_details'))
    return jsonify(response), code

@app.route('/api/v1/p2p/orders/list', methods=['GET'])
def p2p_list_orders_api():
    with core_logic.state_lock:
        open_orders = [o for o in core_logic.p2p_orders.values() if o['status'] == 'OPEN']
    return jsonify(sorted(open_orders, key=lambda x: x['created_at']))

@app.route('/api/v1/p2p/orders/<order_id>/accept', methods=['POST'])
def p2p_accept_order_api(order_id):
    data = request.get_json()
    response, code = core_logic.p2p_accept_order(order_id, data.get('buyer_address'))
    return jsonify(response), code

@app.route('/api/v1/p2p/orders/<order_id>/confirm', methods=['POST'])
def p2p_confirm_payment_api(order_id):
    data = request.get_json(); seller_address = data.get('address'); signature = data.get('signature')
    if not all([seller_address, signature]): return jsonify({"error": "Thiếu địa chỉ hoặc chữ ký."}), 400
    response, code = core_logic.p2p_confirm_fiat_and_release(order_id, seller_address, signature)
    return jsonify(response), code

@app.route('/api/v1/p2p/my_orders', methods=['GET'])
def p2p_get_my_orders_api():
    user_address = request.args.get('address')
    if not user_address: return jsonify({"error": "Thiếu địa chỉ ví."}), 400
    with core_logic.state_lock:
        my_orders = [o for o in core_logic.p2p_orders.values() if o['seller_address'] == user_address or o['buyer_address'] == user_address]
    return jsonify(sorted(my_orders, key=lambda x: x['created_at'], reverse=True))

@app.route('/api/v1/stake/info', methods=['GET'])
def get_stake_info_api(): return jsonify(core_logic.stake_get_info())

@app.route('/api/v1/stake/record/<address>', methods=['GET'])
def get_stake_record_api(address): return jsonify(core_logic.stake_get_user_record(address))

@app.route('/api/v1/stake/claim', methods=['POST'])
def claim_stake_api():
    data = request.get_json(); staker_address = data.get('address'); signature = data.get('signature')
    if not all([staker_address, signature]): return jsonify({"error": "Thiếu địa chỉ hoặc chữ ký."}), 400
    response, code = core_logic.stake_claim_rewards(staker_address, signature)
    return jsonify(response), code

# --- KHỞI ĐỘNG SERVER ---
if __name__ == '__main__':
    setup_logging()
    
    static_folder = os.path.join(project_root, 'static')
    templates_folder = os.path.join(project_root, 'templates')
    if not os.path.exists(static_folder):
        os.makedirs(static_folder); logging.info(f"Đã tạo thư mục '{static_folder}'.")
    if not os.path.exists(templates_folder):
        os.makedirs(templates_folder); logging.info(f"Đã tạo thư mục '{templates_folder}'.")

    try:
        core_logic = PrimeAgentLogic()
        core_logic.start_background_threads()
        try: lan_ip = socket.gethostbyname(socket.gethostname())
        except: lan_ip = '127.0.0.1'
        
        colorama_init(autoreset=True)
        print(Fore.CYAN + Style.BRIGHT + "="*70)
        print(Fore.GREEN + Style.BRIGHT + "      ΣOK CHAIN - ALL-IN-ONE SERVER (v12.0 - SECURE API)")
        print(Fore.YELLOW + "    " + "-"*62)
        print(Fore.WHITE +  f"    Server đang lắng nghe tại: http://{lan_ip}:{SERVER_PORT}")
        print(Fore.WHITE +  f"    Bảng điều khiển quản lý:   http://{lan_ip}:{SERVER_PORT}/manage")
        print(Fore.GREEN + f"    Chợ giao dịch P2P:         http://{lan_ip}:{SERVER_PORT}/market")
        print(Fore.MAGENTA + f"    Nền tảng Staking:          http://{lan_ip}:{SERVER_PORT}/stake")
        print(Fore.RED + Style.BRIGHT + "    [Bảo mật] API /direct_fund không an toàn, sẽ được loại bỏ.")
        print(Fore.YELLOW + "    " + "-"*62)
        print(Fore.CYAN + Style.DIM + "         The Complete Ecosystem. Forged in Conversation.")
        print(Fore.CYAN + Style.BRIGHT + "="*70)
        
        serve(app, host='0.0.0.0', port=SERVER_PORT, threads=18)
    except KeyboardInterrupt: pass
    finally: 
        if 'core_logic' in locals() and core_logic.is_running.is_set():
            core_logic.shutdown()
