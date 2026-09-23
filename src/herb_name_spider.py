import json
import logging
import os
import re
from typing import Dict, List, Optional, Set, Tuple
from urllib.parse import quote, unquote, urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from fake_useragent import UserAgent

logger = logging.getLogger(__name__)


class HerbNameSpider:
    """
    Phase 0: Automatically collects and supplements the Master List of herbal plants
    from directory/source pages (e.g. Wikipedia medicinal plants category)
    into vietnamese_herbs.json, supporting pagination, subcategory recursion,
    and target limits to scale up to 5,000+ plant species.
    """

    DEFAULT_SOURCES = [
        # 1. Primary Vietnamese Medicinal Categories
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_thu%E1%BB%91c",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Th%E1%BB%B1c_v%E1%BA%ADt_%C4%91%C6%B0%E1%BB%A3c_s%E1%BB%AD_d%E1%BB%A5ng_trong_%C4%90%C3%B4ng_y",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_thu%E1%BB%91c_ch%C3%A2u_%C3%81",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_thu%E1%BB%91c_d%C3%A2n_gian",
        
        # 2. Vietnamese Native Flora, Trees & Endemic Plants
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Th%E1%BB%B1c_v%E1%BA%ADt_Vi%E1%BB%87t_Nam",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Th%E1%BB%B1c_v%E1%BA%ADt_%C4%91%E1%BA%B7c_h%E1%BB%AFu_Vi%E1%BB%87t_Nam",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_Vi%E1%BB%87t_Nam",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_r%E1%BB%ABng_Vi%E1%BB%87t_Nam",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Th%E1%BB%B1c_v%E1%BA%ADt_%C4%90%C3%B4ng_D%C6%B0%C6%A1ng",
        
        # 3. Botanical Taxa & Bioactive Families
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Chi_th%E1%BB%B1c_v%E1%BA%ADt",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:H%E1%BB%8D_C%C3%BAc",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:H%E1%BB%8D_%C4%90%E1%BA%ADu",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:H%E1%BB%8D_Hoa_t%C3%A1n",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:H%E1%BB%8D_C%C3%A0",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:H%E1%BB%8D_G%E1%BB%ABng",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:H%E1%BB%8D_Lan",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_%C4%91%E1%BB%99c",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_gia_v%E1%BB%8B",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_%C4%83n_qu%E1%BA%A3",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:C%C3%A2y_b%E1%BB%A5i",
        "https://vi.wikipedia.org/wiki/Th%E1%BB%83_lo%E1%BA%A1i:Th%E1%BB%B1c_v%E1%BA%ADt_c%C3%B3_hoa",
    ]

    def __init__(self, timeout: int = 15):
        self.timeout = timeout
        try:
            self.ua = UserAgent()
        except Exception:
            self.ua = None

    def _get_headers(self) -> Dict[str, str]:
        user_agent = (
            self.ua.random
            if self.ua
            else "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        return {
            "User-Agent": user_agent,
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "vi-VN,vi;q=0.9,en-US;q=0.8,en;q=0.7",
        }

    def parse_herb_name_text(self, text: str) -> Optional[Dict[str, str]]:
        """
        Extract local name and scientific name from a text string.
        Examples:
          - "Ba kích (Morinda officinalis)" -> name: "Ba kích", scientific_name: "Morinda officinalis"
          - "Sâm Ngọc Linh" -> name: "Sâm Ngọc Linh", scientific_name: ""
        """
        cleaned = text.strip()
        if not cleaned or len(cleaned) < 2:
            return None

        # Remove non-herb title prefixes if present
        cleaned = re.sub(
            r"^(Thể loại|Bản mẫu|Danh sách):", "", cleaned, flags=re.IGNORECASE
        ).strip()

        # Extract scientific name inside parentheses (...)
        match = re.search(r"^(.*?)\s*\(([^)]+)\)$", cleaned)
        if match:
            local_name = match.group(1).strip()
            scientific = match.group(2).strip()
            return {"name": local_name, "scientific_name": scientific}

        return {"name": cleaned, "scientific_name": ""}

    def _crawl_wikipedia_category_api(
        self, url: str
    ) -> Tuple[List[Dict[str, str]], Optional[str]]:
        """
        Fetch members of a Wikipedia category using the official MediaWiki API.
        Retrieves 500 members per call, extracts pages and enqueues relevant subcategories.
        """
        results: List[Dict[str, str]] = []
        next_page_url: Optional[str] = None
        self._last_discovered_subcats = []

        try:
            parsed_url = urlparse(url)
            if "api.php" in parsed_url.path:
                api_url = url
            else:
                cat_raw = url.split("/wiki/")[-1].split("?")[0]
                cat_title = unquote(cat_raw).replace("_", " ")
                api_url = f"https://vi.wikipedia.org/w/api.php?action=query&list=categorymembers&cmtitle={quote(cat_title)}&cmlimit=500&format=json"

            logger.info(f"🕷️ [HerbNameSpider API] Querying Wikipedia API: {api_url}")
            resp = requests.get(
                api_url, headers=self._get_headers(), timeout=self.timeout
            )
            if resp.status_code == 200:
                data = resp.json()
                members = data.get("query", {}).get("categorymembers", [])
                for m in members:
                    ns = m.get("ns")
                    title = m.get("title", "").strip()
                    if ns == 0 and title:
                        parsed = self.parse_herb_name_text(title)
                        if parsed:
                            results.append(parsed)
                    elif ns == 14 and title:
                        title_lower = title.lower()
                        # Botanical filter to stay within plant/herb domain
                        if any(
                            kw in title_lower
                            for kw in [
                                "cây", "thực vật", "thuốc", "dược", "hoa",
                                "chi", "họ", "loài", "gỗ", "cỏ", "rừng", "đông y"
                            ]
                        ):
                            sub_url = f"https://vi.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                            self._last_discovered_subcats.append(sub_url)

                # Pagination via cmcontinue
                cmcontinue = data.get("continue", {}).get("cmcontinue")
                if cmcontinue:
                    if "cmcontinue=" in api_url:
                        next_page_url = re.sub(
                            r"cmcontinue=[^&]+",
                            f"cmcontinue={quote(cmcontinue)}",
                            api_url,
                        )
                    else:
                        sep = "&" if "?" in api_url else "?"
                        next_page_url = f"{api_url}{sep}cmcontinue={quote(cmcontinue)}"

                logger.info(
                    f"🌿 [HerbNameSpider API] Collected {len(results)} items & "
                    f"{len(self._last_discovered_subcats)} subcategories."
                )
                return results, next_page_url

        except Exception as e:
            logger.warning(
                f"⚠️ MediaWiki API request error ({e}). Falling back to HTML parsing."
            )

        return results, next_page_url

    def crawl_names_from_url(
        self, url: str
    ) -> Tuple[List[Dict[str, str]], Optional[str]]:
        """
        Crawl a list of herbal plant names from a specified web page using MediaWiki API or BeautifulSoup.
        Returns a tuple of: (herb_list, next_page_url_if_any)
        """
        logger.info(f"🕷️ [HerbNameSpider] Crawling herb name directory from: {url}")
        results: List[Dict[str, str]] = []
        next_page_url: Optional[str] = None
        self._last_discovered_subcats = []

        # 1. Wikipedia Category API Optimization
        if "vi.wikipedia.org" in url and (
            "Thể_loại:" in url
            or "Th%E1%BB%83_lo%E1%BA%A1i:" in url
            or "api.php" in url
        ):
            api_results, next_api_url = self._crawl_wikipedia_category_api(url)
            if api_results or next_api_url:
                return api_results, next_api_url

        # 2. BeautifulSoup HTML Parsing (Generic pages, tables, Wikipedia HTML, or mock responses)
        try:
            response = requests.get(
                url, headers=self._get_headers(), timeout=self.timeout
            )
            if response.status_code != 200:
                logger.warning(
                    f"⚠️ Failed to access {url} (Response status code: {response.status_code})"
                )
                return results, None

            soup = BeautifulSoup(response.text, "html.parser")

            # 2.1. Look for next page pagination link (Wikipedia Pagination)
            for a in soup.select("#mw-pages a, .mw-category-generated a"):
                text = a.get_text().strip().lower()
                href = a.get("href")
                if href and (
                    "trang sau" in text or "trang kế" in text or "next page" in text
                ):
                    next_page_url = urljoin(url, href)
                    break

            # 2.2. Extract subcategories from Wikipedia Category
            for a in soup.select(
                "#mw-subcategories a, .CategoryTreeItem a, .CategoryTreeLabel"
            ):
                href = a.get("href")
                if href and (
                    "/wiki/Th%E1%BB%83_lo%E1%BA%A1i:" in href
                    or "/wiki/Thể_loại:" in href
                ):
                    full_sub_url = urljoin(url, href)
                    title_lower = a.get_text().strip().lower()
                    if any(
                        kw in title_lower
                        for kw in [
                            "cây", "thực vật", "thuốc", "dược", "hoa",
                            "chi", "họ", "loài", "gỗ", "cỏ", "rừng", "đông y"
                        ]
                    ):
                        self._last_discovered_subcats.append(full_sub_url)

            # 2.3. Case: Wikipedia Category (contains #mw-pages list)
            category_links = soup.select("#mw-pages li a, .mw-category-group li a")
            if category_links:
                for link in category_links:
                    link_text = link.get_text().strip()
                    parsed = self.parse_herb_name_text(link_text)
                    if parsed:
                        results.append(parsed)

            # 2.4. Case: Structured table (Table wikitable or similar)
            table_rows = soup.select("table.wikitable tr, table tr")
            for row in table_rows:
                cells = row.select("td")
                if len(cells) >= 2:
                    name_cell = cells[0].get_text().strip()
                    sci_cell = cells[1].get_text().strip()
                    if name_cell and sci_cell:
                        results.append({
                            "name": name_cell,
                            "scientific_name": sci_cell,
                        })

        except Exception as e:
            logger.warning(
                f"⚠️ Exception occurred while crawling herb names from {url}: {e}"
            )

        logger.info(
            f"🌿 [HerbNameSpider] Collected {len(results)} items from current page."
        )
        return results, next_page_url

    def load_master_list(self, json_path: str) -> List[Dict[str, str]]:
        """Read existing herb entities from the JSON master file."""
        if not os.path.exists(json_path):
            return []
        try:
            with open(json_path, "r", encoding="utf-8") as f:
                data = json.load(f)
                if isinstance(data, list):
                    return data
        except Exception as e:
            logger.warning(f"⚠️ Error reading master list '{json_path}': {e}")
        return []

    def save_master_list(self, json_path: str, data: List[Dict[str, str]]) -> None:
        """Save herb entities list into the JSON master file."""
        try:
            with open(json_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            logger.info(f"💾 Saved {len(data)} herb species into '{json_path}'.")
        except Exception as e:
            logger.error(f"❌ Error writing file '{json_path}': {e}")

    def update_master_list(
        self,
        json_path: str = "vietnamese_herbs.json",
        source_url: Optional[str] = None,
        limit: Optional[int] = None,
    ) -> int:
        """
        Execute Phase 0: Crawl plant directory from the web, filter out existing names,
        and append new herbs to the JSON master list until `limit` is reached.

        Supports multi-category crawl, subcategory recursion, and Wikipedia API acceleration
        to easily scale up to 5,000+ plant species.

        Args:
            json_path: Path to the JSON Master List file.
            source_url: Starting URL (defaults to DEFAULT_SOURCES).
            limit: Maximum number of NEW herbs to discover (None or <=0: unlimited).

        Returns:
            Count of new herb species added to the file.
        """
        current_herbs = self.load_master_list(json_path)

        # Set of existing local and scientific names for O(1) deduplication
        existing_names: Set[str] = {
            item.get("name", "").strip().lower()
            for item in current_herbs
            if item.get("name")
        }
        existing_scientific: Set[str] = {
            item.get("scientific_name", "").strip().lower()
            for item in current_herbs
            if item.get("scientific_name")
        }

        urls_queue = [source_url] if source_url else list(self.DEFAULT_SOURCES)
        visited_urls: Set[str] = set()
        new_items: List[Dict[str, str]] = []

        max_new = limit if (limit and limit > 0) else None
        if max_new:
            logger.info(
                f"🎯 [Phase 0 Target] Discovery target: up to {max_new} new herb species."
            )

        while urls_queue:
            target_url = urls_queue.pop(0)
            if target_url in visited_urls:
                continue
            visited_urls.add(target_url)

            crawled_list, next_page = self.crawl_names_from_url(target_url)

            for item in crawled_list:
                name_clean = item.get("name", "").strip()
                sci_clean = item.get("scientific_name", "").strip()
                name_lower = name_clean.lower()
                sci_lower = sci_clean.lower()

                # Deduplication check
                is_name_exist = name_lower in existing_names
                is_sci_exist = bool(sci_lower and sci_lower in existing_scientific)

                if not is_name_exist and not is_sci_exist and name_clean:
                    new_items.append({"name": name_clean, "scientific_name": sci_clean})
                    existing_names.add(name_lower)
                    if sci_lower:
                        existing_scientific.add(sci_lower)

                    # Check if reached target limit
                    if max_new and len(new_items) >= max_new:
                        logger.info(
                            f"🏁 [Phase 0 Limit Reached] Reached target of {max_new} new herb species."
                        )
                        break

            if max_new and len(new_items) >= max_new:
                break

            # If there is a next page, prioritize it at the front of queue to finish current category
            if next_page and next_page not in visited_urls and next_page not in urls_queue:
                logger.info(f"➡️ [Phase 0 Pagination] Next page found: {next_page}")
                urls_queue.insert(0, next_page)

            # Enqueue newly discovered subcategories at the back of queue
            for sub_url in getattr(self, "_last_discovered_subcats", []):
                if sub_url not in visited_urls and sub_url not in urls_queue:
                    urls_queue.append(sub_url)

        if new_items:
            current_herbs.extend(new_items)
            self.save_master_list(json_path, current_herbs)
            logger.info(
                f"✨ [HerbNameSpider] Successfully appended {len(new_items)} new herbs to '{json_path}' "
                f"(Total now: {len(current_herbs)} herbs)."
            )
        else:
            logger.info(
                f"ℹ️ [HerbNameSpider] No new herb species found to add to '{json_path}'."
            )

        return len(new_items)
