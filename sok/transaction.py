# sok/transaction.py (Phiên bản cuối cùng)
import json, time, logging
from typing import Optional, TYPE_CHECKING
from . import wallet
from .utils import hash_data

if TYPE_CHECKING:
    from .blockchain import Blockchain 

class Transaction:
    def __init__(self, sender_public_key_pem: str, recipient_address: str, amount: float, 
                 timestamp: Optional[float] = None, signature: Optional[str] = None, sender_address: Optional[str] = None):
        self.sender_public_key_pem = sender_public_key_pem
        self.recipient_address = recipient_address
        self.amount = float(amount)
        self.timestamp = timestamp or time.time()
        self.signature = signature
        # Ưu tiên sender_address được truyền vào. Nếu không, tính toán lại.
        self.sender_address = sender_address or ("0" if sender_public_key_pem == "0" else wallet.get_address_from_public_key_pem(sender_public_key_pem))

    def get_signing_data(self) -> dict:
        return {'sender_public_key_pem': self.sender_public_key_pem, 'recipient_address': self.recipient_address, 'amount': self.amount, 'timestamp': self.timestamp}
        
    def to_dict(self) -> dict:
        data = self.get_signing_data()
        data['sender_address'] = self.sender_address
        data['signature'] = self.signature
        return data

    def calculate_hash(self) -> str:
        transaction_string = json.dumps(self.get_signing_data(), sort_keys=True).encode('utf-8')
        return hash_data(transaction_string)

    def sign(self, private_key_obj):
        if not self.signature: self.signature = wallet.sign_data(private_key_obj, self.calculate_hash())

    def is_valid(self, blockchain_instance: 'Blockchain') -> tuple[bool, str]:
        if self.sender_public_key_pem == "0":
            return (True, "Giao dịch hệ thống hợp lệ") if self.signature in ["genesis_transaction", "mining_reward"] else (False, "Giao dịch hệ thống không hợp lệ")
        
        if not all([self.sender_public_key_pem, self.recipient_address, self.signature, self.amount is not None]):
            return False, "Thiếu trường dữ liệu quan trọng"
        
        # Kiểm tra xem sender_address có khớp với public key không
        calculated_address = wallet.get_address_from_public_key_pem(self.sender_public_key_pem)
        if self.sender_address != calculated_address:
            return False, "Địa chỉ người gửi không khớp với khóa công khai."

        is_signature_valid = wallet.verify_signature(self.sender_public_key_pem, self.calculate_hash(), self.signature)
        if not is_signature_valid:
            return False, f"Chữ ký không hợp lệ cho địa chỉ {self.sender_address[:10]}..."
        
        sender_balance = blockchain_instance.get_balance(self.sender_address)
        if sender_balance < self.amount:
            return False, f"Số dư không đủ. {self.sender_address[:10]}... chỉ có {sender_balance} SOK."
        
        if self.amount <= 0: return False, "Số tiền giao dịch phải lớn hơn 0."
            
        return True, "Giao dịch hợp lệ"

    @staticmethod
    def from_dict(data: dict):
        required_keys = ['sender_public_key_pem', 'recipient_address', 'amount']
        if not all(k in data for k in required_keys):
            raise ValueError("Thiếu các trường dữ liệu bắt buộc để tạo Giao dịch.")
        return Transaction(
            data['sender_public_key_pem'], data['recipient_address'], data['amount'],
            data.get('timestamp'), data.get('signature'), data.get('sender_address')
        )
