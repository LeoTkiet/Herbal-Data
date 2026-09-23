import logging
import os
import random
import time
from typing import Dict, List, Optional

from src.ai_manager import GeminiKeyPool
from src.db_manager import DatabaseManager
from src.pdf_processor import PDFProcessor

logger = logging.getLogger(__name__)


class HerbalScrapingPipeline:
    """
    Orchestrates the entire scraping pipeline:
      1. Idempotency Check (Verify URL crawl status via crawled_logs).
      2. Anti-Bot Bypass (Random delay 3 - 7 seconds).
      3. Download PDF & Extract Text.
      4. AI Extraction via Gemini (Key Pool Rotation).
      5. Database storage & update crawled_logs.
      6. Zero Disk Footprint (Guaranteed temporary PDF deletion in finally block).
    """

    def __init__(
        self,
        ai_pool: Optional[GeminiKeyPool] = None,
        db_manager: Optional[DatabaseManager] = None,
        pdf_processor: Optional[PDFProcessor] = None,
        min_delay: float = 3.0,
        max_delay: float = 7.0,
    ):
        self.ai_pool = ai_pool or GeminiKeyPool()
        self.db = db_manager or DatabaseManager()
        self.pdf_processor = pdf_processor or PDFProcessor()
        self.min_delay = min_delay
        self.max_delay = max_delay

    def process_url(self, url: str) -> bool:
        """
        Process scraping and extracting a single medical document from URL.
        Returns True if successful or previously crawled, False on failure.
        """
        logger.info(f"\n{'='*60}\nStarting URL processing: {url}\n{'='*60}")

        # 1. [Idempotency] Check crawled_logs
        if self.db.is_url_crawled(url):
            logger.info(f"⏭️ [Idempotency] URL previously crawled successfully. Skipping: {url}")
            return True

        # 2. [Anti-Bot] Random pause between requests
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.info(f"⏳ [Anti-Bot] Pausing {delay:.2f} seconds before downloading document...")
        time.sleep(delay)

        temp_pdf_path: Optional[str] = None
        try:
            # 3. [Download & Read] Download PDF to local disk and extract text
            temp_pdf_path = self.pdf_processor.download_pdf(url)
            raw_text = self.pdf_processor.extract_text(temp_pdf_path)

            # 4. [Extraction] Pass text to Gemini for structured JSON extraction
            logger.info(f"🤖 [AI Extraction] Sending content to Gemini ({self.ai_pool.model_name})...")
            extracted_json = self.ai_pool.extract_herb_data(raw_text)

            # 5. [Store DB & Log] Save to herbs_raw and mark success in crawled_logs
            doc_id = self.db.insert_herb_data(extracted_json, source_url=url)
            self.db.log_crawl(
                url=url,
                status="success",
                metadata={"herb_raw_id": str(doc_id)},
            )
            logger.info(f"🎉 Successfully completed processing for URL: {url}")
            return True

        except Exception as e:
            logger.error(f"❌ Error occurred while processing URL {url}: {e}", exc_info=True)
            self.db.log_crawl(
                url=url,
                status="failed",
                error_message=str(e),
            )
            return False

        finally:
            # 6. [Zero Disk Footprint] MANDATORY cleanup of temporary PDF file
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.remove(temp_pdf_path)
                    logger.info(
                        f"🧹 [Zero Disk Footprint] Cleaned up temporary PDF file: {temp_pdf_path}"
                    )
                except OSError as cleanup_err:
                    logger.warning(
                        f"⚠️ Failed to remove temporary file {temp_pdf_path}: {cleanup_err}"
                    )

    def process_herb(self, herb_name: str, urls: List[str]) -> bool:
        """
        Synthesized processing workflow for a single herb species:
          1. Download and extract text from all PDF files for this herb.
          2. Zero Disk Footprint: Delete each temporary PDF file immediately in finally.
          3. Consolidate text from all research papers into a single unified context.
          4. Send once to Gemini to synthesize clean, deduplicated herbal data.
          5. Save/merge into 'herbs_raw' collection as 1 unique document (No row duplicated!).
          6. Record crawl status for each URL in 'crawled_logs'.
        """
        logger.info(
            f"\n{'='*70}\n🌿 Starting synthesized processing for herb: '{herb_name}' ({len(urls)} PDF documents)\n{'='*70}"
        )

        if not urls:
            logger.warning(f"⚠️ No PDF URLs found for herb '{herb_name}'.")
            return False

        extracted_docs: List[Dict[str, str]] = []
        successful_urls: List[str] = []

        for idx, url in enumerate(urls, 1):
            logger.info(f"--- Processing document [{idx}/{len(urls)}]: {url} ---")

            # Check Idempotency O(1) in crawled_logs
            if self.db.is_url_crawled(url) and self.db.is_herb_in_database(herb_name):
                logger.info(
                    f"   ⏭️ [Idempotency] URL previously crawled and herb '{herb_name}' exists in DB. Skipping: {url}"
                )
                continue

            # Anti-Bot delay
            delay = random.uniform(self.min_delay, self.max_delay)
            time.sleep(delay)

            temp_pdf_path: Optional[str] = None
            try:
                temp_pdf_path = self.pdf_processor.download_pdf(url)
                raw_text = self.pdf_processor.extract_text(temp_pdf_path)
                if raw_text and raw_text.strip():
                    extracted_docs.append({"url": url, "text": raw_text.strip()})
                    successful_urls.append(url)
                    logger.info(f"   ✅ Finished extracting text from: {url}")
                else:
                    self.db.log_crawl(
                        url=url,
                        status="failed",
                        error_message="Extracted text is empty",
                        metadata={"herb": herb_name},
                    )
            except Exception as e:
                logger.warning(f"   ⚠️ Error downloading/reading PDF from {url}: {e}")
                self.db.log_crawl(
                    url=url,
                    status="failed",
                    error_message=str(e),
                    metadata={"herb": herb_name},
                )
            finally:
                # Zero Disk Footprint guarantee
                if temp_pdf_path and os.path.exists(temp_pdf_path):
                    try:
                        os.remove(temp_pdf_path)
                        logger.info(
                            f"   🧹 [Zero Disk Footprint] Removed temporary PDF: {temp_pdf_path}"
                        )
                    except OSError:
                        pass

        if not extracted_docs:
            logger.error(
                f"❌ Failed to extract valid content from {len(urls)} PDF files for herb '{herb_name}'."
            )
            return False

        # Concatenate papers into a single synthesized context block
        context_parts = []
        for i, doc in enumerate(extracted_docs, 1):
            context_parts.append(
                f"=== RESEARCH DOCUMENT [{i}] (Source: {doc['url']}) ===\n{doc['text'][:15000]}"
            )
        combined_text = "\n\n".join(context_parts)

        logger.info(
            f"🤖 [AI Synthesis] Sending synthesis of {len(extracted_docs)} research papers for herb '{herb_name}' to Gemini..."
        )

        try:
            synthesis_prompt = (
                f"Below are scientific medical research documents regarding the medicinal plant '{herb_name}'.\n"
                f"Please analyze, cross-reference, and synthesize all pharmacological properties, chemical compounds, "
                f"and curable diseases into a single structured record, eliminating all duplicate information:\n\n"
                f"{combined_text}"
            )
            extracted_json = self.ai_pool.extract_herb_data(synthesis_prompt)

            # Save into MongoDB with No Row Duplication mechanism (merged into 1 document)
            doc_id = self.db.save_or_update_herb_data(
                data=extracted_json,
                source_urls=successful_urls,
                queried_herb_name=herb_name,
            )

            # Record success in crawled_logs for all documents that contributed to this herb
            for url in successful_urls:
                self.db.log_crawl(
                    url=url,
                    status="success",
                    metadata={"herb": herb_name, "herb_raw_id": str(doc_id)},
                )

            logger.info(
                f"🎉 Successfully synthesized data for herb '{herb_name}' (Document ID: {doc_id})!"
            )
            return True

        except Exception as e:
            logger.error(
                f"❌ Error during Gemini synthesis for herb '{herb_name}': {e}",
                exc_info=True,
            )
            return False

    def run_by_herbs(self, herb_to_urls: Dict[str, List[str]]) -> Dict[str, int]:
        """
        Execute pipeline per herb species (1 herb = 1 unique row).
        """
        logger.info(
            f"🚀 Starting Herbal Synthesis Pipeline for {len(herb_to_urls)} herb species."
        )
        stats = {
            "total_herbs": len(herb_to_urls),
            "success_herbs": 0,
            "failed_herbs": 0,
        }

        for idx, (herb_name, urls) in enumerate(herb_to_urls.items(), 1):
            logger.info(f"\n--- Progress: Herb species [{idx}/{len(herb_to_urls)}] ---")
            success = self.process_herb(herb_name, urls)
            if success:
                stats["success_herbs"] += 1
            else:
                stats["failed_herbs"] += 1

        logger.info(
            f"\n📊 Herbal Synthesis Summary:\n"
            f"   - Total herb species: {stats['total_herbs']}\n"
            f"   - Succeeded: {stats['success_herbs']}\n"
            f"   - Failed: {stats['failed_herbs']}\n"
        )
        return stats

    def run(self, urls: List[str]) -> Dict[str, int]:
        """
        Execute pipeline on a direct list of URLs (backward compatibility).
        Returns scraping statistics.
        """
        logger.info(f"🚀 Starting Herbal Data Scraping Pipeline with {len(urls)} URLs.")
        stats = {"total": len(urls), "success": 0, "failed": 0, "skipped": 0}

        for idx, url in enumerate(urls, 1):
            logger.info(f"\n--- Progress: [{idx}/{len(urls)}] ---")
            if self.db.is_url_crawled(url):
                stats["skipped"] += 1
                logger.info(f"Skipping URL {url} as it was previously crawled.")
                continue

            success = self.process_url(url)
            if success:
                stats["success"] += 1
            else:
                stats["failed"] += 1

        logger.info(
            f"\n📊 Crawling Summary:\n"
            f"   - Total URLs: {stats['total']}\n"
            f"   - Skipped (Already existed): {stats['skipped']}\n"
            f"   - Succeeded: {stats['success']}\n"
            f"   - Failed: {stats['failed']}\n"
        )
        return stats
