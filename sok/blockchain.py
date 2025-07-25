# sok/blockchain.py
# -*- coding: utf-8 -*-

import time
import requests
import json
import os
import sqlite3
import threading
import logging  # <-- SỬA LỖI: THÊM DÒNG NÀY
from typing import List, Optional, Any, Dict
from urllib.parse import urlparse
from .utils import Config, hash_data

class Block:
    # Lớp Block giữ nguyên
    def __init__(self, index: int, previous_hash: str, timestamp: float, transactions: List[Dict], nonce: int = 0):
        self.index: int = index
        self.previous_hash: str = previous_hash
        self.timestamp: float = timestamp
        self.transactions: List[Dict] = transactions
        self.nonce: int = nonce
        self.hash: str = self.calculate_hash()
    def calculate_hash(self) -> str:
        block_data = { 'index': self.index, 'previous_hash': self.previous_hash, 'timestamp': self.timestamp, 'transactions': self.transactions, 'nonce': self.nonce }
        return hash_data(block_data)
    def to_dict(self) -> Dict[str, Any]:
        return self.__dict__
    @staticmethod
    def from_dict(block_data: Dict[str, Any]) -> 'Block':
        return Block(index=block_data['index'], previous_hash=block_data['previous_hash'], timestamp=block_data['timestamp'], transactions=block_data['transactions'], nonce=block_data['nonce'])

class Blockchain:
    def __init__(self, db_path: str, difficulty: Optional[int] = None):
        self.pending_transactions: List[Dict] = []
        self.difficulty: int = difficulty if difficulty is not None else Config.DIFFICULTY
        self.peers: Dict[str, Dict[str, Any]] = {}
        self.peer_lock = threading.Lock()
        self.mining_lock = threading.Lock()
        self.seen_transaction_hashes = set()
        self.conn = sqlite3.connect(db_path, check_same_thread=False)
        self.conn.row_factory = sqlite3.Row 
        self._create_tables()
        cursor = self.conn.cursor()
        cursor.execute('SELECT MAX("index") FROM blocks')
        result = cursor.fetchone()
        if result is None or result[0] is None:
            logging.info("Phát hiện cơ sở dữ liệu trống. Đang tạo khối Sáng thế (Genesis)...")
            self.create_genesis_block()
    
    def register_node(self, node_id: str, node_address: str) -> bool:
        with self.peer_lock:
            parsed_url = urlparse(node_address)
            netloc = parsed_url.netloc or parsed_url.path
            if not netloc: return False
            address = f"http://{netloc.replace('http://', '').replace('https://', '')}"
            if address and node_id:
                # Chỉ log nếu là peer mới hoặc địa chỉ thay đổi
                if node_id not in self.peers or self.peers[node_id]['address'] != address:
                    logging.info(f"[Blockchain] Đã đăng ký/cập nhật peer: {node_id[:15]}... tại {address}")
                self.peers[node_id] = {"address": address, "last_seen": time.time()}
                return True
        return False
        
    def merge_peers(self, peers_from_other_node: Dict[str, Dict[str, Any]], self_node_id: str):
        with self.peer_lock:
            new_peers_found = 0
            for node_id, peer_data in peers_from_other_node.items():
                if node_id != self_node_id and node_id not in self.peers:
                    self.peers[node_id] = peer_data
                    new_peers_found += 1
            if new_peers_found > 0:
                logging.info(f"[Blockchain] Đã học được về {new_peers_found} peer mới thông qua PEX.")
    
    def _create_tables(self):
        cursor = self.conn.cursor()
        cursor.execute(""" CREATE TABLE IF NOT EXISTS blocks ("index" INTEGER PRIMARY KEY, hash TEXT NOT NULL UNIQUE, previous_hash TEXT NOT NULL, timestamp REAL NOT NULL, nonce INTEGER NOT NULL, transactions TEXT NOT NULL) """)
        cursor.execute(""" CREATE TABLE IF NOT EXISTS balances (address TEXT PRIMARY KEY, balance REAL NOT NULL) """)
        self.conn.commit()
    @property
    def last_block(self) -> Block:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM blocks ORDER BY "index" DESC LIMIT 1')
        row = cursor.fetchone()
        if not row: raise Exception("Không tìm thấy khối nào trong cơ sở dữ liệu!")
        # Đảm bảo transactions được load đúng cách
        block_dict = dict(row)
        if isinstance(block_dict['transactions'], str):
            block_dict['transactions'] = json.loads(block_dict['transactions'])
        return Block.from_dict(block_dict)
        
    def _add_block_to_db(self, block: Block):
        try:
            cursor = self.conn.cursor()
            
            # Chuyển transactions sang chuỗi JSON để lưu
            transactions_json = json.dumps([tx for tx in block.transactions])

            cursor.execute('INSERT INTO blocks ("index", hash, previous_hash, timestamp, nonce, transactions) VALUES (?, ?, ?, ?, ?, ?)', 
                           (block.index, block.hash, block.previous_hash, block.timestamp, block.nonce, transactions_json))

            senders_to_update, recipients_to_update, new_recipients_data = [], [], []
            all_recipients = {tx.get('recipient_address') for tx in block.transactions if tx.get('recipient_address')}
            
            for recipient in all_recipients: 
                new_recipients_data.append((recipient, 0.0))
            if new_recipients_data: 
                cursor.executemany("INSERT OR IGNORE INTO balances (address, balance) VALUES (?, ?)", new_recipients_data)

            for tx in block.transactions:
                sender_addr = tx.get('sender_address')
                recipient_addr = tx.get('recipient_address')
                amount = float(tx.get('amount', 0))
                
                # Không trừ tiền từ địa chỉ "0" (giao dịch thưởng/genesis)
                if sender_addr and sender_addr != "0": 
                    senders_to_update.append((amount, sender_addr))
                if recipient_addr: 
                    recipients_to_update.append((amount, recipient_addr))

            if senders_to_update: 
                cursor.executemany("UPDATE balances SET balance = balance - ? WHERE address = ?", senders_to_update)
            if recipients_to_update: 
                cursor.executemany("UPDATE balances SET balance = balance + ? WHERE address = ?", recipients_to_update)
            
            self.conn.commit()
        except Exception as e:
            self.conn.rollback()
            logging.error(f"LỖI DB: Giao dịch cơ sở dữ liệu đã được hoàn tác. Lỗi: {e}")
            raise

    def add_transaction(self, transaction: Dict) -> bool:
        tx_content_for_hash = {k: v for k, v in transaction.items() if k not in ['signature', 'sender_address']}
        tx_hash = hash_data(tx_content_for_hash)
        if tx_hash in self.seen_transaction_hashes: return False
        self.pending_transactions.append(transaction)
        self.seen_transaction_hashes.add(tx_hash)
        return True

    def mine_pending_transactions(self, miner_address: str) -> Block:
        with self.mining_lock:
            reward_tx = { 'sender_public_key_pem': "0", 'sender_address': "0", 'recipient_address': miner_address, 'amount': self.get_current_mining_reward(), 'timestamp': time.time(), 'signature': "mining_reward" }
            transactions_for_block = [reward_tx] + self.pending_transactions
            last_b = self.last_block
            new_block = Block(index=last_b.index + 1, previous_hash=last_b.hash, timestamp=time.time(), transactions=transactions_for_block)
            self.proof_of_work(new_block)
            self._add_block_to_db(new_block)
            tx_hashes_in_block = {hash_data({k: v for k, v in tx.items() if k not in ['signature', 'sender_address']}) for tx in self.pending_transactions}
            self.seen_transaction_hashes -= tx_hashes_in_block
            self.pending_transactions = []
            return new_block

    def add_block_from_peer(self, block_data: Dict) -> bool:
        with self.mining_lock:
            last_b = self.last_block
            if block_data.get('index') != last_b.index + 1 or block_data.get('previous_hash') != last_b.hash: return False
            block = Block.from_dict(block_data)
            if block.hash != block.calculate_hash(): return False
            self._add_block_to_db(block)
            tx_hashes_in_block = {hash_data({k: v for k, v in tx.items() if k not in ['signature', 'sender_address']}) for tx in block.transactions}
            self.pending_transactions = [tx for tx in self.pending_transactions if hash_data({k: v for k, v in tx.items() if k not in ['signature', 'sender_address']}) not in tx_hashes_in_block]
            self.seen_transaction_hashes -= tx_hashes_in_block
        return True

    def create_genesis_block(self):
        genesis_tx = { 'sender_public_key_pem': "0", 'sender_address': "0", 'recipient_address': Config.FOUNDER_ADDRESS, 'amount': Config.INITIAL_SUPPLY_TOKENS, 'timestamp': time.time(), 'signature': "genesis_transaction" }
        genesis_block = Block(index=0, previous_hash=Config.GENESIS_PREVIOUS_HASH, timestamp=time.time(), transactions=[genesis_tx], nonce=Config.GENESIS_NONCE)
        self._add_block_to_db(genesis_block)
        logging.info("✅ Khối Sáng thế đã được tạo và lưu vào SQLite.")

    def get_current_mining_reward(self) -> float:
        halvings = (self.last_block.index + 1) // Config.HALVING_BLOCK_INTERVAL
        return Config.MINING_REWARD / (2 ** halvings)

    def proof_of_work(self, block: Block):
        target = "0" * self.difficulty
        while not block.hash.startswith(target):
            block.nonce += 1
            block.hash = block.calculate_hash()

    def get_balance(self, address: str) -> float:
        cursor = self.conn.cursor()
        cursor.execute("SELECT balance FROM balances WHERE address = ?", (address,))
        row = cursor.fetchone()
        return row['balance'] if row else 0.0

    def get_full_chain_for_api(self) -> List[Dict]:
        cursor = self.conn.cursor()
        cursor.execute('SELECT * FROM blocks ORDER BY "index" ASC')
        rows = cursor.fetchall()
        chain = [dict(row) for row in rows]
        return chain
    
    @staticmethod
    def is_chain_valid(chain_to_validate: List[Dict]) -> bool:
        if not chain_to_validate: return False
        try:
            # Tải lại transactions từ chuỗi JSON nếu cần
            for block_dict in chain_to_validate:
                if isinstance(block_dict['transactions'], str):
                    block_dict['transactions'] = json.loads(block_dict['transactions'])

            genesis_block = Block.from_dict(chain_to_validate[0])
            if genesis_block.index != 0 or genesis_block.previous_hash != Config.GENESIS_PREVIOUS_HASH: return False
            for i in range(1, len(chain_to_validate)):
                current_block, previous_block = Block.from_dict(chain_to_validate[i]), Block.from_dict(chain_to_validate[i-1])
                if current_block.previous_hash != previous_block.hash: return False
                if current_block.hash != current_block.calculate_hash(): return False
        except (KeyError, TypeError, json.JSONDecodeError): return False
        return True

    def resolve_conflicts(self) -> bool:
        new_chain_data, max_length = None, self.last_block.index + 1
        with self.peer_lock: peer_addresses = [peer_data['address'] for peer_data in self.peers.values()]
        for address in peer_addresses:
            try:
                response = requests.get(f'{address}/chain', timeout=3)
                if response.status_code == 200:
                    length = response.json()['length']
                    chain_from_node = response.json()['chain']
                    if length > max_length and self.is_chain_valid(chain_from_node):
                        max_length, new_chain_data = length, chain_from_node
            except requests.exceptions.RequestException: continue
        
        if new_chain_data:
            try:
                cursor = self.conn.cursor()
                cursor.execute("DELETE FROM blocks"); cursor.execute("DELETE FROM balances")
                self.conn.commit() # Commit các lệnh xóa
                
                # Tải lại transactions từ chuỗi JSON
                for block_data in new_chain_data:
                    if isinstance(block_data['transactions'], str):
                       block_data['transactions'] = json.loads(block_data['transactions'])
                    self._add_block_to_db(Block.from_dict(block_data))
                
                logging.info("✅ Đã thay thế chuỗi thành công!")
                return True
            except Exception as e:
                self.conn.rollback()
                logging.error(f"Lỗi khi thay thế chuỗi, đã hoàn tác: {e}")
                return False
        return False

    def calculate_actual_total_supply(self) -> float:
        try:
            cursor = self.conn.cursor()
            cursor.execute("SELECT SUM(balance) FROM balances")
            result = cursor.fetchone()
            return float(result[0]) if result and result[0] is not None else 0.0
        except Exception as e:
            logging.error(f"LỖI DB khi tính tổng cung: {e}")
            return 0.0
