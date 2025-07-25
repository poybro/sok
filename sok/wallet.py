# sok/wallet.py
# -*- coding: utf-8 -*-

from cryptography.hazmat.primitives.asymmetric import rsa, padding
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.backends import default_backend
from typing import Optional, Any
from .utils import hash_data 

def public_key_to_pem(public_key_obj: Any) -> str:
    """Chuyển đổi đối tượng khóa công khai sang định dạng PEM."""
    return public_key_obj.public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo
    ).decode('utf-8')

def load_public_key_from_pem(pem_string: str):
    """Tải đối tượng khóa công khai từ chuỗi PEM."""
    return serialization.load_pem_public_key(
        pem_string.encode('utf-8'),
        backend=default_backend()
    )

class Wallet:
    def __init__(self, private_key_pem: Optional[str] = None):
        if private_key_pem:
            self.private_key = serialization.load_pem_private_key(
                private_key_pem.encode('utf-8'),
                password=None,
                backend=default_backend()
            )
        else:
            self.private_key = rsa.generate_private_key(
                public_exponent=65537,
                key_size=2048,
                backend=default_backend()
            )
        self.public_key = self.private_key.public_key()
        self.address = self.get_address()

    def get_address(self) -> str:
        """Lấy địa chỉ ví từ khóa công khai của ví này."""
        public_key_pem = self.get_public_key_pem()
        return get_address_from_public_key_pem(public_key_pem)

    def get_private_key_pem(self) -> str:
        """Lấy khóa riêng tư dưới dạng chuỗi PEM."""
        return self.private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption()
        ).decode('utf-8')

    def get_public_key_pem(self) -> str:
        """Lấy khóa công khai dưới dạng chuỗi PEM."""
        return public_key_to_pem(self.public_key)

def sign_data(private_key_obj: Any, data_hash: str) -> str:
    """Ký vào một chuỗi hash và trả về chữ ký dưới dạng hex."""
    signature_bytes = private_key_obj.sign(
        bytes.fromhex(data_hash),
        padding.PSS(
            mgf=padding.MGF1(hashes.SHA256()),
            salt_length=padding.PSS.MAX_LENGTH
        ),
        hashes.SHA256()
    )
    return signature_bytes.hex()

def verify_signature(public_key_pem_string: str, data_hash: str, signature_hex: str) -> bool:
    """Xác thực một chữ ký."""
    try:
        public_key_loaded = load_public_key_from_pem(public_key_pem_string)
        public_key_loaded.verify(
            bytes.fromhex(signature_hex),
            bytes.fromhex(data_hash),
            padding.PSS(
                mgf=padding.MGF1(hashes.SHA256()),
                salt_length=padding.PSS.MAX_LENGTH
            ),
            hashes.SHA256()
        )
        return True
    except Exception:
        return False

def get_address_from_public_key_pem(public_key_pem: str) -> str:
    """
    Tạo địa chỉ ví từ public key dạng PEM.
    Đây là một hàm tiện ích để đảm bảo việc tính toán địa chỉ là nhất quán trên toàn hệ thống.
    """
    public_key_bytes = public_key_pem.encode('utf-8')
    raw_hash = hash_data(public_key_bytes)
    return f"SO{raw_hash}K"
