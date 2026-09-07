-- ================================================================
-- HỆ THỐNG TRUY XUẤT NGUỒN GỐC TRUSTID SCAN AI
-- Minh chứng Kỹ thuật Tuần 7: Cấu trúc Cơ sở dữ liệu Nội bộ (SQLite)
-- Tệp tin CSDL: scan_state.db
-- Sinh viên: Hoàng Trung Thành - MSSV: 0194867 - Lớp: 67CS (HUCE)
-- ================================================================

-- Bảng lưu vết trạng thái lượt quét gần nhất theo từng mã tem QR
CREATE TABLE IF NOT EXISTS last_scan (
    code            TEXT PRIMARY KEY,              -- Mã định danh duy nhất của tem QR (Unique Code)
    lat             REAL NOT NULL,                 -- Vĩ độ GPS của lượt quét gần nhất (WGS-84)
    long            REAL NOT NULL,                 -- Kinh độ GPS của lượt quét gần nhất (WGS-84)
    timestamp       TEXT NOT NULL,                 -- Mốc thời gian quét chuẩn ISO 8601 (VD: 2026-07-29T10:30:00)
    scan_count      INTEGER DEFAULT 1,             -- Tổng số lần mã tem này đã được quét trong lịch sử
    is_compromised  INTEGER DEFAULT 0              -- Cờ đánh dấu tem nghi vấn giả mạo (0: Bình thường, 1: Giả mạo)
);

-- Chỉ mục tối ưu tốc độ tìm kiếm theo mã tem (phản hồi < 1ms)
CREATE INDEX IF NOT EXISTS idx_last_scan_code ON last_scan(code);

-- ================================================================
-- CÁC CÂU LỆNH TRUY VẤN NGHIỆP VỤ CHÍNH TRONG DỊCH VỤ API (app.py)
-- ================================================================

-- 1. Truy vấn kiểm tra lượt quét trước đó của mã tem:
-- SELECT lat, long, timestamp, scan_count, is_compromised FROM last_scan WHERE code = ?;

-- 2. Cập nhật / Ghi đè trạng thái lượt quét mới sau khi AI chấm điểm:
-- INSERT OR REPLACE INTO last_scan (code, lat, long, timestamp, scan_count, is_compromised)
-- VALUES (?, ?, ?, ?, ?, ?);

-- 3. Xóa toàn bộ trạng thái (Dùng cho endpoint DELETE /reset-state khi demo):
-- DELETE FROM last_scan;
