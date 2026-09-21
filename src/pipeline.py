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
    Điều phối toàn bộ luồng cào dữ liệu:
      1. Idempotency Check (Kiểm tra trùng lặp qua crawled_logs).
      2. Anti-Bot Bypass (Nghỉ ngẫu nhiên 3 - 7 giây).
      3. Download PDF & Extract Text.
      4. AI Extraction qua Gemini 1.5 Flash (Key Pool Rotation).
      5. Lưu trữ DB & ghi nhận crawled_logs.
      6. Zero Disk Footprint (Bảo đảm xóa file PDF tạm trong finally).
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
        Xử lý cào và bóc tách một tài liệu y khoa từ URL.
        Trả về True nếu thành công hoặc đã cào trước đó, False nếu lỗi.
        """
        logger.info(f"\n{'='*60}\nBắt đầu xử lý URL: {url}\n{'='*60}")

        # 1. [Idempotency] Kiểm tra trong crawled_logs
        if self.db.is_url_crawled(url):
            logger.info(f"⏭️ [Idempotency] URL đã được cào thành công trước đó. Bỏ qua: {url}")
            return True

        # 2. [Anti-Bot] Nghỉ ngẫu nhiên giữa các request
        delay = random.uniform(self.min_delay, self.max_delay)
        logger.info(f"⏳ [Anti-Bot] Nghỉ ngơi {delay:.2f} giây trước khi tải tài liệu...")
        time.sleep(delay)

        temp_pdf_path: Optional[str] = None
        try:
            # 3. [Tải & Đọc] Tải file PDF về ổ cứng local và đọc text
            temp_pdf_path = self.pdf_processor.download_pdf(url)
            raw_text = self.pdf_processor.extract_text(temp_pdf_path)

            # 4. [Bóc tách] Đưa text qua Gemini để phân tích JSON
            logger.info(f"🤖 [AI Extraction] Đang gửi nội dung tới Gemini ({self.ai_pool.model_name})...")
            extracted_json = self.ai_pool.extract_herb_data(raw_text)

            # 5. [Lưu DB & Log] Lưu vào herbs_raw và đánh dấu success trong crawled_logs
            doc_id = self.db.insert_herb_data(extracted_json, source_url=url)
            self.db.log_crawl(
                url=url,
                status="success",
                metadata={"herb_raw_id": str(doc_id)},
            )
            logger.info(f"🎉 Hoàn thành xử lý thành công URL: {url}")
            return True

        except Exception as e:
            logger.error(f"❌ Xảy ra lỗi khi xử lý URL {url}: {e}", exc_info=True)
            self.db.log_crawl(
                url=url,
                status="failed",
                error_message=str(e),
            )
            return False

        finally:
            # 6. [Zero Disk Footprint] BẮT BUỘC dọn dẹp file PDF tạm
            if temp_pdf_path and os.path.exists(temp_pdf_path):
                try:
                    os.remove(temp_pdf_path)
                    logger.info(
                        f"🧹 [Zero Disk Footprint] Đã dọn dẹp file PDF tạm thời: {temp_pdf_path}"
                    )
                except OSError as cleanup_err:
                    logger.warning(
                        f"⚠️ Không thể xóa file tạm {temp_pdf_path}: {cleanup_err}"
                    )

    def run(self, urls: List[str]) -> Dict[str, int]:
        """
        Thực thi pipeline trên một danh sách các URL.
        Trả về thống kê quá trình cào.
        """
        logger.info(f"🚀 Bắt đầu Herbal Data Scraping Pipeline với {len(urls)} URLs.")
        stats = {"total": len(urls), "success": 0, "failed": 0, "skipped": 0}

        for idx, url in enumerate(urls, 1):
            logger.info(f"\n--- Tiến độ: [{idx}/{len(urls)}] ---")
            if self.db.is_url_crawled(url):
                stats["skipped"] += 1
                logger.info(f"Bỏ qua URL {url} do đã cào thành công.")
                continue

            success = self.process_url(url)
            if success:
                stats["success"] += 1
            else:
                stats["failed"] += 1

        logger.info(
            f"\n📊 Tổng kết cào dữ liệu:\n"
            f"   - Tổng số URL: {stats['total']}\n"
            f"   - Bỏ qua (Đã có sẵn): {stats['skipped']}\n"
            f"   - Thành công: {stats['success']}\n"
            f"   - Thất bại: {stats['failed']}\n"
        )
        return stats
