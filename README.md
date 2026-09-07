# trustid-scan-ai-service

Service AI phát hiện bất thường trong hành vi quét mã QR (Isolation Forest,
học không giám sát), phục vụ cho luồng "Quét mã -> chấm điểm rủi ro" của
app `trustid_scan_ai`.

## Cài đặt

```bash
python -m venv venv
source venv/bin/activate        # Windows: venv\Scripts\activate
pip install -r requirements.txt
```

## Chạy lần đầu (huấn luyện model)

```bash
# 1. Nếu CHƯA có dữ liệu thật từ công ty, sinh dữ liệu mẫu để chạy thử:
python generate_sample_data.py

# (Khi có dữ liệu thật, thay data/scan_logs.csv bằng file export thật,
#  giữ đúng 4 cột: code, lat, long, timestamp - không cần sửa code)

# 2. Huấn luyện model + hiệu chỉnh ngưỡng
python train.py
```

Sau bước này sẽ có 2 file mới: `model.pkl` và `thresholds.json`.

## Chạy service

```bash
uvicorn app:app --reload --port 8000
```

Kiểm tra: mở `http://127.0.0.1:8000/` -> phải thấy `{"status":"ok",...}`.

Xem API docs tự động (Swagger UI): `http://127.0.0.1:8000/docs`

## Kiểm thử bằng kịch bản giả lập

```bash
python test_scenarios.py
```

Chạy 5 kịch bản (bình thường / quét ở 2 tỉnh cách xa nhau trong thời gian
ngắn / tần suất quét quá cao...) và so sánh kết quả model với kỳ vọng.

## API

### `POST /risk-score`
Request:
```json
{ "code": "ABC123", "lat": 21.0278, "long": 105.8342, "timestamp": "2026-07-29T10:30:00" }
```
Response:
```json
{ "anomaly_score": 0.95, "level": "HIGH_RISK", "distance_km": 1137.5, "minutes_since_prev": 5.0, "scan_count": 2 }
```
`level` là 1 trong 3 giá trị: `NORMAL`, `WATCH`, `HIGH_RISK`.

### `DELETE /reset-state`
Xoá toàn bộ trạng thái "lượt quét gần nhất" đã lưu - dùng khi cần demo lại từ đầu.

## Retrain khi có dữ liệu mới

Chạy lại đúng 2 lệnh:
```bash
python train.py
# khởi động lại service để nạp model.pkl / thresholds.json mới
```
