# 🤖 Herbal Data Scraping Agent (Vietnamese Herbs)

## 📌 1. Tổng quan (Overview)
**Herbal Data Scraping Agent** là một hệ thống bot cào và bóc tách dữ liệu thông minh, hoạt động theo mô hình **100% Local-first**. Hệ thống được thiết kế chuyên biệt để tự động thu thập, trích xuất và chuẩn hóa thông tin y học dược liệu về các loại cây thuốc, thảo dược Việt Nam từ các bài báo, công trình nghiên cứu khoa học (research papers) định dạng PDF.

- **Mục tiêu:** Xây dựng cơ sở dữ liệu y học cổ truyền & dược liệu học có cấu trúc chuẩn, phục vụ tra cứu và huấn luyện mô hình AI.
- **Tác giả / Maintainer:** **Huỳnh Tuấn Kiệt (LeoTKiet)**
- **Môi trường hoạt động:** Local Machine (On-demand execution, tối ưu tài nguyên).

---

## 🛠 2. Tech Stack & Dependencies
Hệ thống sử dụng kiến trúc module hóa (**Modular Architecture**) với các công nghệ lõi:

- **Ngôn ngữ:** Python 3.10+
- **Thư viện Web Scraping & Anti-bot:**
  - `requests`: Tải file PDF theo luồng stream.
  - `fake-useragent`: Giả lập đa dạng User-Agent của trình duyệt hiện đại.
- **Xử lý PDF:**
  - `pdfplumber`: Phân tích và trích xuất nội dung văn bản chất lượng cao từ tài liệu nghiên cứu y khoa.
- **Trí tuệ nhân tạo (AI Engine):**
  - `google-generativeai`: Sử dụng model `gemini-1.5-flash` kết hợp System Prompt ép cấu trúc JSON chuẩn.
- **Cơ sở dữ liệu (Database):**
  - `pymongo`: Kết nối và thao tác với MongoDB (Local hoặc Cloud Atlas).
- **Cấu hình:**
  - `python-dotenv`: Quản lý các biến môi trường an toàn qua file `.env`.

### 📁 Cấu trúc Thư mục Dự án
```text
Herbal-Data/
├── .env.example          # File mẫu cấu hình biến môi trường
├── requirements.txt      # Danh sách thư viện phụ thuộc
├── main_scraper.py       # File thực thi chính (CLI & Orchestration)
├── src/                  # Các module chức năng tách biệt
│   ├── __init__.py
│   ├── ai_manager.py     # Gemini Key Pool, bắt lỗi 429 & luân chuyển Key
│   ├── db_manager.py     # MongoDB Lazy Creation, Idempotency & Indexing
│   ├── pdf_processor.py  # Tải và trích xuất text từ tài liệu PDF
│   └── pipeline.py       # Điều phối toàn bộ luồng cào dữ liệu
└── AGENT.md              # Tài liệu đặc tả kiến trúc hệ thống
```

---

## 📜 3. Quy tắc Hoạt động (Operational Rules)
Để đảm bảo an toàn tuyệt đối cho thiết bị local, tránh rò rỉ bộ nhớ, chống nghẽn quota và bảo vệ tài nguyên mạng, Agent tuân thủ 4 quy tắc cốt lõi:

1. **Zero Disk Footprint (Không lưu rác ổ cứng):**
   - File PDF tải về từ internet chỉ được lưu trữ tại thư mục tạm thời của hệ điều hành (`tempfile`).
   - Toàn bộ quá trình xử lý nằm trong khối lệnh `try...except...finally`. Khối `finally` **BẮT BUỘC** gọi `os.remove(temp_pdf_path)` để dọn dẹp file PDF ngay lập tức dù quá trình xử lý thành công hay gặp ngoại lệ.

2. **Anti-Bot Bypass & Politeness (Chống khóa IP):**
   - Header của mỗi request luôn được gán User-Agent ngẫu nhiên từ `fake-useragent`.
   - Trước mỗi lượt request tải tài liệu mới, hệ thống tự động nghỉ ngơi ngẫu nhiên từ **3 đến 7 giây** (`time.sleep(random.uniform(3, 7))`) nhằm tránh bị các hệ thống tường lửa (Cloudflare, WAF) nhận diện và chặn IP.

3. **API Key Rotation (Luân chuyển khóa API tự động):**
   - Quản lý danh sách nhiều `GEMINI_KEYS` từ file `.env`.
   - Bắt chính xác mã lỗi `429 (google.api_core.exceptions.ResourceExhausted)`. Khi một key chạm giới hạn quota, Agent tự động luân chuyển (rotate) sang key tiếp theo trong danh sách và thử lại (retry) mà không làm gián đoạn pipeline hay sập chương trình.

4. **Idempotency & Tracking (Chống cào trùng lặp):**
   - Trước khi thực hiện cào bất kỳ URL nào, Agent truy vấn trong collection `crawled_logs`. Nếu URL đã có trạng thái `success`, hệ thống sẽ lập tức bỏ qua để tiết kiệm quota LLM và băng thông.
   - Trạng thái xử lý (`success` hoặc `failed`) cùng thông điệp lỗi chi tiết luôn được cập nhật vào `crawled_logs`.

---

## 🗄️ 4. Database Autonomy (Quyền tự chủ Cơ sở Dữ liệu)
Agent vận hành với cơ chế **MongoDB Lazy Creation** hoàn toàn tự động khi khởi chạy (Runtime Initialization):

- **Không cần script khởi tạo thủ công:** Không cần file migration hoặc lệnh `init_db.sql`. Database `herbal_db` và các collections sẽ tự động tạo trên MongoDB ngay khi document đầu tiên được ghi nhận.
- **Tự động cấu hình 2 Collections:**
  - `herbs_raw`: Lưu trữ các thông tin dược liệu y khoa đã được cấu trúc hóa.
  - `crawled_logs`: Lưu vết lịch sử cào của từng URL.
- **Tự động đánh Index Unique:** Hàm khởi tạo của `DatabaseManager` tự động kích hoạt `create_index("url", unique=True)` trên collection `crawled_logs`, đảm bảo toàn vẹn dữ liệu và tối ưu tốc độ tra cứu URL.

---

## 🔄 5. Data Pipeline (Luồng Xử lý Dữ liệu)
Quy trình xử lý tuần tự cho mỗi tài liệu nghiên cứu y khoa:

```
[1. URL Đầu vào]
       │
       ▼
[2. Check Log (Idempotency)] ──(Đã cào thành công)──► [Bỏ qua - Tiết kiệm tài nguyên]
       │ (Chưa cào hoặc từng failed)
       ▼
[3. Anti-Bot Delay (3-7s)]
       │
       ▼
[4. Ingestion: Tải PDF tạm thời]
       │
       ▼
[5. Processing: Trích xuất Text qua pdfplumber]
       │
       ▼
[6. Extraction: Gemini 1.5 Flash (Key Pool Rotation)] ──(Lỗi 429)──► [Đổi Key & Thử lại]
       │
       ▼
[7. Storage & Logging: Lưu vào herbs_raw & ghi crawled_logs]
       │
       ▼
[8. Cleanup (finally): Xóa file PDF tạm - Zero Disk Footprint]
```

---

## 🗂 6. JSON Schema (Cấu trúc Cơ sở Dữ liệu)

### 1. Collection `herbs_raw` (Dữ liệu y khoa bóc tách)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89012",
  "herb_name": {
    "scientific": "Phyllanthus urinaria",
    "local": [
      "Diệp hạ châu",
      "Cây chó đẻ răng cưa"
    ]
  },
  "medicinal_properties": [
    "Kháng viêm",
    "Hạ men gan",
    "Lợi tiểu"
  ],
  "active_compounds": [
    "Phyllanthin",
    "Hypophyllanthin",
    "Flavonoids"
  ],
  "curable_diseases": [
    "Viêm gan B",
    "Sỏi thận",
    "Mụn nhọt mẩn ngứa"
  ],
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

## 🚀 7. Hướng dẫn Chạy (Setup & Execution)

### Bước 1: Cài đặt môi trường & Thư viện phụ thuộc
Đảm bảo máy đã cài đặt Python 3.10+, sau đó cài đặt các gói cần thiết:
```bash
pip install -r requirements.txt
```

### Bước 2: Thiết lập Biến Môi trường
Tạo file `.env` từ file mẫu `.env.example`:
```bash
cp .env.example .env
```
Mở `.env` và điền cấu hình:
```env
# MongoDB Connection String
MONGO_URI=mongodb://localhost:27017/

# Danh sách Gemini API Keys (ngăn cách bằng dấu phẩy để hệ thống xoay vòng key khi 429)
GEMINI_KEYS=AIzaSyA_KEY_MOT,AIzaSyB_KEY_HAI,AIzaSyC_KEY_BA
```

### Bước 3: Khởi chạy Hệ thống
Hệ thống cung cấp các phương thức chạy linh hoạt:

1. **Chạy với danh sách URL cụ thể qua dòng lệnh:**
   ```bash
   python main_scraper.py --urls https://example.com/paper1.pdf https://example.com/paper2.pdf
   ```

2. **Chạy danh sách URL từ file text (mỗi dòng 1 URL):**
   ```bash
   python main_scraper.py --file list_papers.txt
   ```

3. **Chạy mặc định (Demo mẫu):**
   ```bash
   python main_scraper.py
   ```

---

## 📈 8. Tiến trình Dự án (Project Progress)
- **Trạng thái hiện tại:** **Hoàn tất setup Base Architecture, Database Configuration, và API Rotation. Đã sẵn sàng chạy thử nghiệm thực tế.**
- **Hạng mục đã hoàn thành:**
  - [x] Thiết lập cấu trúc module dự án chuẩn Clean Code (`src/`).
  - [x] Cơ chế quản lý mảng Gemini API Keys và bắt lỗi 429 ResourceExhausted để tự động xoay vòng Key.
  - [x] Cơ chế MongoDB Lazy Creation và tự động thiết lập Unique Index cho `crawled_logs.url`.
  - [x] Module xử lý PDF và Anti-Bot bypass với User-Agent ngẫu nhiên cùng khoảng nghỉ 3-7s.
  - [x] Cam kết Zero Disk Footprint qua khối lệnh `finally`.
  - [x] Giao diện CLI và bộ điều phối pipeline trong `main_scraper.py`.