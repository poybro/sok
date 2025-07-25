# Đảm bảo import đúng
from sok.p2p import HybridP2PManager 

# ...

def main():
    # ...
    
    # Khởi tạo P2P Manager
    p2p_manager = HybridP2PManager(
        blockchain=blockchain_instance, 
        node_wallet=node_wallet, 
        node_port=args.port,
        project_root=project_root # Truyền đường dẫn gốc vào
    )
    
    # Tạo app và truyền p2p_manager vào
    app = create_app(
        blockchain=blockchain_instance,
        p2p_manager=p2p_manager,
        node_wallet=node_wallet
    )

    # Khởi động P2P Manager
    if 'p2p' in roles:
        p2p_manager.start()

    # ... (phần còn lại của hàm main)
