"""
Sinh dữ liệu scan-log MẪU để bạn có thể chạy thử train.py ngay,
trong lúc chờ công ty export dữ liệu thật.

Khi có dữ liệu thật, chỉ cần thay data/scan_logs.csv bằng file thật
(cùng đúng 4 cột: code, lat, long, timestamp), KHÔNG cần sửa gì ở train.py.

Chạy: python generate_sample_data.py
"""

import pandas as pd
import numpy as np
import random
from datetime import datetime, timedelta

random.seed(42)
np.random.seed(42)

# Vài "vùng" toạ độ giả lập (mô phỏng các tỉnh/khu vực đại lý)
REGIONS = {
    "HaNoi": (21.0278, 105.8342),
    "HCMC": (10.7626, 106.6602),
    "DaNang": (16.0544, 108.2022),
    "CanTho": (10.0452, 105.7469),
    "HaiPhong": (20.8449, 106.6881),
}

rows = []
start_date = datetime(2025, 1, 1)

# 1) Sinh 1500 mã "bình thường": mỗi mã quét 1-4 lần, CÙNG 1 khu vực,
#    khoảng cách/thời gian giữa các lần đa dạng hơn -> giúp model học
#    "vùng bình thường" rộng và mượt hơn, tránh model quá nhạy cảm
for i in range(1500):
    code = f"NORMAL-{i:04d}"
    region_name = random.choice(list(REGIONS.keys()))
    base_lat, base_long = REGIONS[region_name]
    n_scans = random.randint(1, 4)
    t = start_date + timedelta(days=random.randint(0, 180), hours=random.randint(0, 23))

    for s in range(n_scans):
        jitter_lat = base_lat + random.uniform(-0.08, 0.08)   # lệch vài-chục km trong cùng khu vực
        jitter_long = base_long + random.uniform(-0.08, 0.08)
        rows.append({"code": code, "lat": jitter_lat, "long": jitter_long,
                      "timestamp": t.isoformat()})
        t += timedelta(minutes=random.randint(30, 4320))  # 30 phút -> 3 ngày, đa dạng hơn nhiều

# 2) Sinh 20 mã "bất thường" có chủ đích: quét ở 2 khu vực CÁCH XA nhau
#    chỉ trong vài phút -> mô phỏng mã bị sao chép/làm giả
region_names = list(REGIONS.keys())
for i in range(20):
    code = f"FRAUD-{i:04d}"
    r1, r2 = random.sample(region_names, 2)
    t1 = start_date + timedelta(days=random.randint(0, 180), hours=random.randint(0, 23))
    t2 = t1 + timedelta(minutes=random.randint(2, 20))  # cách nhau rất ngắn

    rows.append({"code": code, "lat": REGIONS[r1][0], "long": REGIONS[r1][1],
                  "timestamp": t1.isoformat()})
    rows.append({"code": code, "lat": REGIONS[r2][0], "long": REGIONS[r2][1],
                  "timestamp": t2.isoformat()})

# 3) Sinh 20 mã bị quét với tần suất RẤT cao trong thời gian ngắn (cùng 1 khu vực)
#    -> mô phỏng nghi vấn 1 mã bị đóng gói/dán lại nhiều lần, dùng nhiều thiết bị quét liên tục
for i in range(20):
    code = f"HIGHFREQ-{i:04d}"
    region_name = random.choice(list(REGIONS.keys()))
    base_lat, base_long = REGIONS[region_name]
    t = start_date + timedelta(days=random.randint(0, 180), hours=random.randint(0, 23))
    n_scans = random.randint(12, 20)
    for s in range(n_scans):
        jitter_lat = base_lat + random.uniform(-0.01, 0.01)
        jitter_long = base_long + random.uniform(-0.01, 0.01)
        rows.append({"code": code, "lat": jitter_lat, "long": jitter_long,
                      "timestamp": t.isoformat()})
        t += timedelta(minutes=random.randint(1, 3))  # quét liên tục, cách nhau 1-3 phút

df = pd.DataFrame(rows)
df.to_csv("data/scan_logs.csv", index=False)
print(f"Đã sinh {len(df)} dòng dữ liệu mẫu -> data/scan_logs.csv")
print(f"  - 1500 mã bình thường (1-4 lượt quét/mã, cùng khu vực, thời gian đa dạng)")
print(f"  - 20 mã bất thường: quét 2 khu vực xa nhau trong thời gian ngắn (giả mã)")
print(f"  - 20 mã bất thường: tần suất quét rất cao trong thời gian ngắn")
