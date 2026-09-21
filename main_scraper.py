import argparse
import logging
import sys
from typing import List

# Cấu hình UTF-8 cho stdout/stderr trên Windows
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

from src.pipeline import HerbalScrapingPipeline
from src.spider import PDFSpider

# Alias để tương thích với tên gọi thiết kế LocalScraperPipeline
LocalScraperPipeline = HerbalScrapingPipeline

# Cấu hình logging chuẩn mực
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MainScraper")

# Danh sách từ khóa thảo dược mẫu dùng cho Automated Discovery (PDFSpider)
SAMPLE_HERB_KEYWORDS = [
    "nghiên cứu cây chó đẻ",
    "tác dụng cam thảo",
    "nghiên cứu dược liệu diệp hạ châu",
    "hoạt chất cây cà gai leo",
]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Herbal Data Scraping Agent - Tự động tìm kiếm & Bóc tách dược liệu Việt Nam từ PDF"
    )
    parser.add_argument(
        "--keywords",
        nargs="+",
        help="Danh sách từ khóa thảo dược để Spider tự động tìm kiếm (vd: 'nghiên cứu cam thảo')",
        default=None,
    )
    parser.add_argument(
        "--max-results",
        type=int,
        help="Số lượng kết quả tìm kiếm tối đa cho mỗi từ khóa (mặc định: 5)",
        default=5,
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        help="Danh sách URL PDF cụ thể cần cào trực tiếp (bỏ qua bước Spider)",
        default=None,
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Đường dẫn file text chứa danh sách URL có sẵn (mỗi dòng 1 URL)",
        default=None,
    )
    return parser.parse_args()


def load_explicit_urls(args: argparse.Namespace) -> List[str]:
    """Tải danh sách URL nếu người dùng chỉ định trực tiếp qua --urls hoặc --file."""
    urls = []
    if args.urls:
        urls.extend([u.strip() for u in args.urls if u.strip()])

    if args.file:
        try:
            with open(args.file, "r", encoding="utf-8") as f:
                for line in f:
                    line = line.strip()
                    if line and not line.startswith("#"):
                        urls.append(line)
        except Exception as e:
            logger.error(f"Không thể đọc danh sách URL từ file {args.file}: {e}")

    return urls


def main():
    # 1. Nạp biến môi trường từ .env
    load_dotenv()

    # 2. Xử lý tham số dòng lệnh
    args = parse_arguments()
    explicit_urls = load_explicit_urls(args)

    logger.info("🌿 Khởi tạo Herbal Data Scraping Agent...")

    target_urls: List[str] = []

    # 3. Giai đoạn 1: Thu thập URL (Automated Discovery qua Spider hoặc URL chỉ định)
    if explicit_urls:
        logger.info(f"📋 Sử dụng {len(explicit_urls)} URL được cung cấp trực tiếp từ tham số.")
        target_urls = explicit_urls
    else:
        # Nếu không truyền URL trực tiếp, kích hoạt Automated Discovery Spider
        keywords = args.keywords if args.keywords else SAMPLE_HERB_KEYWORDS
        logger.info(
            f"🕸️ Kích hoạt Automated Discovery (PDFSpider) với {len(keywords)} từ khóa thảo dược..."
        )

        spider = PDFSpider(max_results_per_keyword=args.max_results)
        target_urls = spider.discover_pdfs(keywords)

    if not target_urls:
        logger.warning("⚠️ Không tìm thấy URL PDF nào để xử lý. Tiến trình dừng lại.")
        return

    logger.info(f"🎯 Tổng số liên kết PDF được đưa vào Pipeline: {len(target_urls)}")

    try:
        # 4. Giai đoạn 2: Xử lý Pipeline (LocalScraperPipeline)
        pipeline = LocalScraperPipeline()

        # Đẩy danh sách URL vào vòng lặp của Pipeline.
        # Cơ chế check log MongoDB (Idempotency) sẽ tự động bỏ qua các URL đã cào trước đó.
        results = pipeline.run(target_urls)
        logger.info(f"✨ Quá trình thực thi hoàn tất: {results}")

    except KeyboardInterrupt:
        logger.warning("\n🛑 Người dùng đã hủy tiến trình bằng bàn phím (Ctrl+C).")
        sys.exit(0)
    except Exception as e:
        logger.critical(f"💥 Đã xảy ra lỗi nghiêm trọng không thể phục hồi: {e}", exc_info=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
