"""
Service AI chấm điểm rủi ro cho mỗi lượt quét mã QR.
Tự quản lý "lượt quét gần nhất" của mỗi mã trong SQLite - không phụ thuộc
API lịch sử của hệ thống công ty.

Chạy: uvicorn app:app --reload --port 8000
"""

import json
import os
import uuid
import shutil
import sqlite3
import urllib.request
import urllib.error
from datetime import datetime

import joblib
import numpy as np
from fastapi import FastAPI, HTTPException, Request, Response, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
import pandas as pd
from geopy.distance import geodesic
from pydantic import BaseModel
from typing import List

app = FastAPI(title="TrustID Scan Anomaly Detection Service")

# Đảm bảo thư mục uploads tồn tại và mount static files
os.makedirs("uploads", exist_ok=True)
app.mount("/uploads", StaticFiles(directory="uploads"), name="uploads")

# Thêm cấu hình CORS để Flutter Web có thể gọi API mà không bị chặn
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

try:
    model = joblib.load("model.pkl")
except FileNotFoundError:
    raise RuntimeError(
        "Không tìm thấy model.pkl. Hãy chạy 'python train.py' trước khi khởi động service."
    )

try:
    with open("thresholds.json") as f:
        _t = json.load(f)
    SCORE_MIN = _t["score_min"]
    SCORE_MAX = _t["score_max"]
    WATCH_THRESHOLD = _t["watch_threshold"]
    HIGH_THRESHOLD = _t["high_threshold"]
except FileNotFoundError:
    raise RuntimeError(
        "Không tìm thấy thresholds.json. Hãy chạy 'python train.py' (bản mới) trước khi khởi động service."
    )

conn = sqlite3.connect("scan_state.db", check_same_thread=False)
conn.execute(
    """CREATE TABLE IF NOT EXISTS last_scan (
        code TEXT PRIMARY KEY,
        lat REAL,
        long REAL,
        timestamp TEXT,
        scan_count INTEGER,
        is_compromised INTEGER DEFAULT 0
    )"""
)
conn.commit()


class ScanEvent(BaseModel):
    code: str
    lat: float
    long: float
    timestamp: str  # ISO 8601, ví dụ "2026-07-29T10:30:00"


class RiskResult(BaseModel):
    anomaly_score: float
    level: str
    distance_km: float
    minutes_since_prev: float
    scan_count: int
    reasons: List[str] = []


@app.get("/")
def health_check():
    return {"status": "ok", "message": "TrustID Scan Anomaly Detection Service is running"}


@app.post("/risk-score", response_model=RiskResult)
def risk_score(event: ScanEvent):
    try:
        event_time = datetime.fromisoformat(event.timestamp)
    except ValueError:
        raise HTTPException(status_code=400, detail="timestamp phải theo định dạng ISO 8601")

    row = conn.execute(
        "SELECT lat, long, timestamp, scan_count, is_compromised FROM last_scan WHERE code = ?",
        (event.code,),
    ).fetchone()

    if row is None:
        # Lượt quét đầu tiên của mã này -> không có gì để so sánh,
        # không thể có "bất thường" theo định nghĩa của bài toán này.
        # Trở về NORMAL trực tiếp, không cần đưa qua model.
        distance_km = 0.0
        minutes_since_prev = 0.0
        scan_count = 1
        is_compromised = 0
        conn.execute(
            "INSERT OR REPLACE INTO last_scan VALUES (?, ?, ?, ?, ?, ?)",
            (event.code, event.lat, event.long, event.timestamp, scan_count, is_compromised),
        )
        conn.commit()
        return RiskResult(
            anomaly_score=0.0,
            level="NORMAL",
            distance_km=distance_km,
            minutes_since_prev=minutes_since_prev,
            scan_count=scan_count,
            reasons=[],
        )

    prev_lat, prev_long, prev_time_str, prev_scan_count, is_compromised = row
    distance_km = geodesic((event.lat, event.long), (prev_lat, prev_long)).km
    prev_time = datetime.fromisoformat(prev_time_str)
    minutes_since_prev = max((event_time - prev_time).total_seconds() / 60, 0)
    scan_count = prev_scan_count + 1

    implied_speed = (distance_km * 60.0) / (minutes_since_prev if minutes_since_prev > 0 else 0.1)

    features = pd.DataFrame(
        [[distance_km, minutes_since_prev, implied_speed, scan_count]],
        columns=["distance_km", "minutes_since_prev", "implied_speed", "scan_count"]
    )
    raw_score = model.decision_function(features)[0]  # Càng âm càng bất thường

    # Quy về thang 0..1 dựa trên min/max đã quan sát lúc train
    if SCORE_MAX == SCORE_MIN:
        anomaly_score = 0.0
    else:
        anomaly_score = float(np.clip((SCORE_MAX - raw_score) / (SCORE_MAX - SCORE_MIN), 0, 1))

    reasons = []
    
    # HARD RULES (Luật cứng thực tế)
    if implied_speed > 900:
        reasons.append(f"Tốc độ di chuyển bất khả thi ({round(implied_speed, 1)} km/h)")
    if distance_km > 1000 and minutes_since_prev < 60:
        reasons.append(f"Khoảng cách quá xa trong thời gian ngắn ({round(distance_km, 1)} km / {round(minutes_since_prev, 1)} phút)")
    if scan_count > 50:
        reasons.append(f"Sản phẩm bị quét quá nhiều lần ({scan_count} lần)")

    # Hybrid system logic
    if is_compromised == 1:
        reasons.append("Cảnh báo: Lịch sử quét mã này từng phát hiện rủi ro làm giả")
        level = "HIGH_RISK"
        anomaly_score = max(anomaly_score, 0.99)
    elif len(reasons) > 0:
        level = "HIGH_RISK"
        anomaly_score = max(anomaly_score, 0.95)  # Đẩy điểm lên mức cao
    elif anomaly_score >= HIGH_THRESHOLD:
        level = "HIGH_RISK"
        reasons.append("Mô hình AI phát hiện hành vi bất thường nghiêm trọng")
    elif anomaly_score >= WATCH_THRESHOLD:
        level = "WATCH"
        reasons.append("Khoảng cách hoặc tần suất quét có dấu hiệu đáng ngờ")
    else:
        level = "NORMAL"

    if level == "HIGH_RISK":
        is_compromised = 1

    print(f"[{event.code}] Lần quét: {scan_count} | Khoảng cách: {distance_km:.2f} km | Cách lần trước: {minutes_since_prev:.1f} phút | Vận tốc: {implied_speed:.1f} km/h | Lỗi: {is_compromised}")

    conn.execute(
        "INSERT OR REPLACE INTO last_scan VALUES (?, ?, ?, ?, ?, ?)",
        (event.code, event.lat, event.long, event.timestamp, scan_count, is_compromised),
    )
    conn.commit()

    return RiskResult(
        anomaly_score=round(anomaly_score, 3),
        level=level,
        distance_km=round(distance_km, 2),
        minutes_since_prev=round(minutes_since_prev, 1),
        scan_count=scan_count,
        reasons=reasons,
    )


@app.delete("/reset-state")
def reset_state():
    """Xóa toàn bộ trạng thái lượt quét gần nhất - dùng khi cần demo lại từ đầu."""
    conn.execute("DELETE FROM last_scan")
    conn.commit()
    return {"status": "reset_done"}


import urllib.request
import urllib.parse
from fastapi import Response, Request

@app.get("/api/traceability/public/{code}")
@app.get("/api/v2/traceability/public/{code}")
def proxy_traceability(code: str):
    """Proxy API truy xuất nguồn gốc qua lỗi CORS trên Flutter Web."""
    url = f"https://api.trustid.com.vn/api/v2/traceability/public/{code}"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except urllib.error.HTTPError as e:
        data = e.read()
        return Response(content=data, status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/login")
async def proxy_login(request: Request):
    """Proxy cho API đăng nhập."""
    url = "https://api.trustid.com.vn/auth/login"
    try:
        body = await request.body()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except urllib.error.HTTPError as e:
        data = e.read()
        return Response(content=data, status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/auth/register")
async def proxy_register(request: Request):
    """Proxy cho API đăng ký."""
    url = "https://api.trustid.com.vn/auth/register"
    try:
        body = await request.body()
        req = urllib.request.Request(url, data=body, headers={'Content-Type': 'application/json', 'User-Agent': 'Mozilla/5.0'}, method='POST')
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except urllib.error.HTTPError as e:
        data = e.read()
        return Response(content=data, status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/trace/scan-log")
async def proxy_scan_log(request: Request):
    """Proxy API log lượt quét để tránh 404."""
    url = "https://api.trustid.com.vn/trace/scan-log"
    try:
        body = await request.body()
        req = urllib.request.Request(url, data=body, headers={'User-Agent': 'Mozilla/5.0', 'Content-Type': 'application/json'}, method='POST')
        with urllib.request.urlopen(req) as response:
            return Response(content=response.read(), media_type="application/json")
    except Exception as e:
        return {"status": "ok", "note": "proxied with error/ignored"}

@app.get("/consumer/products/featured")
def proxy_products():
    """Proxy cho API Sản phẩm nổi bật."""
    url = "https://api.trustid.com.vn/consumer/products/featured"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/auth/profile")
async def proxy_profile(request: Request):
    """Proxy cho API Lấy thông tin tài khoản."""
    url = "https://api.trustid.com.vn/auth/profile"
    try:
        # Lấy header Authorization từ request
        auth_header = request.headers.get('Authorization')
        headers = {'User-Agent': 'Mozilla/5.0'}
        if auth_header:
            headers['Authorization'] = auth_header
            
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except urllib.error.HTTPError as e:
        data = e.read()
        return Response(content=data, status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/proxy-image")
async def proxy_image(url: str):
    """Proxy cho hình ảnh để vượt lỗi CORS trên Flutter Web."""
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            data = response.read()
            content_type = response.headers.get('Content-Type', 'image/jpeg')
            return Response(content=data, media_type=content_type)
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/home-stats")
def proxy_home_stats():
    url = "https://api.trustid.com.vn/api/home-stats"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return Response(content=response.read(), media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/consumer/partners/top")
def proxy_top_partners():
    url = "https://api.trustid.com.vn/consumer/partners/top"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return Response(content=response.read(), media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/consumer/products/grouped-by-category")
def proxy_grouped_products():
    url = "https://api.trustid.com.vn/consumer/products/grouped-by-category"
    try:
        req = urllib.request.Request(url, headers={'User-Agent': 'Mozilla/5.0'})
        with urllib.request.urlopen(req) as response:
            return Response(content=response.read(), media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tenant/dashboard/summary")
async def proxy_dashboard_summary(request: Request):
    """Proxy cho API Thống kê Dashboard."""
    url = "https://api.trustid.com.vn/tenant/dashboard/summary"
    try:
        auth_header = request.headers.get("Authorization")
        headers = {"User-Agent": "Mozilla/5.0"}
        if auth_header:
            headers["Authorization"] = auth_header
            
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except urllib.error.HTTPError as e:
        data = e.read()
        return Response(content=data, status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/tenant/dashboard/supply-stats")
async def proxy_dashboard_supply_stats(request: Request):
    """Proxy cho API Supply Stats Dashboard."""
    url = "https://api.trustid.com.vn/tenant/dashboard/supply-stats"
    try:
        auth_header = request.headers.get("Authorization")
        headers = {"User-Agent": "Mozilla/5.0"}
        if auth_header:
            headers["Authorization"] = auth_header
            
        req = urllib.request.Request(url, headers=headers)
        with urllib.request.urlopen(req) as response:
            data = response.read()
            return Response(content=data, media_type="application/json")
    except urllib.error.HTTPError as e:
        data = e.read()
        return Response(content=data, status_code=e.code, media_type="application/json")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/files/upload")
@app.post("/upload")
async def handle_file_upload(file: UploadFile = File(...)):
    """Xử lý tải file lên cục bộ tránh lỗi 413 Payload Too Large từ máy chủ bên thứ ba."""
    try:
        os.makedirs("uploads", exist_ok=True)
        filename = file.filename or "upload.jpg"
        ext = os.path.splitext(filename)[1]
        if not ext:
            ext = ".jpg"
        unique_name = f"{uuid.uuid4().hex[:12]}{ext}"
        file_path = os.path.join("uploads", unique_name)
        
        with open(file_path, "wb") as buffer:
            shutil.copyfileobj(file.file, buffer)
            
        file_url = f"http://127.0.0.1:8000/uploads/{unique_name}"
        return {
            "success": True,
            "url": file_url,
            "relative_url": f"/uploads/{unique_name}",
            "filename": unique_name,
            "data": {
                "url": file_url,
                "filename": unique_name,
            }
        }
    except Exception as e:
        print(f"[Upload Error] {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.api_route("/{path:path}", methods=["GET", "POST", "PUT", "DELETE", "PATCH"])
async def catch_all_proxy(path: str, request: Request):
    """Fallback proxy chuyển tiếp mọi request khác sang API thật của TrustID."""
    url = f"https://api.trustid.com.vn/{path}"
    
    query_params = request.url.query
    if query_params:
        url = f"{url}?{query_params}"
        
    try:
        body = await request.body()
        method = request.method
        
        headers = {}
        for k, v in request.headers.items():
            if k.lower() not in ["host", "content-length", "connection", "accept-encoding"]:
                headers[k] = v
        headers["User-Agent"] = "Mozilla/5.0"
        headers["Host"] = "api.trustid.com.vn"
        
        # print request info for debugging
        print(f"[Proxy Request] {method} {url} | Headers: {headers}")
        
        # urllib yêu cầu data phải là None đối với GET/DELETE hoặc các request không body
        req_data = body if method in ["POST", "PUT", "PATCH", "DELETE"] and body else None
        
        req = urllib.request.Request(
            url,
            data=req_data,
            headers=headers,
            method=method
        )
        
        try:
            with urllib.request.urlopen(req) as response:
                content = response.read()
                resp_headers = {}
                for k, v in response.headers.items():
                    if k.lower() not in ["content-encoding", "transfer-encoding", "content-length", "connection"]:
                        resp_headers[k] = v
                print(f"[Proxy Response] Success {response.status}")
                return Response(content=content, status_code=response.status, headers=resp_headers)
        except urllib.error.HTTPError as e:
            content = e.read()
            resp_headers = {}
            for k, v in e.headers.items():
                if k.lower() not in ["content-encoding", "transfer-encoding", "content-length", "connection"]:
                    resp_headers[k] = v
            print(f"[Proxy Response] HTTPError {e.code} | Content: {content[:200]}")
            return Response(content=content, status_code=e.code, headers=resp_headers)
            
    except Exception as e:
        print(f"[Proxy Error] Exception: {e}")
        raise HTTPException(status_code=500, detail=str(e))
