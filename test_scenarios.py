"""
Script kiểm thử kịch bản (test case) cho service /risk-score
(trustid-scan-ai-service).

Vì không có nhãn thật (giả/không giả) để tính accuracy, ta tự tạo
các kịch bản có chủ đích để kiểm tra model có phát hiện đúng
hành vi bất thường hay không. Dùng để demo lúc bảo vệ.

Cách chạy:
    1. Đảm bảo service đang chạy: uvicorn app:app --port 8000
    2. Xoá file scan_state.db cũ nếu muốn test từ đầu (tránh nhiễu dữ liệu cũ)
    3. python test_scenarios.py
"""

import requests
from datetime import datetime, timedelta

BASE_URL = "http://127.0.0.1:8000"

# Toạ độ tham khảo để mô phỏng khoảng cách thực tế
HANOI = (21.0278, 105.8342)
HCMC = (10.7626, 106.6602)
DA_NANG = (16.0544, 108.2022)
HANOI_NEARBY = (21.0300, 105.8400)  # cách Hà Nội vài trăm mét


def call_risk_score(code: str, lat: float, long: float, timestamp: datetime):
    """Gọi API /risk-score với 1 lượt quét."""
    payload = {
        "code": code,
        "lat": lat,
        "long": long,
        "timestamp": timestamp.isoformat(),
    }
    res = requests.post(f"{BASE_URL}/risk-score", json=payload)
    res.raise_for_status()
    return res.json()


def print_result(scenario: str, expected: str, result: dict):
    status = "✅ ĐÚNG" if result["level"] == expected else "❌ SAI"
    print(f"[{scenario}]")
    print(f"  Kỳ vọng: {expected} | Thực tế: {result['level']} "
          f"(score={result['anomaly_score']}) -> {status}\n")


def scenario_1_normal():
    """Kịch bản 1: Quét bình thường - 1 mã, 1 lần duy nhất."""
    code = "TEST-NORMAL-001"
    now = datetime.now()
    result = call_risk_score(code, *HANOI, now)
    print_result("1. Quét lần đầu (bình thường)", "NORMAL", result)


def scenario_2_normal_second_scan_same_area():
    """Kịch bản 2: Quét lần 2 cùng khu vực, cách nhau vài giờ - vẫn bình thường."""
    code = "TEST-NORMAL-002"
    t1 = datetime.now()
    call_risk_score(code, *HANOI, t1)  # lượt quét đầu, thiết lập baseline

    t2 = t1 + timedelta(hours=3)
    result = call_risk_score(code, *HANOI_NEARBY, t2)
    print_result("2. Quét lần 2, cùng khu vực, cách 3 giờ", "NORMAL", result)


def scenario_3_teleport_fraud():
    """Kịch bản 3 (trọng tâm): cùng mã, quét ở Hà Nội rồi 5 phút sau
    quét ở TP.HCM -> không thể có thật, dấu hiệu mã bị sao chép."""
    code = "TEST-FRAUD-001"
    t1 = datetime.now()
    call_risk_score(code, *HANOI, t1)  # lượt quét gốc, hợp lệ

    t2 = t1 + timedelta(minutes=5)
    result = call_risk_score(code, *HCMC, t2)
    print_result("3. Quét Hà Nội -> TP.HCM chỉ trong 5 phút", "HIGH_RISK", result)


def scenario_4_moderate_distance_short_time():
    """Kịch bản 4: khoảng cách vừa phải trong thời gian ngắn - mức cảnh báo trung bình."""
    code = "TEST-WATCH-001"
    t1 = datetime.now()
    call_risk_score(code, *HANOI, t1)

    t2 = t1 + timedelta(minutes=20)
    result = call_risk_score(code, *DA_NANG, t2)  # ~600km trong 20 phút, vẫn phi lý nhưng để so sánh
    print_result("4. Hà Nội -> Đà Nẵng trong 20 phút", "HIGH_RISK", result)


def scenario_5_excessive_scan_count():
    """Kịch bản 5: 1 mã bị quét quá nhiều lần trong thời gian ngắn."""
    code = "TEST-HIGHFREQ-001"
    t0 = datetime.now()
    result = None
    for i in range(15):
        t = t0 + timedelta(minutes=i)
        result = call_risk_score(code, HANOI[0], HANOI[1] + i * 0.0001, t)
    print_result("5. Quét 15 lần liên tiếp trong 15 phút (cùng khu vực)", "HIGH_RISK", result)


if __name__ == "__main__":
    print("=== KIỂM THỬ KỊCH BẢN CHO /risk-score ===\n")
    scenario_1_normal()
    scenario_2_normal_second_scan_same_area()
    scenario_3_teleport_fraud()
    scenario_4_moderate_distance_short_time()
    scenario_5_excessive_scan_count()
    print("=== HOÀN TẤT ===")
    print("Lưu ý: nếu kết quả 'Thực tế' lệch nhiều so với 'Kỳ vọng',")
    print("cân nhắc điều chỉnh ngưỡng (threshold) trong app.py hoặc")
    print("tham số contamination khi train lại model (train.py).")
