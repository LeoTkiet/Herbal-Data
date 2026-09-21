import logging
import random
import time
import warnings
from typing import List, Optional, Set
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Bỏ qua RuntimeWarning khi duckduckgo_search nhắc chuyển sang ddgs
warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise ImportError(
            "Không tìm thấy thư viện ddgs. Vui lòng cài đặt: pip install ddgs"
        )

logger = logging.getLogger(__name__)

class PDFSpider:
    """
    Automated Discovery Spider:
    Tự động tìm kiếm các liên kết tài liệu nghiên cứu dạng PDF theo từ khóa
    thông qua DuckDuckGo Search API (DDGS), kết hợp bóc tách liên kết sâu
    và truy xuất kho nghiên cứu mở Open-Access.
    """

    def __init__(
        self,
        min_delay: float = 2.5,
        max_delay: float = 5.5,
        max_results_per_keyword: int = 5,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_results_per_keyword = max_results_per_keyword

    def _is_valid_pdf_url(self, url: str) -> bool:
        """Kiểm tra xem URL có cấu trúc trỏ tới tài liệu PDF hay không."""
        if not url or not url.startswith(("http://", "https://")):
            return False
        parsed = urlparse(url)
        path = parsed.path.lower()
        query = parsed.query.lower()
        return (
            path.endswith(".pdf")
            or ".pdf?" in url.lower()
            or "pdf=render" in query
            or "download=pdf" in query
            or "/article/download/" in path
            or "/download/pdf" in path
        )

    def _extract_pdfs_from_page(self, page_url: str, timeout: int = 4) -> Set[str]:
        """Trích xuất các liên kết tải file PDF nằm bên trong một trang bài viết HTML."""
        extracted: Set[str] = set()
        try:
            headers = {
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/122.0.0.0 Safari/537.36"
            }
            resp = requests.get(page_url, headers=headers, timeout=timeout)
            if resp.status_code == 200:
                content_type = resp.headers.get("content-type", "").lower()
                if "application/pdf" in content_type:
                    extracted.add(page_url)
                    return extracted

                soup = BeautifulSoup(resp.text, "html.parser")
                for a in soup.find_all("a", href=True):
                    href = a["href"].strip()
                    if href.lower().endswith(".pdf") or ".pdf?" in href.lower():
                        full_pdf_url = urljoin(page_url, href)
                        extracted.add(full_pdf_url)
        except Exception:
            pass
        return extracted

    def _search_open_access_repository(
        self, keyword: str, limit: int = 5
    ) -> Set[str]:
        """
        Tìm kiếm các tài liệu bài báo khoa học PDF mở (OpenAlex Open-Access)
        trực tiếp theo từ khóa người dùng cung cấp.
        """
        academic_urls: Set[str] = set()
        query = keyword.strip()

        logger.info(
            f"   ↳ 📚 Truy vấn kho tài liệu y học mở (OpenAlex) cho '{query}'..."
        )
        try:
            api_url = f"https://api.openalex.org/works?search={quote_plus(query)}&filter=has_fulltext:true"
            resp = requests.get(
                api_url,
                headers={"User-Agent": "HerbalDataScraper/1.0 (academic-research)"},
                timeout=10,
            )
            if resp.status_code == 200:
                data = resp.json()
                for work in data.get("results", []):
                    oa = work.get("open_access", {})
                    pdf_url = oa.get("oa_url")
                    if pdf_url and self._is_valid_pdf_url(pdf_url):
                        academic_urls.add(pdf_url.strip())
                        logger.info(f"   ↳ 📄 Tìm thấy bài báo PDF: {pdf_url}")

                    primary = work.get("primary_location", {}) or {}
                    p_url = primary.get("pdf_url")
                    if p_url and self._is_valid_pdf_url(p_url):
                        academic_urls.add(p_url.strip())
                        logger.info(f"   ↳ 📄 Tìm thấy bài báo PDF: {p_url}")

                    if len(academic_urls) >= limit:
                        break
        except Exception as e:
            logger.warning(f"⚠️ Lỗi truy vấn kho tài liệu học thuật: {e}")

        return academic_urls

    def search_keyword(
        self, keyword: str, max_results: Optional[int] = None
    ) -> Set[str]:
        """
        Tìm kiếm các liên kết PDF cho một từ khóa đơn lẻ:
          1. Sử dụng DuckDuckGo Search (DDGS) với cú pháp 'filetype:pdf'.
          2. Quét liên kết PDF trực tiếp và liên kết đính kèm trong các bài báo.
          3. Tự động kết nối kho tài liệu nghiên cứu y khoa mở nếu DDGS chỉ có web blog.
        """
        clean_kw = keyword.strip()
        if not clean_kw:
            return set()

        query = (
            clean_kw
            if "filetype:pdf" in clean_kw.lower()
            else f"{clean_kw} filetype:pdf"
        )
        limit = max_results or self.max_results_per_keyword
        logger.info(
            f"🔍 [Spider] Đang tìm kiếm: '{query}' (Giới hạn: {limit} kết quả)..."
        )

        found_urls: Set[str] = set()

        # 1. Tìm kiếm qua DuckDuckGo Search (DDGS)
        try:
            warnings.filterwarnings("ignore")
            with DDGS() as ddgs:
                search_results = list(ddgs.text(query, max_results=limit * 4))

                # Kiểm tra các URL trực tiếp
                for item in search_results:
                    href = item.get("href")
                    if href and self._is_valid_pdf_url(href):
                        found_urls.add(href.strip())
                        logger.info(f"   ↳ 📄 [DDGS PDF]: {href}")
                        if len(found_urls) >= limit:
                            break

                # Nếu chưa có file PDF trực tiếp, thử quét liên kết đính kèm trong các trang kết quả
                if not found_urls and search_results:
                    logger.info(
                        "   ↳ Đang kiểm tra các trang bài báo kết quả để tìm tài liệu PDF đính kèm..."
                    )
                    for item in search_results[:3]:
                        href = item.get("href")
                        if href:
                            page_pdfs = self._extract_pdfs_from_page(href)
                            for p in page_pdfs:
                                found_urls.add(p)
                                logger.info(f"   ↳ 📄 [Deep Page PDF]: {p}")
                                if len(found_urls) >= limit:
                                    break
                        if len(found_urls) >= limit:
                            break

        except Exception as e:
            logger.warning(f"⚠️ [Spider] Lỗi tìm kiếm DDGS cho từ khóa '{query}': {e}")

        # 2. Bổ trợ kho tài liệu mở (OpenAlex) nếu DuckDuckGo không có link PDF
        if not found_urls or len(found_urls) < limit:
            needed = limit - len(found_urls)
            academic_pdfs = self._search_open_access_repository(clean_kw, limit=needed)
            found_urls.update(academic_pdfs)

        logger.info(f"✅ Đã thu thập được {len(found_urls)} URL PDF từ '{clean_kw}'.")
        return found_urls

    def discover_pdfs(
        self,
        keywords: List[str],
        max_results_per_keyword: Optional[int] = None,
    ) -> List[str]:
        """
        Duyệt qua danh sách từ khóa, thu thập danh sách URL (.pdf) không trùng lặp (Set).
        Áp dụng random sleep giữa các lần tìm kiếm để chống bị rate limit.
        """
        logger.info(f"🕸️ [Spider] Bắt đầu quét tự động cho {len(keywords)} từ khóa...")
        all_unique_urls: Set[str] = set()

        for idx, kw in enumerate(keywords, 1):
            if idx > 1:
                delay = random.uniform(self.min_delay, self.max_delay)
                logger.info(
                    f"⏳ [Spider Rate Limit Prevention] Nghỉ {delay:.2f}s trước từ khóa tiếp theo..."
                )
                time.sleep(delay)

            kw_urls = self.search_keyword(kw, max_results=max_results_per_keyword)
            all_unique_urls.update(kw_urls)

        result_list = list(all_unique_urls)
        logger.info(
            f"🎉 [Spider Hoàn tất] Tổng cộng thu thập được {len(result_list)} liên kết PDF độc nhất!"
        )
        return result_list
