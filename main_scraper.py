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

# Cấu hình logging chuẩn mực
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%Y-%m-%d %H:%M:%S",
)
logger = logging.getLogger("MainScraper")

# Danh sách URL mẫu (Dùng để kiểm thử nhanh hệ thống)
SAMPLE_RESEARCH_URLS = [
    "https://raw.githubusercontent.com/LeoTkiet/Herbal-Data/main/samples/sample_herb_paper.pdf",
]


def parse_arguments() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Herbal Data Scraping Agent - Thu thập & Bóc tách dược liệu Việt Nam từ PDF"
    )
    parser.add_argument(
        "--urls",
        nargs="+",
        help="Danh sách các URL PDF cần cào (cách nhau bởi dấu cách)",
        default=None,
    )
    parser.add_argument(
        "--file",
        type=str,
        help="Đường dẫn file text chứa danh sách URL (mỗi dòng 1 URL)",
        default=None,
    )
    return parser.parse_args()


def load_urls(args: argparse.Namespace) -> List[str]:
    """Thu thập danh sách URL từ tham số dòng lệnh hoặc file."""
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

    if not urls:
        logger.warning(
            "⚠️ Không nhận được URL từ tham số dòng lệnh. Hệ thống sẽ sử dụng danh sách mẫu để chạy thử nghiệm."
        )
        urls = SAMPLE_RESEARCH_URLS

    return urls


def main():
    # 1. Nạp biến môi trường từ .env
    load_dotenv()

    # 2. Xử lý tham số dòng lệnh
    args = parse_arguments()
    target_urls = load_urls(args)

    logger.info("🌿 Khởi tạo Herbal Data Scraping Agent...")

    try:
        # 3. Khởi tạo Pipeline
        pipeline = HerbalScrapingPipeline()

        # 4. Thực thi cào dữ liệu
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
