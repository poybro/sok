# mouse_schedule_automation.py
# -*- coding: utf-8 -*-

"""
Kịch bản tự động hóa các hành động của chuột theo một lịch trình định sẵn.
Chương trình sẽ chạy, thực hiện các hành động, và tự động kết thúc.
"""

import pyautogui
import time
from typing import List, Tuple

# --- LỊCH TRÌNH HÀNH ĐỘNG ---
# Cấu trúc: (Thời gian chờ ban đầu (giây), Tọa độ X, Tọa độ Y, Số lần nhấp chuột)
# LƯU Ý: Tọa độ (0, 0) là ở góc trên cùng bên trái màn hình.
ACTION_SCHEDULE: List[Tuple[int, int, int, int]] = [
    # Dựa trên lịch trình của bạn, diễn giải lại cho hành động chuột:
    (25, 125,   5, 10),
    (605, 750,  1,  2),
    (25, 180,   1, 10),
    (605, 750,  1,  2),
    (25, 230,   1, 10),
    (605, 750,  1,  2),
    (25, 280,   1, 10),
    (605, 750,  1,  2),
    (25, 335,   1, 10),
    (605, 750,  1,  2),
    (25, 390,   1, 10),
    (605, 750,  1,  2),
    (25, 445,   1, 10),
    (605, 750,  1,  2),
]

# --- CÁC HÀM THỰC THI ---

def countdown(seconds: int):
    """Hiển thị một đồng hồ đếm ngược trong terminal."""
    for i in range(seconds, 0, -1):
        # In trên cùng một dòng, \r di chuyển con trỏ về đầu dòng
        print(f"  Bắt đầu hành động tiếp theo sau: {i:02d} giây...", end='\r')
        time.sleep(1)
    print("\nBắt đầu hành động!                       ") # In thêm khoảng trắng để xóa dòng cũ

def execute_mouse_action(x: int, y: int, clicks: int):
    """
    Di chuyển chuột đến một tọa độ và thực hiện nhấp chuột.
    """
    try:
        print(f"  -> Di chuyển chuột đến tọa độ ({x}, {y}).")
        # Thêm duration để chuột di chuyển mượt mà hơn, trông tự nhiên hơn
        pyautogui.moveTo(x, y, duration=0.5)

        print(f"  -> Nhấp chuột {clicks} lần.")
        # Thêm interval để có khoảng nghỉ nhỏ giữa các lần nhấp
        pyautogui.click(clicks=clicks, interval=0.1)

    except Exception as e:
        print(f"\n[LỖI] Đã xảy ra lỗi khi điều khiển chuột: {e}")

def run_automation_schedule():
    """Hàm chính thực thi toàn bộ lịch trình."""
    print("=" * 50)
    print("🚀 BẮT ĐẦU KỊCH BẢN TỰ ĐỘNG HÓA CHUỘT 🚀")
    print("=" * 50)
    print("\nCẢNH BÁO: Vui lòng không sử dụng chuột hoặc bàn phím")
    print("trong khi kịch bản đang chạy để tránh làm gián đoạn.")
    print("\n!!! BẠN CÓ THỂ DỪNG KHẨN CẤP BẰNG CÁCH DI CHUỘT VÀO GÓC TRÊN CÙNG BÊN TRÁI MÀN HÌNH !!!")

    # Chờ 5 giây để người dùng có thời gian chuẩn bị
    time.sleep(5)

    for i, task in enumerate(ACTION_SCHEDULE):
        initial_delay, target_x, target_y, num_clicks = task
        
        print(f"\n--- Đang thực hiện Tác vụ {i+1}/{len(ACTION_SCHEDULE)} ---")
        
        # 1. Chờ ban đầu
        countdown(initial_delay)

        # 2. Thực hiện hành động
        execute_mouse_action(target_x, target_y, num_clicks)

    print("\n" + "=" * 50)
    print("✅ LỊCH TRÌNH TỰ ĐỘNG HÓA ĐÃ HOÀN TẤT! ✅")
    print("=" * 50)

# --- BẮT ĐẦU KỊCH BẢN ---
if __name__ == "__main__":
    try:
        run_automation_schedule()
    except pyautogui.FailSafeException:
        print("\n[DỪNG KHẨN CẤP] Kịch bản đã được dừng bởi người dùng (Fail-Safe Triggered).")
    except KeyboardInterrupt:
        print("\n[DỪNG] Kịch bản đã được dừng bởi người dùng (Ctrl+C).")
    except Exception as e:
        print(f"\n[LỖI NGHIÊM TRỌNG] Đã xảy ra lỗi không mong muốn: {e}")
    
    print("\nChương trình sẽ tự động đóng sau 5 giây...")
    time.sleep(5)
