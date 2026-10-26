"""
Huấn luyện mô hình phát hiện bất thường (Isolation Forest) từ dữ liệu
scan-log lịch sử.

Input:  data/scan_logs.csv  (cột: code, lat, long, timestamp)
Output: model.pkl

Chạy: python train.py
"""

import sys
import json

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

import numpy as np
import pandas as pd
from sklearn.ensemble import IsolationForest
from geopy.distance import geodesic
import joblib

print("Đang đọc dữ liệu...")
df = pd.read_csv("data/scan_logs.csv", parse_dates=["timestamp"])

# --- INJECT SYNTHETIC ANOMALIES (LÀM GIÀU DỮ LIỆU ĐỂ AI KHÔN HƠN) ---
synthetic_data = []
# 1. Teleport: Khoảng cách rất xa trong thời gian cực ngắn (HN -> HCM trong 5 phút)
for i in range(20):
    synthetic_data.extend([
        {"code": f"SYN-TELE-{i}", "lat": 21.0285, "long": 105.8542, "timestamp": pd.to_datetime(f"2025-10-01 10:00:00")},
        {"code": f"SYN-TELE-{i}", "lat": 10.8231, "long": 106.6297, "timestamp": pd.to_datetime(f"2025-10-01 10:05:00")}
    ])
# 2. Spammer: Quét liên tục cùng 1 chỗ nhưng quét cả trăm lần (lộ mã công khai)
for i in range(5):
    for j in range(60):
        synthetic_data.append({
            "code": f"SYN-SPAM-{i}", "lat": 16.0471, "long": 108.2068, 
            "timestamp": pd.to_datetime(f"2025-10-02 08:00:00") + pd.Timedelta(minutes=j*2)
        })

df_synthetic = pd.DataFrame(synthetic_data)
df = pd.concat([df, df_synthetic], ignore_index=True)
# -------------------------------------------------------------------

df = df.sort_values(["code", "timestamp"]).reset_index(drop=True)
print(f"Tổng số dòng sau khi thêm synthetic: {len(df)}, số mã duy nhất: {df['code'].nunique()}")

# ---- Feature engineering ----
df["prev_lat"] = df.groupby("code")["lat"].shift(1)
df["prev_long"] = df.groupby("code")["long"].shift(1)
df["prev_time"] = df.groupby("code")["timestamp"].shift(1)


def calc_distance(row):
    if pd.isna(row["prev_lat"]):
        return 0.0
    return geodesic((row["lat"], row["long"]), (row["prev_lat"], row["prev_long"])).km


df["distance_km"] = df.apply(calc_distance, axis=1)

df["minutes_since_prev"] = (
    (df["timestamp"] - df["prev_time"]).dt.total_seconds() / 60
)
df["minutes_since_prev"] = df["minutes_since_prev"].fillna(999999)

df["implied_speed"] = (df["distance_km"] * 60.0) / df["minutes_since_prev"].replace(0, 0.1)
df["scan_count"] = df.groupby("code")["code"].transform("count")

feature_cols = ["distance_km", "minutes_since_prev", "implied_speed", "scan_count"]
features = df[feature_cols].fillna(0)

print("\nThống kê đặc trưng:")
print(features.describe())

# ---- Huấn luyện ----
# contamination=0.05: giả định khoảng 5% dữ liệu là bất thường
# (tham số này nên tinh chỉnh dựa trên tỉ lệ thực tế nếu công ty có ước lượng)
model = IsolationForest(
    n_estimators=200,
    contamination=0.05,
    random_state=42,
)
model.fit(features)

joblib.dump(model, "model.pkl")
print("\nĐã lưu model vào model.pkl")

# ---- Đánh giá nhanh trên chính tập train (sơ bộ, không thay thế test case kịch bản) ----
predictions = model.predict(features)  # 1 = bình thường, -1 = bất thường
n_anomaly = (predictions == -1).sum()
print(f"Số điểm được gắn là bất thường trên tập train: {n_anomaly}/{len(df)} "
      f"({n_anomaly/len(df)*100:.1f}%)")

# ---- Hiệu chỉnh ngưỡng (threshold) dựa trên phân bố điểm thật của model ----
# Không đặt cứng 0.4/0.7, mà tính theo percentile của chính tập train:
# - watch_threshold: mốc 80th percentile (20% điểm cao nhất -> "cần theo dõi")
# - high_threshold : mốc 95th percentile (5% điểm cao nhất -> khớp contamination=0.05)
raw_scores = model.decision_function(features)
score_min, score_max = float(raw_scores.min()), float(raw_scores.max())


def to_anomaly_score(raw):
    if score_max == score_min:
        return 0.0
    return float(np.clip((score_max - raw) / (score_max - score_min), 0, 1))


normalized = np.array([to_anomaly_score(r) for r in raw_scores])
watch_threshold = float(np.percentile(normalized, 80))
high_threshold = float(np.percentile(normalized, 95))

thresholds = {
    "score_min": score_min,
    "score_max": score_max,
    "watch_threshold": watch_threshold,
    "high_threshold": high_threshold,
}
with open("thresholds.json", "w") as f:
    json.dump(thresholds, f, indent=2)

print(f"\nĐã hiệu chỉnh ngưỡng theo phân bố dữ liệu train -> thresholds.json")
print(f"  watch_threshold = {watch_threshold:.3f}")
print(f"  high_threshold  = {high_threshold:.3f}")
