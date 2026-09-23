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
    Handles downloading PDF documents to temporary directories and
    extracting text from herbal research papers.
    """

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        try:
            self.ua = UserAgent()
        except Exception:
            self.ua = None

    def get_random_headers(self) -> dict:
        """Generate HTTP headers with randomized User-Agent for Anti-Bot protection."""
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
        Download a PDF file from a URL to local disk (temporary directory).
        Returns the absolute path to the temporary file.
        """
        headers = self.get_random_headers()
        logger.info(f"Downloading PDF from {url}...")

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

            logger.info(f"Successfully downloaded PDF to temporary file: {temp_path}")
            return temp_path

        except Exception as e:
            # If an error occurs during download, clean up temporary file immediately
            if os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    pass
            logger.error(f"❌ Error downloading PDF from {url}: {e}")
            raise

    def extract_text(self, pdf_path: str, max_pages: int = 15) -> str:
        """
        Extract text from the PDF file using pdfplumber.
        Limits the number of pages processed to optimize runtime and LLM context size.
        """
        if not os.path.exists(pdf_path):
            raise FileNotFoundError(f"PDF file not found at: {pdf_path}")

        extracted_pages = []
        logger.info(f"Reading PDF content from {pdf_path}...")

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
            raise ValueError("Failed to extract valid text from the PDF file!")

        logger.info(
            f"Successfully extracted {len(extracted_pages)}/{total_pages} pages ({len(cleaned_text)} characters)."
        )
        return cleaned_text

    def _clean_text(self, text: str) -> str:
        """Clean excessive whitespaces and control characters."""
        # Replace consecutive whitespace and blank lines
        cleaned = re.sub(r"\r\n|\r", "\n", text)
        cleaned = re.sub(r"[ \t]+", " ", cleaned)
        cleaned = re.sub(r"\n{3,}", "\n\n", cleaned)
        return cleaned.strip()
