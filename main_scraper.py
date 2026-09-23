import argparse
import json
import logging
import os
import random
import signal
import sys
import time
from typing import Any, Dict, List, Optional

# Configure UTF-8 for stdout/stderr on Windows
if sys.stdout and hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass
if sys.stderr and hasattr(sys.stderr, "reconfigure"):
    try:
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass

from dotenv import load_dotenv

from src.db_manager import DatabaseManager
from src.herb_name_spider import HerbNameSpider
from src.pipeline import HerbalScrapingPipeline
from src.spider import PDFSpider

# Alias for compatibility with LocalScraperPipeline naming
LocalScraperPipeline = HerbalScrapingPipeline

# Standard logging configuration
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MainScraper")

# Global graceful shutdown state
shutdown_requested = False


def sigint_handler(signum, frame):
    """
    Handle SIGINT (Ctrl+C) gracefully.
    First Ctrl+C requests a graceful shutdown, completing the current herb.
    Second Ctrl+C forces immediate termination.
    """
    global shutdown_requested
    if not shutdown_requested:
        shutdown_requested = True
        logger.warning(
            "\n🛑 Interruption signal (Ctrl+C) received! Gracefully completing current herb before exiting..."
        )
        logger.warning("   (Press Ctrl+C again to force immediate termination.)")
    else:
        logger.critical("\n💥 Second Ctrl+C received! Forcing immediate termination.")
        sys.exit(130)


# Register SIGINT signal handler
try:
    signal.signal(signal.SIGINT, sigint_handler)
except Exception:
    pass


def interruptible_sleep(seconds: float) -> bool:
    """
    Sleep in short intervals to respond immediately to graceful shutdown signals.
    Returns False if shutdown was requested during sleep, True otherwise.
    """
    step = 0.5
    elapsed = 0.0
    while elapsed < seconds:
        if shutdown_requested:
            return False
        time.sleep(min(step, seconds - elapsed))
        elapsed += step
    return True

# Default Master List file (JSON seed data)
DEFAULT_MASTER_JSON = "vietnamese_herbs.json"

# Fallback herb entities if file is not found
FALLBACK_HERB_ENTITIES = [
    {"name": "Sâm Ngọc Linh", "scientific_name": "Panax vietnamensis"},
    {"name": "Xạ đen", "scientific_name": "Ehretia asperula"},
    {"name": "Cà gai leo", "scientific_name": "Solanum procumbens"},
    {"name": "Diệp hạ châu", "scientific_name": "Phyllanthus urinaria"},
    {"name": "Cam thảo", "scientific_name": "Glycyrrhiza uralensis"},
    {"name": "Ba kích", "scientific_name": "Morinda officinalis"},
    {"name": "Đinh lăng", "scientific_name": "Polyscias fruticosa"},
    {"name": "Kim tiền thảo", "scientific_name": "Desmodium styracifolium"},
    {"name": "Trinh nữ hoàng cung", "scientific_name": "Crinum latifolium"},
    {"name": "Bình vôi", "scientific_name": "Stephania glabra"},
]


def load_herbs_from_file(file_path: str) -> List[Dict[str, str]]:
    """
    Read herb entities from a .json or .txt file.
    - If .json: Read array of objects {"name": ..., "scientific_name": ...}.
    - If .txt: Read comma-separated values ','.
    """
    if not os.path.exists(file_path):
        return []

    # JSON format
    if file_path.lower().endswith(".json"):
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    normalized = []
                    for item in data:
                        if isinstance(item, dict) and item.get("name"):
                            normalized.append({
                                "name": item.get("name", "").strip(),
                                "scientific_name": item.get("scientific_name", "").strip(),
                            })
                        elif isinstance(item, str) and item.strip():
                            normalized.append({"name": item.strip(), "scientific_name": ""})
                    return normalized
        except Exception as e:
            logger.error(f"❌ Error reading JSON file {file_path}: {e}")
            return []

    # Comma-separated TXT format
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            raw_content = f.read()

        herbs = [
            item.strip()
            for item in raw_content.split(",")
            if item.strip() and not item.strip().startswith("#")
        ]

        seen = set()
        unique_entities: List[Dict[str, str]] = []
        for h in herbs:
            if h.lower() not in seen:
                seen.add(h.lower())
                unique_entities.append({"name": h, "scientific_name": ""})

        return unique_entities

    except Exception as e:
        logger.error(f"❌ Error reading TXT file {file_path}: {e}")
        return []


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Herbal Data Scraping Agent - Entity-centric Crawler extracting Vietnamese herbal medicine data from PDF research papers"
    )
    # Phase selection
    parser.add_argument(
        "--phase",
        "-p",
        type=str,
        choices=["all", "phase0", "phase12"],
        default="all",
        help="Select execution phase: 'phase0' (Master List discovery), 'phase12' (Auto-discovery + PDF Pipeline), or 'all' (entire workflow)",
    )
    # Phase 0 config: New herbs target limit
    parser.add_argument(
        "--phase0-limit",
        type=int,
        default=30,
        help="Maximum number of NEW herb species to discover in Phase 0 (default: 30)",
    )
    # Phase 2 config: Maximum PDF results per herb
    parser.add_argument(
        "--max-results",
        type=int,
        default=5,
        help="Maximum number of PDF search results per herb in Phase 2 (default: 5)",
    )
    # Phase 2 config: Limit of saved herbs in database
    parser.add_argument(
        "--phase12-limit",
        type=int,
        default=None,
        help="Maximum number of herbs successfully processed and saved to database before stopping (default: unlimited)",
    )
    # Master List file path
    parser.add_argument(
        "--file",
        "--herbs-file",
        type=str,
        dest="file",
        default=DEFAULT_MASTER_JSON,
        help="Path to Master List .json or .txt file (default: vietnamese_herbs.json)",
    )
    parser.add_argument(
        "--source-url",
        type=str,
        default=None,
        help="Optional seed URL for HerbNameSpider to scrape plant name directory in Phase 0",
    )
    parser.add_argument(
        "--herbs",
        type=str,
        default=None,
        help="Comma-separated herb names to process directly (runs for Phase 1 & 2)",
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        default=None,
        help="List of herb names or keywords provided via command line arguments",
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        default=None,
        help="List of direct PDF URLs to process (Direct Mode, bypasses Spider)",
    )
    return parser.parse_args()


def run_phase_0(args: argparse.Namespace) -> int:
    """
    Execute Phase 0: Automated Master List collection (HerbNameSpider)
    until target new herbs limit is reached (--phase0-limit).
    """
    master_file = args.file
    logger.info(f"\n{'='*70}")
    logger.info(
        f"🕷️ [Phase 0] Activating HerbNameSpider to collect Master List..."
    )
    logger.info(f"   ↳ Target: Discover up to {args.phase0_limit} new herb species")
    logger.info(f"   ↳ Destination file: '{master_file}'")
    logger.info(f"{'='*70}")

    name_spider = HerbNameSpider()
    added = name_spider.update_master_list(
        json_path=master_file,
        source_url=args.source_url,
        limit=args.phase0_limit,
    )
    logger.info(
        f"✅ [Phase 0 Complete] Successfully appended {added} new herb species into '{master_file}'."
    )
    return added


def run_phase_12(args: argparse.Namespace) -> None:
    """
    Execute Phase 1 & Phase 2 workflow:
    - Phase 1 (Entity Discovery): Read Master List, check O(1) keyword_logs, search DDGS with query format {herb_name} nghiên cứu filetype:pdf.
    - Phase 2 (Core Extraction): Check O(1) crawled_logs, download PDF, extract text, Gemini AI 1-call Synthesis, store in MongoDB herbs_raw.
    """
    logger.info(f"\n{'='*70}")
    logger.info(
        f"🌿 [Phase 1 & 2] Activating Entity Auto-Discovery & Core Extraction Pipeline..."
    )
    limit_info = (
        f", DB save limit: {args.phase12_limit}"
        if (args.phase12_limit and args.phase12_limit > 0)
        else ""
    )
    logger.info(f"   ↳ PDF results limit per herb: {args.max_results}{limit_info}")
    logger.info(f"{'='*70}")

    # 1. Load herb entities list (Master List)
    herb_entities: List[Dict[str, str]] = []

    if args.herbs:
        raw_names = [h.strip() for h in args.herbs.split(",") if h.strip()]
        herb_entities = [{"name": h, "scientific_name": ""} for h in raw_names]
    elif args.keywords:
        herb_entities = [
            {"name": k.strip(), "scientific_name": ""} for k in args.keywords if k.strip()
        ]
    elif args.file:
        herb_entities = load_herbs_from_file(args.file)

    if not herb_entities:
        logger.warning(
            f"⚠️ No herb entities found in '{args.file}'. Using fallback seed entities."
        )
        herb_entities = FALLBACK_HERB_ENTITIES

    logger.info(
        f"📋 Loaded Master List of {len(herb_entities)} herb species ready for scanning."
    )

    # 2. Initialize DatabaseManager, PDFSpider, and Pipeline
    db = DatabaseManager()
    spider = PDFSpider(max_results_per_keyword=args.max_results)
    pipeline = LocalScraperPipeline(db_manager=db)

    # Synchronize incomplete keywords from previous runs (allows resuming unfinished herbs)
    db.sync_unprocessed_keywords()

    total_entities = len(herb_entities)
    success_count = 0
    skipped_count = 0

    # 3. Iterate over each herb species
    for idx, entity in enumerate(herb_entities, 1):
        if shutdown_requested:
            logger.info("🛑 Graceful shutdown requested. Stopping execution loop safely.")
            break

        herb_name = entity.get("name", "").strip()
        scientific_name = entity.get("scientific_name", "").strip()

        if not herb_name:
            continue

        sci_info = f" ({scientific_name})" if scientific_name else ""
        logger.info(f"\n{'#'*70}")
        logger.info(f"🌿 Progress: Herb species [{idx}/{total_entities}]: '{herb_name}'{sci_info}")
        logger.info(f"{'#'*70}")

        # Step 3.1: O(1) Check in keyword_logs and herbs_raw
        if db.is_keyword_searched(herb_name, scientific_name=scientific_name):
            logger.info(
                f"⏭️ [O(1) Keyword Check] Herb '{herb_name}'{sci_info} previously completed in database. SKIPPING."
            )
            skipped_count += 1
            continue

        # Step 3.2: Search for PDF links via DDGS: {herb_name} nghiên cứu filetype:pdf
        herb_pdf_urls = list(spider.search_keyword(herb_name, max_results=args.max_results))

        # Check if shutdown was requested during spider search
        if shutdown_requested:
            logger.info(f"🛑 Interrupted during search for '{herb_name}'. Exiting gracefully.")
            db.log_keyword(
                keyword=herb_name,
                status="interrupted",
                scientific_name=scientific_name,
                metadata={"found_urls_count": len(herb_pdf_urls)},
            )
            break

        # Step 3.3: Mandatory pause with interruptible delay to prevent DDGS rate limiting
        delay = random.uniform(7.0, 15.0)
        logger.info(
            f"⏳ [DDGS Rate Limit Prevention] Pausing {delay:.2f}s after searching '{herb_name}'..."
        )
        if not interruptible_sleep(delay):
            logger.info(f"🛑 Interrupted during rate-limit delay for '{herb_name}'. Exiting gracefully.")
            db.log_keyword(
                keyword=herb_name,
                status="interrupted",
                scientific_name=scientific_name,
                metadata={"found_urls_count": len(herb_pdf_urls)},
            )
            break

        if not herb_pdf_urls:
            logger.warning(
                f"⚠️ No PDF files found for herb species '{herb_name}'. Skipping extraction."
            )
            db.log_keyword(
                keyword=herb_name,
                status="failed",
                scientific_name=scientific_name,
                metadata={"found_urls_count": 0, "reason": "No PDF files found"},
            )
            continue

        logger.info(
            f"🎯 Found {len(herb_pdf_urls)} PDF files for '{herb_name}'. Starting extraction & synthesis..."
        )

        # Step 3.4: Hand over URL list to Pipeline
        # (Download PDF -> Extract Text -> LLM Synthesis -> Save herbs_raw -> Delete temporary PDF)
        success = pipeline.process_herb(herb_name, herb_pdf_urls)

        # Step 3.5: Record definitive status in keyword_logs AFTER pipeline completion
        if success:
            success_count += 1
            db.log_keyword(
                keyword=herb_name,
                status="completed",
                scientific_name=scientific_name,
                metadata={"found_urls_count": len(herb_pdf_urls), "saved_to_db": True},
            )
            if args.phase12_limit and args.phase12_limit > 0 and success_count >= args.phase12_limit:
                logger.info(
                    f"🏁 [Phase 1 & 2 Limit Reached] Processed and saved target {args.phase12_limit} herbs into database (--phase12-limit). Stopping run."
                )
                break
        else:
            db.log_keyword(
                keyword=herb_name,
                status="failed",
                scientific_name=scientific_name,
                metadata={"found_urls_count": len(herb_pdf_urls), "saved_to_db": False},
            )

        if shutdown_requested:
            logger.info(
                f"🛑 Gracefully completed herb '{herb_name}'. Safe shutdown confirmed."
            )
            break

    logger.info(
        f"\n📊 Phase 1 & 2 Summary (Entity-centric Flow):\n"
        f"   - Total herbs in Master List: {total_entities}\n"
        f"   - Skipped (Previously completed in database): {skipped_count}\n"
        f"   - Successfully processed (Synthesized & saved to herbs_raw): {success_count}\n"
        f"   - Interrupted / Failed: {total_entities - skipped_count - success_count}\n"
    )


def main():
    # 1. Load environment variables from .env
    load_dotenv()

    # 2. Parse command line arguments
    args = parse_arguments()

    try:
        logger.info("🌿 Initializing Herbal Data Scraping Agent...")
        logger.info(f"⚙️ Execution mode: Phase = '{args.phase.upper()}'")

        # 3. Direct Mode: If user supplies direct PDF URLs
        if args.urls:
            target_urls = [u.strip() for u in args.urls if u.strip()]
            logger.info(f"📋 Using {len(target_urls)} directly specified URLs.")
            logger.info(f"🎯 Total PDF links provided to Pipeline: {len(target_urls)}")
            pipeline = LocalScraperPipeline()
            results = pipeline.run(target_urls)
            logger.info(f"✨ Execution completed: {results}")
            return

        # 4. Route by Phase: 'all', 'phase0', 'phase12'
        if args.phase in ("all", "phase0"):
            if not shutdown_requested:
                run_phase_0(args)

        if args.phase in ("all", "phase12"):
            if not shutdown_requested:
                run_phase_12(args)

        if shutdown_requested:
            logger.warning("🛑 Execution stopped early due to user interruption. Data integrity preserved.")
        else:
            logger.info(f"🎉 Entire execution for phase '{args.phase.upper()}' completed successfully!")

    except KeyboardInterrupt:
        logger.warning("\n🛑 User interrupted execution via keyboard (Ctrl+C). Clean shutdown confirmed.")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"💥 Fatal unhandled exception occurred: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
