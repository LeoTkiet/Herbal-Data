# 🤖 Herbal Data Scraping Agent (Vietnamese Herbs)

## 📌 1. Overview
**Herbal Data Scraping Agent** is an intelligent crawling and extraction system operating on a **100% Local-first** architecture. The system is designed specifically to discover, collect, extract, and standardize medicinal herbal knowledge regarding Vietnamese medicinal plants and herbs from scientific research papers in PDF format.

- **Objective:** Construct a standardized, structured database of traditional medicine and pharmacognosy for query systems and AI model training.
- **Author / Maintainer:** **Huỳnh Tuấn Kiệt (LeoTKiet)**
- **Operating Environment:** Local Machine (On-demand execution, resource-optimized).

---

## 🛠 2. Tech Stack & Dependencies
The system utilizes a **Modular Architecture** powered by modern core technologies:

- **Programming Language:** Python 3.10+
- **Search & Automated Discovery:**
  - `ddgs`: Automatically queries for PDF research papers using the query syntax `filetype:pdf`.
- **Web Scraping & Anti-Bot Bypass:**
  - `requests`: Stream-based PDF downloading.
  - `fake-useragent`: Randomized modern browser User-Agent simulation.
- **PDF Processing:**
  - `pdfplumber`: High-fidelity text extraction from complex scientific paper layouts.
- **Artificial Intelligence (AI Engine):**
  - `google-generativeai`: Uses `gemini-3.6-flash` with structured system instructions enforcing standard JSON output.
- **Database:**
  - `pymongo`: Connectivity and indexing operations for MongoDB (Local or Cloud Atlas).
- **Configuration:**
  - `python-dotenv`: Secure environment variable management via `.env`.

### 📁 Project Directory Structure
```text
Herbal-Data/
├── .env.example          # Environment variable template
├── requirements.txt      # Python dependency list
├── main_scraper.py       # Main CLI entry point & orchestration
├── src/                  # Isolated functional modules
│   ├── __init__.py
│   ├── spider.py         # Automated Discovery Spider (DuckDuckGo Search)
│   ├── ai_manager.py     # Gemini Key Pool, 429 error handling & Key rotation
│   ├── db_manager.py     # MongoDB Lazy Creation, Idempotency & Indexing
│   ├── pdf_processor.py  # PDF downloading and text extraction
│   └── pipeline.py       # Core scraping and synthesis pipeline
└── AGENT.md              # System architecture specification
```

---

## 📜 3. Operational Rules
To ensure safety on local hardware, prevent memory leaks, eliminate quota bottlenecks, and protect network resources, the Agent adheres strictly to 4 core operational rules:

1. **Zero Disk Footprint:**
   - PDF files downloaded from the internet are stored exclusively in the operating system's temporary directory (`tempfile`).
   - The entire download and extraction process is wrapped in a `try...except...finally` construct. The `finally` block **MANDATORILY** executes `os.remove(temp_pdf_path)` to immediately clean up the temporary file regardless of success or failure.

2. **Anti-Bot Bypass & Politeness:**
   - Headers for every HTTP request are assigned a randomized User-Agent from `fake-useragent`.
   - Before executing a search or document download, the system pauses for a random interval between **7 and 15 seconds** (`time.sleep(random.uniform(7, 15))`) to avoid triggering Cloudflare, WAF, or search engine rate limits and IP bans.

3. **API Key Rotation:**
   - Manages a pool of multiple `GEMINI_KEYS` loaded from the `.env` file.
   - Intercepts error `429 (google.api_core.exceptions.ResourceExhausted)`. When a key exhausts its quota, the Agent automatically rotates to the next available key in the pool and retries without crashing or halting the pipeline.

4. **Idempotency & Tracking:**
   - Before downloading or parsing any URL, the Agent queries `crawled_logs`. If the URL has a recorded status of `success`, it is immediately bypassed to save LLM quota and network bandwidth.
   - Execution status (`success` or `failed`) along with detailed error messages are always updated in `crawled_logs`.

5. **Graceful Interruption & Transactional Consistency:**
   - Intercepts `SIGINT` (Ctrl+C). The crawler gracefully completes the herb species currently in flight, ensuring synthesized data is committed to MongoDB and status is cleanly recorded before the process exits.
   - Prevents inconsistent states or partial row corruption. A second consecutive Ctrl+C forces immediate termination if required.

---

## 🗄️ 4. Database Autonomy
The Agent operates with a **MongoDB Lazy Creation** mechanism, automatically preparing data layers at runtime:

- **No Manual Initialization Scripts:** No migration scripts or `init_db.sql` files required. The database `herbal_db` and its collections are automatically instantiated in MongoDB as soon as the first document is written.
- **Three Dedicated Collections:**
  - `herbs_raw`: Stores extracted medical herbal information (1 herb = 1 unique document, no row duplication).
  - `crawled_logs`: Tracks crawl history for each URL (Unique Index on `url` for $O(1)$ lookups).
  - `keyword_logs`: Tracks local and scientific herb names searched (Unique Index on `keyword` for $O(1)$ deduplication).
- **Automatic Index Creation:**
  - `crawled_logs`: `create_index("url", unique=True)`
  - `keyword_logs`: `create_index("keyword", unique=True)` and `create_index("scientific_name")`
  - `herbs_raw`: `create_index("queried_name")` and `create_index("herb_name.scientific")`

---

## 🔄 5. Data Pipeline (Entity-centric Workflow)
The complete data workflow comprises 3 autonomous phases:

```
┌─────────────────────────────────────────────────────────────┐
│ PHASE 0: MASTER LIST DISCOVERY (HERBNAMESPIDER)             │
│ 1. BeautifulSoup scrapes plant/herbal directory web pages   │
│ 2. Extracts Common Name and Latin Scientific Name           │
│ 3. Deduplicates and automatically appends to JSON master    │
└──────────────────────────────┬──────────────────────────────┘
                               │
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 1: ENTITY AUTO-DISCOVERY & O(1) KEYWORD TRACKING      │
│ Iterate over each entity in 'vietnamese_herbs.json':        │
│ 4. Perform O(1) check in 'keyword_logs' (both names)        │
│    ├── (Already searched) ──► Skip                          │
│    └── (Not in logs yet)  ──► Proceed:                      │
│ 5. Pass to PDFSpider search: "{herb} nghiên cứu filetype:pdf"│
│ 6. Record in 'keyword_logs' with status='searched'          │
│ 7. time.sleep(random.uniform(7, 15)) for rate limit safety  │
└──────────────────────────────┬──────────────────────────────┘
                               │ Herb's PDF URLs list
                               ▼
┌─────────────────────────────────────────────────────────────┐
│ PHASE 2: HERB-CENTRIC AI SYNTHESIS PIPELINE                 │
│ 8. Iterate over PDF URLs for this herb:                     │
│    ├── Check O(1) Idempotency in 'crawled_logs'             │
│    ├── Download temporary PDF (tempfile) with fake-UA       │
│    ├── Extract text using pdfplumber                        │
│    ├── Update status in 'crawled_logs'                      │
│    └── Cleanup (finally): Delete temp PDF immediately       │
│ 9. Consolidate text from all research papers for the herb   │
│ 10. Send unified context to Gemini EXACTLY ONCE             │
│     └── Auto-catch 429 & Rotate Key (Key Pool)              │
│ 11. Save/Merge into 'herbs_raw' (No Row Duplicated)         │
│     └── 1 herb = 1 unique row, stores all source_urls       │
└─────────────────────────────────────────────────────────────┘
```

---

## 🗂 6. JSON Schemas (Database Structure)

### 1. Collection `herbs_raw` (Extracted Herbal Data - No Row Duplication)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89012",
  "queried_name": "sâm ngọc linh",
  "herb_name": {
    "scientific": "Panax vietnamensis",
    "local": [
      "Sâm Ngọc Linh",
      "Sâm Việt Nam",
      "Cây thuốc giấu"
    ]
  },
  "medicinal_properties": [
    "Vitality enhancement",
    "Anti-stress",
    "Antioxidant"
  ],
  "active_compounds": [
    "Majonoside-R2",
    "Ginsenoside Rb1",
    "Ginsenoside Rg1"
  ],
  "curable_diseases": [
    "Physical asthenia",
    "Fatigue and stress",
    "Circulatory deficiency"
  ],
  "source_urls": [
    "https://example.com/research/paper1.pdf",
    "https://example.com/research/paper2.pdf"
  ],
  "created_at": 1696123450.123,
  "updated_at": 1696123456.789
}
```

### 2. Collection `crawled_logs` (PDF Crawl Log & Idempotency)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89013",
  "url": "https://example.com/research/paper1.pdf",
  "status": "success",
  "error_message": null,
  "metadata": {
    "herb": "sâm ngọc linh"
  },
  "created_at": 1696123450.123,
  "updated_at": 1696123456.789
}
```

### 3. Collection `keyword_logs` (Keyword Log & O(1) Deduplication)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89014",
  "keyword": "sâm ngọc linh",
  "scientific_name": "Panax vietnamensis",
  "status": "completed",
  "metadata": {
    "found_urls_count": 5,
    "saved_to_db": true
  },
  "searched_at": 1696123455.123,
  "created_at": 1696123455.123
}
```
*(Status values: `completed`, `interrupted`, `failed`, `processing`)*

---

## 🚀 7. Setup & Execution Guide

### Step 1: Environment & Dependencies
Ensure Python 3.10+ is installed, then install all dependencies:
```bash
pip install -r requirements.txt
```

### Step 2: Configure Environment Variables
Create a `.env` file from `.env.example`:
```bash
cp .env.example .env
```
Configure `.env`:
```env
# MongoDB Connection String
MONGO_URI=mongodb://localhost:27017/

# Comma-separated Gemini API Keys (for automatic rotation upon 429)
GEMINI_KEYS=AIzaSyA_KEY_1,AIzaSyB_KEY_2,AIzaSyC_KEY_3

# Gemini Model (Default: gemini-3.6-flash)
GEMINI_MODEL=gemini-3.6-flash
```

### Step 3: Run the Agent
The system provides flexible execution modes by phase or full pipeline:

1. **Full Workflow (`--phase all` - Default):**
   ```bash
   python main_scraper.py --phase all --phase0-limit 50 --max-results 5 --phase12-limit 10
   ```
   *Sequential execution: Phase 0 discovers up to 50 new herbs -> Phase 1 O(1) keyword check & DDGS search -> Phase 2 PDF extraction, Gemini synthesis, and storage in MongoDB (stops after 10 herbs saved).*

2. **Phase 0 Only (`--phase phase0`):**
   ```bash
   python main_scraper.py --phase phase0 --phase0-limit 50
   ```

3. **Phase 1 & 2 Workflow (`--phase phase12`):**
   ```bash
   python main_scraper.py --phase phase12 --max-results 3 --phase12-limit 5
   ```

4. **Direct Mode (Specific PDF URLs, bypassing Spider):**
   ```bash
   python main_scraper.py --urls https://example.com/paper1.pdf https://example.com/paper2.pdf
   ```

---

## 📈 8. Project Milestones

- **Current Status:** **Completed Entity-centric Crawler architecture with modular phase execution (`phase0`, `phase12`, `all`).**
- **Completed Components:**
  - [x] Clean, modular project structure (`src/`).
  - [x] Gemini API Key Pool rotation with 429 ResourceExhausted handling.
  - [x] MongoDB Lazy Creation and automatic Unique Index configuration for `crawled_logs.url` and `keyword_logs.keyword`.
  - [x] PDF processing and Anti-Bot protection with randomized User-Agents.
  - [x] Zero Disk Footprint guarantee via `finally` blocks.
  - [x] **Phase 0 Master List (`src/herb_name_spider.py`):** Automated plant directory scraper with pagination and limit controls (`--phase0-limit`).
  - [x] **Phase 1 & 2 Entity-centric Pipeline:** $O(1)$ check in `keyword_logs`, DDGS search `"{herb} nghiên cứu filetype:pdf"`, 7-15s delay, PDF extraction, and Gemini 1-call Synthesis in `herbs_raw` (No Row Duplication).
  - [x] **Modular Phase Execution:** Isolated phase execution via `--phase {all, phase0, phase12}`.
  - [x] **Graceful Shutdown & Data Safety:** Intercepts Ctrl+C safely, preserves in-flight data, and synchronizes unfinished crawl tasks.
  - [x] **Gemini 3.6 Flash Upgrade & Extended Key Pool:** Supported high-throughput model with automatic fallback handling across multi-key pool.