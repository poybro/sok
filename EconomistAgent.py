# -*- coding: utf-8 -*-
# EconomistAgent_v3_Debug.py
# PHIÊN BẢN GỠ LỖI: Tăng cường ghi log để xác định điểm bị treo.

import os
import sys
import time
import requests
import json
import logging
import math
import plotly.graph_objects as go
from datetime import datetime

# --- THÊM ĐƯỜNG DẪN DỰ ÁN SOKCHAIN ---
project_root = os.path.abspath(os.path.dirname(__file__))
if project_root not in sys.path:
    sys.path.insert(0, project_root)

# --- CẤU HÌNH ---
DATA_FILE = "sok_econ_data_v3.json"
TREASURY_FILE = "sok_treasury_v3.json"
OUTPUT_HTML_FILE = "sok_valuation_chart_v3.html"
# <<< THAY ĐỔI GỠ LỖI >>>: Giảm thời gian chờ xuống 60 giây để dễ theo dõi
COLLECTION_INTERVAL_SECONDS = 60 

# --- CẤU HÌNH MÔ HÌNH KINH TẾ ---
INITIAL_SUPPLY = 10000000.0
INITIAL_PRICE_USD = 0.001
INITIAL_TREASURY_USD = INITIAL_SUPPLY * INITIAL_PRICE_USD
WORKSTATION_MONTHLY_FEE_USD = 200.0
NODES_PER_WORKSTATION = 7
ASSUMED_VALUE_PER_TX_USD = 0.0005 
W_TX_GROWTH = 0.5
W_NODE_GROWTH = 0.3
W_DIFFICULTY_GROWTH = 0.2
SPECULATIVE_MULTIPLIER_DECAY = 0.05
MAX_GROWTH_FACTOR_PER_CYCLE = 0.10

# --- CẤU HÌNH MẠNG ---
LIVE_NETWORK_CONFIG_FILE = "live_network_nodes.json"
BOOTSTRAP_CONFIG_FILE = "bootstrap_config.json"
NODE_HEALTH_CHECK_TIMEOUT = 5

# <<< THAY ĐỔI GỠ LỖI >>>: Bật chế độ DEBUG để xem thông tin chi tiết nhất
logging.basicConfig(level=logging.DEBUG, format='%(asctime)s [EconomistAgent v3-Debug] [%(levelname)s] - %(message)s')

# =========================================================================
# === CÁC HÀM TIỆN ÍCH MẠNG (Hoạt động độc lập) ============================
# =========================================================================
def load_all_known_nodes() -> list[str]:
    nodes = []
    logging.debug(f"Đang tải danh sách node từ '{LIVE_NETWORK_CONFIG_FILE}' và '{BOOTSTRAP_CONFIG_FILE}'...")
    if os.path.exists(LIVE_NETWORK_CONFIG_FILE):
        try:
            with open(LIVE_NETWORK_CONFIG_FILE, 'r', encoding='utf-8') as f:
                loaded_nodes = json.load(f).get("active_nodes", [])
                nodes.extend(loaded_nodes)
                logging.debug(f"Đã tìm thấy {len(loaded_nodes)} node từ live_network_nodes.json")
        except Exception as e:
            logging.error(f"Lỗi khi đọc tệp bản đồ mạng: {e}")
    if os.path.exists(BOOTSTRAP_CONFIG_FILE):
        try:
            with open(BOOTSTRAP_CONFIG_FILE, 'r', encoding='utf-8') as f:
                peers = json.load(f).get("trusted_bootstrap_peers", {})
                loaded_nodes = [p.get("last_known_address") for p in peers.values() if p.get("last_known_address")]
                nodes.extend(loaded_nodes)
                logging.debug(f"Đã tìm thấy {len(loaded_nodes)} node từ bootstrap_config.json")
        except Exception as e:
            logging.error(f"Lỗi khi đọc tệp cấu hình bootstrap: {e}")
    
    unique_nodes = sorted(list(set(nodes)))
    logging.debug(f"Tổng số node duy nhất đã biết: {len(unique_nodes)}. Danh sách: {unique_nodes}")
    return unique_nodes

def find_best_node() -> str | None:
    logging.debug("Bắt đầu quá trình tìm node tốt nhất...")
    known_nodes = load_all_known_nodes()
    if not known_nodes:
        logging.warning("Không có node nào được định nghĩa trong các tệp cấu hình.")
        return None
    
    healthy_nodes = []
    for node_url in known_nodes:
        logging.debug(f"Đang kiểm tra node: {node_url}...")
        try:
            response = requests.get(f'{node_url}/chain/stats', timeout=NODE_HEALTH_CHECK_TIMEOUT)
            if response.status_code == 200:
                stats = response.json()
                block_height = stats.get('block_height', -1)
                logging.debug(f"  -> THÀNH CÔNG! Node {node_url} đang hoạt động, chiều cao khối: {block_height}")
                healthy_nodes.append({"url": node_url, "block_height": block_height})
            else:
                 logging.warning(f"  -> THẤT BẠI. Node {node_url} phản hồi với mã trạng thái {response.status_code}")
        except requests.exceptions.RequestException as e:
            logging.warning(f"  -> THẤT BẠI. Không thể kết nối đến node {node_url}. Lỗi: {e}")
            continue
            
    if not healthy_nodes:
        logging.error("QUAN TRỌNG: Đã kiểm tra tất cả các node đã biết nhưng không có node nào hoạt động.")
        return None
    
    best_node = sorted(healthy_nodes, key=lambda x: x['block_height'], reverse=True)[0]
    logging.info(f"Đã chọn node tốt nhất: {best_node['url']} (chiều cao khối: {best_node['block_height']})")
    return best_node['url']

# ===================================================================
# === CÁC HÀM LOGIC CHÍNH (Giữ nguyên) ===========================================
# ===================================================================

def load_data(file_path):
    if not os.path.exists(file_path): return None
    try:
        with open(file_path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except (IOError, json.JSONDecodeError): return None

def save_data(data, file_path):
    try:
        with open(file_path, 'w', encoding='utf-8') as f:
            json.dump(data, f, indent=2)
    except IOError as e:
        logging.error(f"Không thể lưu dữ liệu vào {file_path}: {e}")

def generate_chart(historical_data):
    if len(historical_data) < 2:
        logging.debug("Cần ít nhất 2 điểm dữ liệu để vẽ biểu đồ.")
        return

    logging.debug("Bắt đầu tạo biểu đồ...")
    timestamps = [datetime.fromtimestamp(d['timestamp']) for d in historical_data]
    market_prices = [d['market_price'] for d in historical_data]
    floor_prices = [d['floor_price'] for d in historical_data]
    workstation_counts = [d.get('number_of_workstations', 0) for d in historical_data]
    
    fig = go.Figure()
    fig.add_trace(go.Scatter(x=timestamps, y=floor_prices, mode='lines', name='Giá trị Sàn (Nội tại)', line=dict(color='grey', dash='dot'), yaxis='y1'))
    fig.add_trace(go.Scatter(x=timestamps, y=market_prices, mode='lines+markers', name='Giá trị Thị trường (Ước tính)', line=dict(color='blue'), yaxis='y1'))
    fig.add_trace(go.Bar(x=timestamps, y=workstation_counts, name='Số Workstation (Đang hoạt động)', yaxis='y2', marker_color='lightsalmon', opacity=0.6))
    fig.add_trace(go.Scatter(x=timestamps + timestamps[::-1], y=market_prices + floor_prices[::-1], fill='toself', fillcolor='rgba(0,100,80,0.2)', line=dict(color='rgba(255,255,255,0)'), hoverinfo="none", name='Phần bù Thặng dư'))

    fig.update_layout(
        title_text='<b>Mô hình Định giá Kép Mở Rộng và Sức khỏe Mạng lưới Sokchain</b>',
        xaxis_title='Thời gian',
        yaxis=dict(title='<b>Giá SOK (USD)</b>', color='blue', type='log'),
        yaxis2=dict(title='Số Workstation', overlaying='y', side='right', showgrid=False, color='salmon', range=[0, max(workstation_counts)*2 if workstation_counts else 10]),
        legend=dict(yanchor="top", y=0.99, xanchor="left", x=0.01),
        template='plotly_white',
        hovermode='x unified'
    )
    
    fig.write_html(OUTPUT_HTML_FILE)
    logging.info(f"✅ Biểu đồ đã được cập nhật: '{os.path.abspath(OUTPUT_HTML_FILE)}'")

def run_cycle():
    logging.info("="*50)
    logging.info("BẮT ĐẦU CHU KỲ THU THẬP VÀ PHÂN TÍCH KINH TẾ")
    logging.info("="*50)
    
    node_url = find_best_node()
    if not node_url:
        logging.error("Không thể tiếp tục chu kỳ vì không tìm thấy node nào đang hoạt động."); return

    try:
        logging.debug(f"Đang gửi yêu cầu tới {node_url}/chain/stats...")
        stats_resp = requests.get(f'{node_url}/chain/stats', timeout=10)
        logging.debug(f"Đang gửi yêu cầu tới {node_url}/chain...")
        chain_resp = requests.get(f'{node_url}/chain', timeout=20)
        
        if stats_resp.status_code != 200 or chain_resp.status_code != 200:
            logging.error("Không thể lấy dữ liệu đầy đủ từ node."); return
        
        logging.info("Đã nhận dữ liệu thành công từ node. Bắt đầu phân tích...")
        stats_data = stats_resp.json()
        chain_data = chain_resp.json().get('chain', [])
        # ... (Toàn bộ phần logic tính toán bên dưới giữ nguyên) ...
        current_metrics = {
            "timestamp": time.time(),
            "peer_count": max(1, stats_data.get('peer_count', 1)),
            "difficulty": stats_data.get('difficulty', 0),
            "total_supply": stats_data.get('total_supply', INITIAL_SUPPLY),
            "total_transactions": sum(len(json.loads(b['transactions'])) if isinstance(b['transactions'], str) else len(b['transactions']) for b in chain_data)
        }
        historical_data = load_data(DATA_FILE) or []
        treasury_data = load_data(TREASURY_FILE)
        if not historical_data:
            logging.info("Thiết lập chu kỳ kinh tế Sáng thế (Genesis)...")
            treasury_data = {'value_usd': INITIAL_TREASURY_USD}
            floor_price, market_price, speculative_multiplier = INITIAL_PRICE_USD, INITIAL_PRICE_USD, 0.0
            number_of_workstations = math.ceil(current_metrics['peer_count'] / NODES_PER_WORKSTATION)
            current_analysis = {**current_metrics, "floor_price": floor_price, "market_price": market_price, "speculative_multiplier": speculative_multiplier, "treasury_value": treasury_data['value_usd'], "number_of_workstations": number_of_workstations}
        else:
            last_analysis = historical_data[-1]
            number_of_workstations = math.ceil(current_metrics['peer_count'] / NODES_PER_WORKSTATION)
            total_monthly_revenue = number_of_workstations * WORKSTATION_MONTHLY_FEE_USD
            workstation_hourly_revenue = total_monthly_revenue / (30 * 24)
            new_transactions_this_cycle = current_metrics['total_transactions'] - last_analysis['total_transactions']
            transaction_value_growth = new_transactions_this_cycle * ASSUMED_VALUE_PER_TX_USD
            total_treasury_growth = workstation_hourly_revenue + transaction_value_growth
            treasury_data['value_usd'] += total_treasury_growth
            logging.info(f"Doanh thu từ {number_of_workstations} workstation: +${workstation_hourly_revenue:.4f} USD.")
            logging.info(f"Giá trị từ {new_transactions_this_cycle} giao dịch mới: +${transaction_value_growth:.4f} USD.")
            floor_price = treasury_data['value_usd'] / current_metrics['total_supply']
            tx_growth = (current_metrics['total_transactions'] - last_analysis['total_transactions']) / last_analysis['total_transactions'] if last_analysis['total_transactions'] > 0 else 0
            node_growth = (current_metrics['peer_count'] - last_analysis['peer_count']) / last_analysis['peer_count'] if last_analysis['peer_count'] > 0 else 0
            difficulty_growth = (current_metrics['difficulty'] - last_analysis['difficulty']) / last_analysis['difficulty'] if last_analysis['difficulty'] > 0 else 0
            smoothed_tx_growth, smoothed_node_growth, smoothed_difficulty_growth = math.log1p(max(0, tx_growth)), math.log1p(max(0, node_growth)), math.log1p(max(0, difficulty_growth))
            raw_growth_factor = (W_TX_GROWTH * smoothed_tx_growth) + (W_NODE_GROWTH * smoothed_node_growth) + (W_DIFFICULTY_GROWTH * smoothed_difficulty_growth)
            capped_growth_factor = min(raw_growth_factor, MAX_GROWTH_FACTOR_PER_CYCLE)
            last_multiplier = last_analysis.get('speculative_multiplier', 0.0)
            decayed_multiplier = last_multiplier * (1 - SPECULATIVE_MULTIPLIER_DECAY)
            speculative_multiplier = decayed_multiplier + capped_growth_factor
            market_price = floor_price * (1 + speculative_multiplier)
            current_analysis = {**current_metrics, "floor_price": floor_price, "market_price": market_price, "speculative_multiplier": speculative_multiplier, "treasury_value": treasury_data['value_usd'], "number_of_workstations": number_of_workstations}
        logging.info(f"Tổng kết: Quỹ=${current_analysis['treasury_value']:.2f} | Giá Sàn=${current_analysis['floor_price']:.8f} | Giá Thị trường=${current_analysis['market_price']:.8f} | Workstations={current_analysis['number_of_workstations']}")
        historical_data.append(current_analysis)
        save_data(historical_data, DATA_FILE)
        save_data(treasury_data, TREASURY_FILE)
        generate_chart(historical_data)

    except Exception as e:
        logging.error(f"Lỗi trong chu kỳ thu thập dữ liệu: {e}", exc_info=True)

if __name__ == "__main__":
    logging.info("--- Khởi động AI Agent Kinh tế (v3 - Gỡ lỗi) ---")
    while True:
        try:
            run_cycle()
            logging.info(f"Chu kỳ hoàn tất. Sẽ chạy lại sau {COLLECTION_INTERVAL_SECONDS} giây.")
            time.sleep(COLLECTION_INTERVAL_SECONDS)
        except KeyboardInterrupt:
            logging.info("\nĐã dừng Economist Agent.")
            break
        except Exception as e:
            logging.error(f"Lỗi nghiêm trọng trong vòng lặp chính: {e}")
            time.sleep(60)
