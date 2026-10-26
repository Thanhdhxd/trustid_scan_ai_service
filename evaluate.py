import sys
import pandas as pd
import numpy as np
import matplotlib.pyplot as plt
import seaborn as sns
import joblib
import json
from geopy.distance import geodesic
import os

if sys.stdout.encoding and sys.stdout.encoding.lower() != 'utf-8':
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Create an output directory for the plots
os.makedirs("evaluation_results", exist_ok=True)

print("1. Đang tải dữ liệu và mô hình...")
df = pd.read_csv("data/scan_logs.csv", parse_dates=["timestamp"])
df = df.sort_values(["code", "timestamp"]).reset_index(drop=True)

# ---- Feature engineering (Giống hệt train.py) ----
df["prev_lat"] = df.groupby("code")["lat"].shift(1)
df["prev_long"] = df.groupby("code")["long"].shift(1)
df["prev_time"] = df.groupby("code")["timestamp"].shift(1)

def calc_distance(row):
    if pd.isna(row["prev_lat"]):
        return 0.0
    return geodesic((row["lat"], row["long"]), (row["prev_lat"], row["prev_long"])).km

df["distance_km"] = df.apply(calc_distance, axis=1)
df["minutes_since_prev"] = ((df["timestamp"] - df["prev_time"]).dt.total_seconds() / 60)
df["minutes_since_prev"] = df["minutes_since_prev"].fillna(999999)
df["implied_speed"] = (df["distance_km"] * 60.0) / df["minutes_since_prev"].replace(0, 0.1)
df["scan_count"] = df.groupby("code")["code"].transform("count")

feature_cols = ["distance_km", "minutes_since_prev", "implied_speed", "scan_count"]
features = df[feature_cols].fillna(0)

# Tải model và thresholds
model = joblib.load("model.pkl")
with open("thresholds.json") as f:
    thresholds = json.load(f)

score_min = thresholds["score_min"]
score_max = thresholds["score_max"]
watch_threshold = thresholds["watch_threshold"]
high_threshold = thresholds["high_threshold"]

print("2. Đang dự đoán và chấm điểm...")
raw_scores = model.decision_function(features)

def to_anomaly_score(raw):
    if score_max == score_min: return 0.0
    return float(np.clip((score_max - raw) / (score_max - score_min), 0, 1))

df['anomaly_score'] = [to_anomaly_score(r) for r in raw_scores]

def get_label(score):
    if score >= high_threshold: return "HIGH_RISK (Đỏ)"
    if score >= watch_threshold: return "WATCH (Vàng)"
    return "NORMAL (Xanh)"

df['risk_label'] = df['anomaly_score'].apply(get_label)

print("3. Đang vẽ biểu đồ...")
plt.style.use('seaborn-v0_8-whitegrid')

# ---- Biểu đồ 1: Phân bố điểm số (Histogram) ----
plt.figure(figsize=(10, 6))
sns.histplot(data=df, x='anomaly_score', bins=50, color='skyblue')
plt.axvline(watch_threshold, color='orange', linestyle='--', linewidth=2, label=f'Watch Threshold ({watch_threshold:.2f})')
plt.axvline(high_threshold, color='red', linestyle='--', linewidth=2, label=f'High Risk Threshold ({high_threshold:.2f})')
plt.title('Phân bố điểm bất thường (Anomaly Score)', fontsize=14)
plt.xlabel('Điểm rủi ro (0.0 -> 1.0)')
plt.ylabel('Số lượng lượt quét')
plt.legend()
plt.tight_layout()
out1 = "evaluation_results/chart1_histogram.png"
plt.savefig(out1, dpi=300)
plt.close()
print(f"Đã lưu biểu đồ 1 tại: {out1}")

# ---- Biểu đồ 2: Scatter plot (Tốc độ vs Số lượt quét) ----
# Lọc bỏ các điểm log lần đầu (vì tốc độ = 0, scan_count = tổng số) để nhìn rõ hơn
# Dùng log scale cho trục Y (tốc độ) vì tốc độ lừa đảo thường cực kỳ cao
plt.figure(figsize=(10, 6))
scatter_df = df[df['minutes_since_prev'] != 999999]
colors = {"NORMAL (Xanh)": "green", "WATCH (Vàng)": "orange", "HIGH_RISK (Đỏ)": "red"}

sns.scatterplot(
    data=scatter_df, 
    x='scan_count', 
    y='implied_speed', 
    hue='risk_label', 
    palette=colors,
    alpha=0.7
)
plt.title('Tốc độ di chuyển vs Tổng số lượt quét', fontsize=14)
plt.xlabel('Tổng số lượt quét của mã (Scan Count)')
plt.ylabel('Tốc độ di chuyển (km/phút)')
plt.yscale('symlog') # Dùng log scale cho dễ nhìn
plt.tight_layout()
out2 = "evaluation_results/chart2_scatter.png"
plt.savefig(out2, dpi=300)
plt.close()
print(f"Đã lưu biểu đồ 2 tại: {out2}")

# Thống kê nhanh
print("\n--- THỐNG KÊ KẾT QUẢ ---")
print(df['risk_label'].value_counts())
print("\nHoàn tất! Bạn có thể lấy 2 file ảnh trong thư mục evaluation_results.")
