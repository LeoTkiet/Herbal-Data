# 🌿 Herbal Data Scraping Agent (Vietnamese Herbs)

[![Python Version](https://img.shields.io/badge/Python-3.10%2B-blue.svg)](https://www.python.org/)
[![Database](https://img.shields.io/badge/Database-MongoDB-green.svg)](https://www.mongodb.com/)
[![AI Model](https://img.shields.io/badge/AI-Gemini%203.6%20Flash-orange.svg)](https://ai.google.dev/)
[![Architecture](https://img.shields.io/badge/Architecture-Modular%20OOP-purple.svg)]()
[![License](https://img.shields.io/badge/License-MIT-brightgreen.svg)](LICENSE)

> An automated system for discovering, crawling, extracting, and standardizing medical and pharmacognosy knowledge of Vietnamese medicinal herbs from scientific research papers (PDF). Operates **100% Local-first**, guarantees **Zero Disk Footprint**, automates database management, and preserves API quota.

---

## 📌 Key Features

- 🕷️ **Entity-centric Crawler & Phase 0 Discovery (`HerbNameSpider`):** Automatically discovers herbal plant directories (Vietnamese common names and scientific Latin names) from directory sources (such as Wikipedia medicinal categories), deduplicating and enriching the Master List file `vietnamese_herbs.json`.
- ⚡ **O(1) Keyword Tracking & Smart Resumption (`keyword_logs`):** Manages keyword crawl states with a Unique Index on `keyword` and an index on `scientific_name`. Differentiates between `completed`, `interrupted`, and `failed` states. If a crawl was interrupted mid-stream, the system automatically resumes unfinished herbs without skipping them.
- 🛑 **Graceful Shutdown & Data Integrity (Ctrl+C Safety):** Intercepts `SIGINT` signals so pressing `Ctrl+C` safely finishes processing and writing the current herb to MongoDB before exiting. A second `Ctrl+C` forces immediate termination if required.
- 🕸️ **Automated Discovery (PDFSpider DDGS):** Automatically generates standard queries `"{herb_name} nghiên cứu filetype:pdf"` on DuckDuckGo Search (`DDGS`), with automated deduplication (Set).
- 🛡️ **Anti-Bot & Rate-limiting Politeness:** Enforces random delay with `time.sleep(random.uniform(7, 15))` after each DDGS search query to thoroughly prevent rate limits or IP blocking.
- 🧪 **Multi-Document AI Synthesis & No Row Duplication:** Aggregates all crawled PDF papers for **a single herb species**, synthesizes content, and invokes Gemini **only once** to extract comprehensive medical knowledge. In MongoDB (`herbs_raw`), each plant species is stored in exactly one document (1 row per herb), with source links aggregated in `source_urls`, eliminating row duplication.
- 🤖 **Gemini API Key Pool & Auto Rotation (`Gemini 3.6 Flash`):** Manages an array of Gemini API keys. Automatically intercepts error code `429 (ResourceExhausted)` or recoverable API exceptions to rotate to the next key and retry seamlessly without crashing the application.
- 🗄️ **MongoDB Lazy Creation:** Automatically connects, initializes the `herbal_db` database, configures three collections (`herbs_raw`, `crawled_logs`, `keyword_logs`), and activates Unique Indexes entirely at runtime.
- 🧹 **Zero Disk Footprint:** PDF files downloaded from the internet are stored only in the operating system temporary directory (`tempfile`). A `finally` block guarantees deletion of the temporary PDF immediately after text extraction, leaving no residual disk clutter.
- 🧩 **Modular OOP Architecture:** Clean separation of responsibilities in the `src/` directory, making the codebase maintainable and extensible.

---

## 📁 Project Structure

```text
Herbal-Data/
├── .env.example            # Environment variables template (MONGO_URI, GEMINI_KEYS)
├── .gitignore              # Secures .env, .venv/ and temporary files
├── requirements.txt        # Python dependency manifest
├── vietnamese_herbs.json   # Seed Master List (Common Name + Scientific Name)
├── herbs.txt               # Supplementary text-based herb list
├── main_scraper.py         # Main execution CLI (Entity-centric Runner)
├── AGENT.md                # Detailed Agent Architecture Specification
├── README.md               # Project documentation & overview
├── tests/                  # Automated test suite (Unit tests)
└── src/                    # Specialized functional modules
    ├── __init__.py         # Package init
    ├── herb_name_spider.py # HerbNameSpider: Phase 0 Master List crawler
    ├── spider.py           # PDFSpider: Automated DDGS PDF discovery
    ├── ai_manager.py       # GeminiKeyPool: Key rotation & JSON extraction
    ├── db_manager.py       # DatabaseManager: MongoDB O(1) Index, Upsert & No Duplicate
    ├── pdf_processor.py    # PDFProcessor: PDF download with fake-UA & text extraction
    └── pipeline.py         # HerbalScrapingPipeline: Core herb synthesis coordinator
```

---

## 🔄 Data Pipeline Workflow

```
[Phase 0: HerbNameSpider] ──► Crawl web directory ──► Update Master List: vietnamese_herbs.json
                                                              │
      ┌───────────────────────────────────────────────────────┘
      │
      ▼
[Phase 1: Entity Discovery] ──► Check O(1) keyword_logs (Duplicate name/scientific -> Skip)
      │
      ├──► Not crawled yet: DDGS Search "{herb_name} nghiên cứu filetype:pdf"
      ├──► Record keyword_logs with status='searched'
      └──► Anti-RateLimit delay: 7 - 15 seconds
      │
      ▼
[Phase 2: Core Extraction Pipeline] 
      │ ──► Check O(1) crawled_logs for each PDF URL
      │ ──► Download & Extract Text per PDF (Zero Disk Footprint: finally deletes temp PDF)
      │ ──► Consolidate all papers for the herb species
      │ ──► Send to Gemini AI once for unified synthesis
      └──► Store in MongoDB herbs_raw (1 herb = 1 unique row, source_urls array)
```

---

## 🗂 Data Structures (MongoDB Schemas)

### 1. Collection `herbs_raw` (Medical Herbal Knowledge - No Row Duplication)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89012",
  "queried_name": "sâm ngọc linh",
  "herb_name": {
    "scientific": "Panax vietnamensis",
    "local": ["Sâm Ngọc Linh", "Sâm Việt Nam"]
  },
  "medicinal_properties": ["Vitality enhancement", "Anti-stress", "Antioxidant"],
  "active_compounds": ["Majonoside-R2", "Ginsenoside Rb1"],
  "curable_diseases": ["Physical asthenia", "Fatigue and stress"],
  "source_urls": [
    "https://example.com/research/paper1.pdf",
    "https://example.com/research/paper2.pdf"
  ],
  "created_at": 1696123450.123,
  "updated_at": 1696123456.789
}
```

### 2. Collection `keyword_logs` (Keyword Crawl Log & O(1) Deduplication)
```json
{
  "_id": "650c8f12a3b4c5d6e7f89014",
  "keyword": "sâm ngọc linh",
  "scientific_name": "Panax vietnamensis",
  "status": "completed",
  "metadata": {
    "found_urls_count": 4,
    "saved_to_db": true
  },
  "searched_at": 1696123455.123,
  "created_at": 1696123455.123
}
```
*(Status values: `completed`, `interrupted`, `failed`, `processing`)*

### 3. Collection `crawled_logs` (PDF Crawl Log & Idempotency)
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

---

## 🚀 Installation & Usage Guide

### Step 1: Clone the repository
```bash
git clone https://github.com/LeoTkiet/Herbal-Data.git
cd Herbal-Data
```

### Step 2: Set up dependencies
A Python virtual environment is recommended:
```bash
python -m venv .venv

# On Windows (PowerShell):
# If script execution is disabled, allow execution for current session:
Set-ExecutionPolicy -ExecutionPolicy RemoteSigned -Scope Process
.venv\Scripts\activate

# On Windows (Command Prompt - CMD):
.venv\Scripts\activate.bat

# On Linux/macOS:
source .venv/bin/activate

pip install -r requirements.txt
```

### Step 3: Configure `.env` environment variables
Create a `.env` file based on `.env.example`:
```bash
# Windows CMD / PowerShell:
copy .env.example .env
# Linux / macOS:
cp .env.example .env
```

Open `.env` and fill in your settings:
```env
# MongoDB Connection URI
MONGO_URI=mongodb://localhost:27017/

# Comma-separated Gemini API Keys (activates key rotation on 429 quota exhaustion)
GEMINI_KEYS=AIzaSyA_KEY_1,AIzaSyB_KEY_2,AIzaSyC_KEY_3

# Gemini Model (Default: gemini-3.6-flash)
GEMINI_MODEL=gemini-3.6-flash
```

### Step 4: Run the Scraper

The system operates as an **Entity-centric Crawler**, supporting execution of individual phases or the full end-to-end pipeline:

#### 1. Full Pipeline (`--phase all` - Default):
Executes the sequential flow: Phase 0 Master List Discovery $\rightarrow$ Phase 1 Discovery & O(1) Check $\rightarrow$ Phase 2 PDF Extraction & AI Synthesis:
```bash
# Full workflow: Phase 0 discovers 50 new herbs, Phase 2 searches up to 5 PDFs/herb, stops after saving 10 herbs to DB
python main_scraper.py --phase all --phase0-limit 50 --max-results 5 --phase12-limit 10
```

#### 2. Phase 0 Only (`--phase phase0`):
Collects, parses, and supplements the Master List `vietnamese_herbs.json` from the web until the target number of new herbs is reached:
```bash
# Crawl until 50 new herbal species are collected into the Master List
python main_scraper.py --phase phase0 --phase0-limit 50
```

#### 3. Phase 1 & 2 Workflow (`--phase phase12`):
Runs Phase 1 and Phase 2 together (Phase 1 discovers entities & checks $O(1)$ in `keyword_logs`, Phase 2 extracts PDFs, synthesizes with AI, and stores in `herbs_raw`):
```bash
# Iterate existing Master List, perform O(1) checks, and extract PDFs (max 3 PDFs/herb, stops when 5 herbs are saved)
python main_scraper.py --phase phase12 --max-results 3 --phase12-limit 5
```

#### 4. Additional Flexible Options:
```bash
# Specify custom Master List file and limit saved herbs
python main_scraper.py --phase phase12 --file vietnamese_herbs.json --max-results 3 --phase12-limit 10

# Scan list of herbs passed directly via CLI string
python main_scraper.py --phase phase12 --herbs "sâm ngọc linh, xạ đen, cà gai leo" --max-results 3

# Crawl specific PDF URLs directly (Direct Mode, bypasses Spider)
python main_scraper.py --urls https://domain.com/paper1.pdf https://domain.com/paper2.pdf
```

---

## 👨‍💻 Author & Maintainer

- **Author / Maintainer:** Huỳnh Tuấn Kiệt ([LeoTKiet](https://github.com/LeoTkiet))
- **Repository:** [LeoTkiet/Herbal-Data](https://github.com/LeoTkiet/Herbal-Data)

---

## 📜 License

This project is licensed under the open-source **[MIT License](LICENSE)**.

Copyright (c) 2026 **Huỳnh Tuấn Kiệt ([LeoTKiet](https://github.com/LeoTkiet))**. You are granted full permission to use, modify, integrate, and distribute this software under the terms of the MIT License. See [LICENSE](LICENSE) for details.