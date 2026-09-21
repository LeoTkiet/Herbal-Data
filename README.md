# 🌿 Herbal Data Scraping Agent (Vietnamese Herbs)

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-MongoDB-green.svg)](https://www.mongodb.com/)
[![AI Model](https://img.shields.io/badge/AI-Gemini%201.5%20Flash-orange.svg)](https://ai.google.dev/)
[![Architecture](https://img.shields.io/badge/Architecture-Modular%20OOP-purple.svg)]()
[![License](https://img.shields.io/badge/License-MIT-brightgreen.svg)](LICENSE)

> Hệ thống tự động thu thập, trích xuất và chuẩn hóa tri thức y học dược liệu về các loại cây thuốc, thảo dược Việt Nam từ các bài báo và công trình nghiên cứu khoa học (PDF). Hoạt động **100% Local-first**, cam kết **Zero Disk Footprint**, tự động hóa cơ sở dữ liệu và bảo toàn quota API.

---

## 📌 Tính Năng Nổi Bật

- 🕸️ **Automated Discovery (PDFSpider):** Tự động tìm kiếm link PDF bài báo y học trên DuckDuckGo Search API bằng cú pháp `filetype:pdf`. Hỗ trợ khử trùng lặp (Set) và cơ chế chống rate-limit thông minh.
- 🤖 **Gemini API Key Pool & Auto Rotation:** Quản lý mảng nhiều Gemini API Keys. Tự động bắt mã lỗi `429 (ResourceExhausted)` để chuyển sang key kế tiếp và retry mà không làm sập ứng dụng.
- 🗄️ **MongoDB Lazy Creation:** Tự động kết nối, khởi tạo database `herbal_db`, thiết lập 2 collections `herbs_raw` và `crawled_logs`, đồng thời kích hoạt Unique Index trên `crawled_logs.url` hoàn toàn tự động ở runtime.
- 🧹 **Zero Disk Footprint:** File PDF tải về từ internet chỉ lưu tạm ở thư mục `tempfile`. Khối lệnh `finally` cam kết xóa bỏ file PDF ngay sau khi đọc xong, không để lại rác trên ổ cứng.
- 🛡️ **Anti-Bot & Rate-limiting Politeness:** Sinh `User-Agent` trình duyệt ngẫu nhiên bằng `fake-useragent` và tạo khoảng nghỉ ngẫu nhiên từ 3 đến 7 giây giữa các lượt request để chống bị chặn IP.
- ⚡ **Idempotency Tracking:** Kiểm tra trạng thái cào trong `crawled_logs`. Nếu URL đã từng cào thành công, hệ thống lập tức bỏ qua nhằm tiết kiệm tối đa quota LLM và băng thông.
- 🧩 **Kiến trúc Đa Module (Modular OOP):** Phân chia trách nhiệm rõ ràng trong thư mục `src/`, dễ dàng bảo trì và mở rộng tính năng.

---

## 📁 Cấu Trúc Dự Án

```text
Herbal-Data/
├── .env.example          # Template biến môi trường (MONGO_URI, GEMINI_KEYS)
├── .gitignore            # Bảo mật .env, .venv/ và file tạm
├── requirements.txt      # Danh sách thư viện phụ thuộc
├── main_scraper.py       # File thực thi chính (CLI runner)
├── AGENT.md              # Đặc tả chi tiết kiến trúc của Agent
├── README.md             # Hướng dẫn sử dụng & tổng quan dự án
└── src/                  # Các module chức năng chuyên biệt
    ├── __init__.py       # Package init
    ├── spider.py         # PDFSpider: Tự động tìm kiếm link PDF theo từ khóa
    ├── ai_manager.py     # GeminiKeyPool: Key rotation & trích xuất JSON
    ├── db_manager.py     # DatabaseManager: MongoDB Lazy Creation & Index
    ├── pdf_processor.py  # PDFProcessor: Tải PDF với fake-UA & đọc text
    └── pipeline.py       # HerbalScrapingPipeline: Core pipeline điều phối
```

---

## 🔄 Luồng Hoạt Động (Data Pipeline)

```
[1. URL PDF] 
     │
     ▼
[2. Idempotency Check] ──(Đã cào thành công)──► [Bỏ qua để tiết kiệm quota]
     │ (Chưa cào hoặc failed)
     ▼
[3. Anti-Bot Delay (3-7s)]
     │
     ▼
[4. Download PDF về Local Temp]
     │
     ▼
[5. Trích xuất Text bằng pdfplumber]
     │
     ▼
[6. AI Extraction (Gemini 1.5 Flash)] ──(Gặp lỗi 429)──► [Đổi Key & Retry]
     │
     ▼
[7. Lưu vào MongoDB: herbs_raw & crawled_logs]
     │
     ▼
[8. Cleanup (finally: os.remove) - Zero Disk Footprint]
```

---

## 🗂 Cấu Trúc Dữ Liệu (MongoDB Schemas)

### 1. Collection `herbs_raw` (Dữ liệu y học dược liệu)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89012",
  "herb_name": {
    "scientific": "Phyllanthus urinaria",
    "local": ["Diệp hạ châu", "Cây chó đẻ răng cưa"]
  },
  "medicinal_properties": ["Kháng viêm", "Hạ men gan", "Lợi tiểu"],
  "active_compounds": ["Phyllanthin", "Hypophyllanthin", "Flavonoids"],
  "curable_diseases": ["Viêm gan B", "Sỏi thận", "Mụn nhọt mẩn ngứa"],
  "source_url": "https://example.com/research/phyllanthus_urinaria.pdf",
  "crawled_at": 1696123456.789
}
```

### 2. Collection `crawled_logs` (Nhật ký cào & Idempotency)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89013",
  "url": "https://example.com/research/phyllanthus_urinaria.pdf",
  "status": "success",
  "error_message": null,
  "metadata": {
    "herb_raw_id": "650c8f12a3b4c5d6e7f89012"
  },
  "created_at": 1696123450.123,
  "updated_at": 1696123456.789
}
```

---

## 🚀 Hướng Dẫn Cài Đặt & Sử Dụng

### Bước 1: Clone kho mã nguồn
```bash
git clone https://github.com/LeoTkiet/Herbal-Data.git
cd Herbal-Data
```

### Bước 2: Cài đặt thư viện phụ thuộc
Khuyến khích sử dụng môi trường ảo Python (Virtualenv):
```bash
python -m venv .venv

# Trên Windows (PowerShell):
# Nếu gặp lỗi "running scripts is disabled", chạy lệnh mở quyền cho phiên hiện tại:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\activate

# Trên Windows (Command Prompt - CMD):
.venv\Scripts\activate.bat

# Trên Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### Bước 3: Cấu hình file môi trường `.env`
Tạo file `.env` dựa trên file mẫu `.env.example`:
```bash
# Windows CMD / PowerShell:
copy .env.example .env
# Linux / macOS:
cp .env.example .env
```
Mở file `.env` và điền thông tin:
```env
# MongoDB Connection URI
MONGO_URI=mongodb://localhost:27017/

# Mảng Gemini API Keys (ngăn cách bởi dấu phẩy để kích hoạt luân chuyển key khi 429)
GEMINI_KEYS=AIzaSyA_KEY_1,AIzaSyB_KEY_2,AIzaSyC_KEY_3
```

### Bước 4: Khởi chạy chương trình

1. **Chạy mặc định (Automated Discovery - Tự động tìm bài báo theo từ khóa mẫu):**
   ```bash
   python main_scraper.py
   ```

2. **Tìm kiếm tự động với danh sách từ khóa thảo dược tùy chọn:**
   ```bash
   python main_scraper.py --keywords "nghiên cứu sâm ngọc linh" "tác dụng xạ đen" --max-results 5
   ```

3. **Cào danh sách URL truyền trực tiếp qua dòng lệnh (bỏ qua Spider):**
   ```bash
   python main_scraper.py --urls https://domain.com/paper1.pdf https://domain.com/paper2.pdf
   ```

4. **Cào từ file danh sách URL (mỗi dòng chứa một URL PDF):**
   ```bash
   python main_scraper.py --file list_urls.txt
   ```

---

## 👨‍💻 Tác giả & Duy trì (Maintainer)

- **Tác giả / Maintainer:** Huỳnh Tuấn Kiệt ([LeoTKiet](https://github.com/LeoTkiet))
- **Dự án:** [LeoTkiet/Herbal-Data](https://github.com/LeoTkiet/Herbal-Data)

---

## 📜 Giấy phép (License)

Dự án được phát hành và phân phối theo giấy phép mã nguồn mở **[MIT License](LICENSE)**.

Toàn bộ bản quyền (c) 2026 thuộc về **Huỳnh Tuấn Kiệt ([LeoTKiet](https://github.com/LeoTkiet))**. Bạn được toàn quyền sử dụng, sửa đổi, tích hợp và phân phối phần mềm này theo các điều khoản của giấy phép MIT. Xem chi tiết tại file [LICENSE](LICENSE).