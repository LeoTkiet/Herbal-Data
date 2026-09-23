import logging
import random
import re
import time
import warnings
from typing import List, Optional, Set
from urllib.parse import quote_plus, urljoin, urlparse

import requests
from bs4 import BeautifulSoup

# Ignore RuntimeWarning when duckduckgo_search prompts migrating to ddgs
warnings.filterwarnings("ignore", category=RuntimeWarning)

try:
    from ddgs import DDGS
except ImportError:
    try:
        from duckduckgo_search import DDGS
    except ImportError:
        raise ImportError(
            "ddgs library not found. Please install it via: pip install ddgs"
        )

logger = logging.getLogger(__name__)

class PDFSpider:
    """
    Automated Discovery Spider:
    Automatically searches for PDF research paper links by keyword
    via the DuckDuckGo Search API (DDGS), integrated with deep link extraction
    and Open-Access academic repository fallbacks.
    """

    def __init__(
        self,
        min_delay: float = 7.0,
        max_delay: float = 15.0,
        max_results_per_keyword: int = 5,
    ):
        self.min_delay = min_delay
        self.max_delay = max_delay
        self.max_results_per_keyword = max_results_per_keyword

    def _is_valid_pdf_url(self, url: str) -> bool:
        """Check if the URL structure points to a PDF document."""
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
        """Extract downloadable PDF links embedded inside an HTML article page."""
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
        Search for open scientific research PDFs (OpenAlex Open-Access)
        directly for the provided keyword.
        """
        academic_urls: Set[str] = set()
        query = keyword.strip()

        logger.info(
            f"   ↳ 📚 Querying open medical repository (OpenAlex) for '{query}'..."
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
                        logger.info(f"   ↳ 📄 Found research paper PDF: {pdf_url}")

                    primary = work.get("primary_location", {}) or {}
                    p_url = primary.get("pdf_url")
                    if p_url and self._is_valid_pdf_url(p_url):
                        academic_urls.add(p_url.strip())
                        logger.info(f"   ↳ 📄 Found research paper PDF: {p_url}")

                    if len(academic_urls) >= limit:
                        break
        except Exception as e:
            logger.warning(f"⚠️ Error querying academic repository: {e}")

        return academic_urls

    def generate_search_query(self, keyword: str) -> str:
        """Generate DDGS query matching requirement: {herb_name} nghiên cứu filetype:pdf"""
        clean_name = keyword.strip()
        if not clean_name:
            return ""
        name_only = re.sub(r"\bfiletype:pdf\b", "", clean_name, flags=re.IGNORECASE).strip()
        name_only = re.sub(r"\bnghiên cứu\b", "", name_only, flags=re.IGNORECASE).strip()
        return f"{name_only} nghiên cứu filetype:pdf".strip()

    def search_keyword(
        self, keyword: str, max_results: Optional[int] = None
    ) -> Set[str]:
        """
        Search for PDF links for a single keyword:
          1. Use DuckDuckGo Search (DDGS) with query syntax 'filetype:pdf'.
          2. Scan direct PDF links and attached links inside result pages.
          3. Automatically query open medical repository fallback if DDGS yields web blogs only.
        """
        clean_name = keyword.strip()
        if not clean_name:
            return set()

        # Standard search query format: "nghiên cứu" + herb name + "filetype:pdf"
        query = self.generate_search_query(clean_name)

        limit = max_results or self.max_results_per_keyword
        logger.info(
            f"🔍 [Spider DDGS] Searching: '{query}' (Limit: {limit} results)..."
        )

        found_urls: Set[str] = set()

        # 1. Search via DuckDuckGo Search (DDGS)
        try:
            warnings.filterwarnings("ignore")
            with DDGS() as ddgs:
                search_results = list(ddgs.text(query, max_results=limit * 4))

                # Check direct URLs
                for item in search_results:
                    href = item.get("href")
                    if href and self._is_valid_pdf_url(href):
                        found_urls.add(href.strip())
                        logger.info(f"   ↳ 📄 [DDGS PDF]: {href}")
                        if len(found_urls) >= limit:
                            break

                # If no direct PDF files yet, inspect embedded article page links
                if not found_urls and search_results:
                    logger.info(
                        "   ↳ Checking article result pages for attached PDF links..."
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
            logger.warning(f"⚠️ [Spider] DDGS search error for query '{query}': {e}")

        # 2. Open-access repository fallback (OpenAlex) if DuckDuckGo yields insufficient PDFs
        if not found_urls or len(found_urls) < limit:
            needed = limit - len(found_urls)
            academic_pdfs = self._search_open_access_repository(clean_name, limit=needed)
            found_urls.update(academic_pdfs)

        logger.info(f"✅ Collected {len(found_urls)} PDF URLs for '{clean_name}'.")
        return found_urls

    def discover_pdfs(
        self,
        keywords: List[str],
        max_results_per_keyword: Optional[int] = None,
    ) -> List[str]:
        """
        Iterate through keyword list, collecting deduplicated PDF URLs (Set).
        Applies random sleep between searches to prevent rate limits.
        """
        logger.info(f"🕸️ [Spider] Starting automated discovery for {len(keywords)} keywords...")
        all_unique_urls: Set[str] = set()

        for idx, kw in enumerate(keywords, 1):
            if idx > 1:
                delay = random.uniform(self.min_delay, self.max_delay)
                logger.info(
                    f"⏳ [Spider Rate Limit Prevention] Sleeping {delay:.2f}s before next keyword..."
                )
                time.sleep(delay)

            kw_urls = self.search_keyword(kw, max_results=max_results_per_keyword)
            all_unique_urls.update(kw_urls)

        result_list = list(all_unique_urls)
        logger.info(
            f"🎉 [Spider Finished] Collected total of {len(result_list)} unique PDF links!"
        )
        return result_list
