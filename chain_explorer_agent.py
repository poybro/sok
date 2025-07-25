#!/usr/bin/env python3
# chain_explorer_agent.py - Tác nhân Phân tích & Trình diễn Blockchain

# -*- coding: utf-8 -*-

"""
Tác nhân Trình khám phá Chuỗi (Chain Explorer Agent).
- Hoạt động liên tục trong nền.
- Tự động tìm node mạng tốt nhất để lấy dữ liệu.
- Lấy toàn bộ dữ liệu blockchain và các số liệu thống kê.
- Phân tích, định dạng và tạo ra một tệp HTML báo cáo trực quan.
- Tự động cập nhật tệp HTML sau mỗi khoảng thời gian nhất định.
"""

import os
import sys
import requests
import json
import time
import logging
from datetime import datetime

# --- THIẾT LẬP MÔI TRƯỜNG ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- CẤU HÌNH ---
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"
OUTPUT_HTML_FILE = "sokchain_explorer.html"
REFRESH_INTERVAL_SECONDS = 60  # Cập nhật mỗi phút
NODE_HEALTH_CHECK_TIMEOUT = 5

# Cấu hình logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s [ExplorerAgent] [%(levelname)s] - %(message)s',
    encoding='utf-8',
    handlers=[
        logging.StreamHandler(sys.stdout)
    ]
)

def load_all_known_nodes() -> list[str]:
    """Tải danh sách tất cả các node tiềm năng từ các tệp cấu hình."""
    # (Hàm này được tái sử dụng từ các agent khác để đảm bảo tính nhất quán)
    if os.path.exists(LIVE_NETWORK_CONFIG_FILE):
        try:
            with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                nodes = data.get("active_nodes", [])
                if nodes: return nodes
        except Exception as e:
            logging.error(f"Lỗi khi đọc tệp bản đồ mạng: {e}.")

    if os.path.exists(BOOTSTRAP_CONFIG_FILE):
        try:
            with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                data = json.load(f)
                peers = data.get("trusted_bootstrap_peers", {})
                if peers:
                    return [p.get("last_known_address") for p in peers.values() if p.get("last_known_address")]
        except Exception as e:
            logging.error(f"Lỗi khi đọc tệp cấu hình bootstrap: {e}.")
    return []

def find_best_node() -> str | None:
    """Quét mạng và chọn node tốt nhất (chuỗi dài nhất) để lấy dữ liệu."""
    known_nodes = load_all_known_nodes()
    if not known_nodes:
        return None

    healthy_nodes = []
    for node_url in known_nodes:
        try:
            response = requests.get(f'{node_url}/chain/stats', timeout=NODE_HEALTH_CHECK_TIMEOUT)
            if response.status_code == 200:
                stats = response.json()
                healthy_nodes.append({"url": node_url, "block_height": stats.get('block_height', -1)})
        except requests.exceptions.RequestException:
            continue
    
    if not healthy_nodes:
        return None

    return sorted(healthy_nodes, key=lambda x: x['block_height'], reverse=True)[0]['url']


def generate_explorer_html(chain_data: list, stats_data: dict, last_update_time: float) -> str:
    """
    Tạo nội dung HTML hoàn chỉnh cho trình khám phá chuỗi.
    """
    # Bắt đầu với CSS để trang trí
    html = """
    <!DOCTYPE html>
    <html lang="vi">
    <head>
        <meta charset="UTF-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Sokchain Explorer</title>
        <style>
            body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Helvetica, Arial, sans-serif; background-color: #f4f7f9; color: #333; margin: 0; padding: 20px; }
            .container { max-width: 1200px; margin: auto; }
            h1 { color: #2c3e50; text-align: center; border-bottom: 2px solid #e0e0e0; padding-bottom: 10px; }
            .header-stats { display: flex; justify-content: space-around; flex-wrap: wrap; margin: 20px 0; background: #fff; padding: 15px; border-radius: 8px; box-shadow: 0 2px 5px rgba(0,0,0,0.05); }
            .stat-box { text-align: center; padding: 10px 20px; }
            .stat-box h3 { margin: 0 0 5px 0; color: #7f8c8d; font-size: 14px; text-transform: uppercase; }
            .stat-box p { margin: 0; color: #3498db; font-size: 22px; font-weight: 600; }
            .update-info { text-align: center; font-size: 12px; color: #95a5a6; margin-bottom: 20px; }
            .blockchain-container { display: flex; flex-direction: column-reverse; } /* Hiển thị khối mới nhất lên đầu */
            .block-card { background: #ffffff; border: 1px solid #e0e6ed; border-radius: 8px; margin-bottom: 20px; box-shadow: 0 4px 8px rgba(0,0,0,0.07); transition: all 0.2s ease-in-out; }
            .block-card:hover { box-shadow: 0 6px 12px rgba(0,0,0,0.1); transform: translateY(-3px); }
            .block-header { background-color: #ecf0f1; padding: 10px 15px; border-bottom: 1px solid #e0e6ed; font-weight: bold; font-size: 20px; color: #2980b9; }
            .block-header .index { font-weight: 800; }
            .block-details { padding: 15px; display: grid; grid-template-columns: 150px 1fr; gap: 8px 15px; font-size: 14px; }
            .detail-label { font-weight: 600; color: #7f8c8d; }
            .detail-value { word-wrap: break-word; font-family: 'Menlo', 'Consolas', monospace; }
            .hash { color: #27ae60; }
            .timestamp { color: #8e44ad; }
            .nonce { color: #f39c12; }
            h4 { margin-top: 20px; padding-left: 15px; color: #34495e; }
            .transaction-list { list-style: none; padding: 0 15px 15px 15px; margin: 0; }
            .tx-item { padding: 12px; border-top: 1px dashed #e0e6ed; display: grid; grid-template-columns: auto 1fr auto; gap: 15px; align-items: center;}
            .tx-item:first-child { border-top: 1px solid #bdc3c7; }
            .tx-type { font-weight: bold; font-size: 12px; padding: 3px 8px; border-radius: 12px; text-transform: uppercase; }
            .tx-reward { background-color: #e67e22; color: white; }
            .tx-genesis { background-color: #9b59b6; color: white; }
            .tx-normal { background-color: #3498db; color: white; }
            .tx-details { font-family: 'Menlo', 'Consolas', monospace; font-size: 13px; line-height: 1.5; }
            .address { color: #2980b9; }
            .amount { font-weight: bold; color: #c0392b; justify-self: end; font-size: 16px; }
        </style>
    </head>
    <body>
        <div class="container">
            <h1>Sokchain Explorer</h1>
    """

    # Phần Header Stats
    last_update_str = datetime.fromtimestamp(last_update_time).strftime('%H:%M:%S %d-%m-%Y')
    html += f"""
        <div class="header-stats">
            <div class="stat-box">
                <h3>Chiều cao khối</h3>
                <p>{stats_data.get('block_height', 'N/A')}</p>
            </div>
            <div class="stat-box">
                <h3>Tổng Cung</h3>
                <p>{stats_data.get('total_supply', 0.0):,.4f}</p>
            </div>
            <div class="stat-box">
                <h3>Giao dịch chờ</h3>
                <p>{stats_data.get('pending_tx_count', 'N/A')}</p>
            </div>
            <div class="stat-box">
                <h3>Số Node mạng</h3>
                <p>{stats_data.get('peer_count', 'N/A')}</p>
            </div>
        </div>
        <div class="update-info">Cập nhật lần cuối: {last_update_str}</div>
        <div class="blockchain-container">
    """

    # Phần danh sách các khối
    previous_block_time = None
    for block in chain_data:
        block_time = datetime.fromtimestamp(block['timestamp'])
        
        time_diff_str = ""
        if previous_block_time:
            time_diff = (previous_block_time - block_time).total_seconds()
            time_diff_str = f" ({time_diff:,.2f}s so với khối trước)"
        
        html += f"""
        <div class="block-card">
            <div class="block-header">Khối <span class="index">#{block['index']}</span></div>
            <div class="block-details">
                <span class="detail-label">Hash:</span>
                <span class="detail-value hash">{block['hash']}</span>

                <span class="detail-label">Hash Khối Trước:</span>
                <span class="detail-value hash">{block['previous_hash']}</span>

                <span class="detail-label">Thời gian:</span>
                <span class="detail-value timestamp">{block_time.strftime('%H:%M:%S %d-%m-%Y')}{time_diff_str}</span>

                <span class="detail-label">Nonce:</span>
                <span class="detail-value nonce">{block['nonce']}</span>
            </div>
            <h4>Giao dịch trong khối ({len(block['transactions'])})</h4>
            <ul class="transaction-list">
        """
        
        for tx in block['transactions']:
            tx_sender = tx.get('sender_address')
            tx_recipient = tx.get('recipient_address')
            tx_amount = tx.get('amount', 0.0)

            if tx_sender == "0":
                if tx.get('signature') == "genesis_transaction":
                    html += f"""
                    <li class="tx-item">
                        <span class="tx-type tx-genesis">Genesis</span>
                        <div class="tx-details">
                            Tạo ra quỹ ban đầu cho <strong>{tx_recipient[:20]}...</strong>
                        </div>
                        <span class="amount">+{tx_amount:,.4f} SOK</span>
                    </li>
                    """
                else:
                    html += f"""
                    <li class="tx-item">
                        <span class="tx-type tx-reward">Thưởng</span>
                        <div class="tx-details">
                            Phần thưởng khai thác cho thợ mỏ <strong>{tx_recipient[:20]}...</strong>
                        </div>
                        <span class="amount">+{tx_amount:,.4f} SOK</span>
                    </li>
                    """
            else:
                html += f"""
                <li class="tx-item">
                    <span class="tx-type tx-normal">Chuyển</span>
                    <div class="tx-details">
                        TỪ <span class="address">{tx_sender}</span><br>
                        ĐẾN <span class="address">{tx_recipient}</span>
                    </div>
                    <span class="amount">{tx_amount:,.4f} SOK</span>
                </li>
                """
        html += "</ul></div>"
        previous_block_time = block_time

    # Đóng các thẻ HTML
    html += """
        </div></div>
    </body>
    </html>
    """
    return html


class ExplorerAgent:
    def __init__(self):
        self.best_node = None

    def _fetch_data(self, node_url: str):
        """Lấy dữ liệu chuỗi và thống kê từ một node cụ thể."""
        try:
            logging.info(f"Đang lấy dữ liệu từ node: {node_url}...")
            chain_resp = requests.get(f'{node_url}/chain', timeout=20)
            stats_resp = requests.get(f'{node_url}/chain/stats', timeout=10)

            if chain_resp.status_code == 200 and stats_resp.status_code == 200:
                chain_data = chain_resp.json().get('chain', [])
                stats_data = stats_resp.json()
                # Tải lại các giao dịch từ chuỗi JSON
                for block in chain_data:
                    if isinstance(block.get('transactions'), str):
                        block['transactions'] = json.loads(block['transactions'])
                return chain_data, stats_data
            return None, None
        except requests.exceptions.RequestException as e:
            logging.error(f"Không thể lấy dữ liệu từ {node_url}: {e}")
            return None, None

    def run(self):
        """Vòng lặp chính của Agent."""
        logging.info("--- Khởi động Tác nhân Trình khám phá Chuỗi (Explorer Agent) ---")
        while True:
            try:
                logging.info("Đang tìm kiếm node mạng tốt nhất...")
                self.best_node = find_best_node()
                
                if not self.best_node:
                    logging.warning("Không tìm thấy node nào đang hoạt động. Sẽ thử lại sau 30 giây.")
                    time.sleep(30)
                    continue

                chain_data, stats_data = self._fetch_data(self.best_node)

                if chain_data and stats_data:
                    logging.info("Đang tạo tệp HTML trình khám phá...")
                    html_content = generate_explorer_html(chain_data, stats_data, time.time())
                    
                    # Ghi tệp một cách an toàn (atomic write)
                    temp_file = OUTPUT_HTML_FILE + ".tmp"
                    with open(temp_file, 'w', encoding='utf-8') as f:
                        f.write(html_content)
                    os.replace(temp_file, OUTPUT_HTML_FILE)
                    
                    logging.info(f"✅ Đã cập nhật thành công! Mở tệp '{os.path.abspath(OUTPUT_HTML_FILE)}' để xem.")
                else:
                    logging.error("Lấy dữ liệu từ node thất bại.")

                logging.info(f"Sẽ cập nhật lại sau {REFRESH_INTERVAL_SECONDS} giây.")
                time.sleep(REFRESH_INTERVAL_SECONDS)

            except KeyboardInterrupt:
                logging.info("\nĐã dừng Tác nhân Trình khám phá.")
                break
            except Exception as e:
                logging.error(f"Lỗi nghiêm trọng trong vòng lặp chính: {e}", exc_info=True)
                time.sleep(60)

if __name__ == "__main__":
    agent = ExplorerAgent()
    agent.run()
