import logging
import os
import re
import tempfile
from typing import Optional

import pdfplumber
import requests
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


class PDFProcessor:
    """
    Chịu trách nhiệm tải file PDF về thư mục tạm và trích xuất text
    từ các trang tài liệu nghiên cứu dược liệu.
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        try:
            self.ua = UserAgent()
        except Exception:
            self.ua = None

    def get_random_headers(self) -> dict:
        """Sinh HTTP Header với User-Agent ngẫu nhiên nhằm phòng chống Anti-Bot."""
        user_agent = (
            self.ua.random
            if self.ua
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
        )
        return {
            "User-Agent": user_agent,
            "Accept": "application/pdf,application/octet-stream,*/*",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def download_pdf(self, url: str, destination_dir: Optional[str] = None) -> str:
        """
        Tải file PDF từ URL về ổ cứng local (thư mục tạm).
        Trả về đường dẫn tuyệt đối của file tạm.
        """
        headers = self.get_random_headers()
        logger.info(f"Đang tải PDF từ {url}...")

        target_dir = destination_dir or tempfile.gettempdir()
        temp_file = tempfile.NamedTemporaryFile(
            delete=False, suffix=".pdf", dir=target_dir
        )
        temp_path = os.path.abspath(temp_file.name)
        temp_file.close()

        try:
            response = requests.get(
                url, headers=headers, timeout=self.timeout, stream=True
            )
            response.raise_for_status()

            with open(temp_path, "wb") as f:
                for chunk in response.iter_content(chunk_size=8192):
                    if chunk:
                        f.write(chunk)

            logger.info(f"Đã tải thành công PDF về file tạm: {temp_path}")
            return temp_path

        except Exception as e:
            # Nếu xảy ra lỗi trong lúc tải, dọn dẹp file tạm ngay lập tức
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            logger.error(f"❌ Lỗi khi tải PDF từ {url}: {e}")
            raise

    def extract_text(self, pdf_path: str, max_pages: int = 15) -> str:
        """
        Trích xuất toàn bộ text từ file PDF bằng pdfplumber.
        Có giới hạn số trang xử lý để tối ưu thời gian và context của LLM.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"Không tìm thấy file PDF tại: {pdf_path}")

        extracted_pages = []
        logger.info(f"Đang đọc nội dung PDF từ {pdf_path}...")

        with pdfplumber.open(pdf_path) as pdf:
            total_pages = len(pdf.pages)
            pages_to_read = min(total_pages, max_pages)

            for page_idx in range(pages_to_read):
                page = pdf.pages[page_idx]
                page_text = page.extract_text()
                if page_text and page_text.strip():
                    extracted_pages.append(page_text.strip())

        full_text = "\n\n".join(extracted_pages)
        cleaned_text = self._clean_text(full_text)

        if not cleaned_text:
            raise ValueError("Không thể trích xuất văn bản hợp lệ từ file PDF!")

        logger.info(
            f"Trích xuất thành công {len(extracted_pages)}/{total_pages} trang ({len(cleaned_text)} ký tự)."
        )
        return cleaned_text

    def _clean_text(self, text: str) -> str:
        """Làm sạch khoảng trắng thừa và ký tự điều khiển."""
        # Thay thế khoảng trắng và dòng trống liên tiếp
        cleaned = re.sub(r"\r\n|\r", "\n", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
