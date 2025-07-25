# sok/node_api.py
# -*- coding: utf-8 -*-

import os
import json
import threading
from flask import Flask, jsonify, request
from flask_cors import CORS
import logging
from .transaction import Transaction
from .wallet import Wallet
from .blockchain import Block

logger = logging.getLogger(__name__)

# --- CÁC HÀM TRỢ GIÚP ĐỂ CẬP NHẬT FILE CỤC BỘ ---
project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
LIVE_NETWORK_CONFIG_FILE = os.path.join(project_root, 'live_network_nodes.json')

def update_local_map_file(nodes_list: list):
    try:
        sorted_nodes = sorted(list(set(nodes_list))) 
        temp_file = LIVE_NETWORK_CONFIG_FILE + ".tmp"
        with open(temp_file, 'w', encoding='utf-8') as f:
            json.dump({"active_nodes": sorted_nodes}, f, indent=2)
        os.replace(temp_file, LIVE_NETWORK_CONFIG_FILE)
        logger.info(f"[API] Đã cập nhật thành công tệp bản đồ mạng cục bộ '{os.path.basename(LIVE_NETWORK_CONFIG_FILE)}'")
    except Exception as e:
        logger.error(f"[API] Lỗi khi ghi tệp bản đồ mạng cục bộ: {e}")

def create_app(blockchain, p2p_manager, node_wallet: Wallet, genesis_wallet: Wallet = None):
    app = Flask(__name__)
    CORS(app)
    
    # === API ĐỂ LAN TRUYỀN BẢN ĐỒ MẠNG ===
    @app.route('/nodes/update_map', methods=['POST'])
    def update_network_map():
        data = request.get_json()
        if not data or 'active_nodes' not in data:
            return jsonify({'error': 'Dữ liệu không hợp lệ.'}), 400
        nodes_list = data['active_nodes']
        update_thread = threading.Thread(target=update_local_map_file, args=(nodes_list,))
        update_thread.start()
        return jsonify({'message': 'Đã nhận bản đồ.'}), 202

    # --- ENDPOINTS CHÍNH ---
    
    @app.route('/genesis/info', methods=['GET'])
    def get_genesis_info():
        # ... (giữ nguyên)
        if not genesis_wallet: return jsonify({'error': 'Forbidden.'}), 403
        return jsonify({ 'genesis_address': genesis_wallet.get_address(), 'current_balance': blockchain.get_balance(genesis_wallet.get_address()) }), 200
        
    @app.route('/handshake', methods=['GET'])
    def handshake():
        return jsonify({"node_id": node_wallet.get_address()}), 200

    @app.route('/nodes/peers', methods=['GET'])
    def get_peers():
        with blockchain.peer_lock:
            return jsonify(blockchain.peers), 200

    @app.route('/mine', methods=['GET'])
    def mine():
        miner_address = request.args.get('miner_address')
        if not miner_address: return jsonify({'error': 'Yêu cầu địa chỉ của thợ mỏ.'}), 400
        new_block = blockchain.mine_pending_transactions(miner_address)
        p2p_manager.broadcast_block(new_block)
        return jsonify({'message': 'Đã khai thác khối mới!', 'block': new_block.to_dict()}), 200

    @app.route('/transactions/new', methods=['POST'])
    def new_transaction():
        # ... (giữ nguyên)
        values = request.get_json()
        if not all(k in values for k in ['sender_public_key_pem', 'recipient_address', 'amount', 'signature']): return jsonify({'error': 'Thiếu trường dữ liệu.'}), 400
        tx = Transaction.from_dict(values)
        if not tx.is_valid(blockchain): return jsonify({'error': 'Giao dịch không hợp lệ.'}), 400
        if blockchain.add_transaction(values):
            p2p_manager.broadcast_transaction(values)
            return jsonify({'message': 'Giao dịch sẽ được thêm vào khối tiếp theo.'}), 201
        return jsonify({'message': 'Giao dịch đã tồn tại.'}), 400

    @app.route('/chain', methods=['GET'])
    def get_chain():
        chain_data = blockchain.get_full_chain_for_api()
        return jsonify({'chain': chain_data, 'length': len(chain_data)}), 200

    @app.route('/balance/<address>', methods=['GET'])
    def get_balance(address):
        if not address: return jsonify({'error': 'Địa chỉ không được để trống.'}), 400
        return jsonify({'address': address, 'balance': blockchain.get_balance(address)}), 200

    # === ENDPOINT QUAN TRỌNG MÀ THỢ MỎ ĐANG TÌM ===
    @app.route('/chain/stats', methods=['GET'])
    def get_chain_stats():
        """
        Cung cấp các số liệu thống kê chính của chuỗi.
        Đây là endpoint mà các client thông minh dùng để kiểm tra sức khỏe.
        """
        try:
            stats = {
                "total_supply": blockchain.calculate_actual_total_supply(), 
                "block_height": blockchain.last_block.index, 
                "pending_tx_count": len(blockchain.pending_transactions), 
                "difficulty": blockchain.difficulty,
                "peer_count": len(blockchain.peers)
            }
            return jsonify(stats), 200
        except Exception as e:
            logger.error(f"Lỗi khi lấy thống kê chuỗi: {e}")
            return jsonify({"error": "Không thể xử lý yêu cầu thống kê."}), 500

    # ... các endpoint P2P khác giữ nguyên
            
    return app
