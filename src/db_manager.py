import logging
import os
import time
from typing import Any, Dict, Optional

import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Quản lý kết nối MongoDB theo cơ chế Lazy Creation.
    Tự động chuẩn bị database 'herbal_db' và 2 collections:
      - 'herbs_raw': Chứa dữ liệu y khoa/dược liệu đã bóc tách.
      - 'crawled_logs': Lưu lịch sử cào dữ liệu với Unique Index trên 'url'.
    """

    def __init__(self, mongo_uri: Optional[str] = None, db_name: str = "herbal_db"):
        self.mongo_uri = mongo_uri or os.getenv(
            "MONGO_URI", "mongodb://localhost:27017/"
        )
        self.db_name = db_name

        logger.info(f"Đang kết nối tới MongoDB tại: {self._mask_uri(self.mongo_uri)}")
        self.client: MongoClient = MongoClient(self.mongo_uri)
        self.db: Database = self.client[self.db_name]

        # Khởi tạo tham chiếu Collections
        self.herbs_raw: Collection = self.db["herbs_raw"]
        self.crawled_logs: Collection = self.db["crawled_logs"]

        # Thiết lập Unique Index cho trường 'url' trong 'crawled_logs'
        self._ensure_indexes()

    def _mask_uri(self, uri: str) -> str:
        """Che mật khẩu trong chuỗi kết nối MongoDB nếu có."""
        if "@" in uri:
            prefix = uri.split("@")[0]
            suffix = uri.split("@")[1]
            if ":" in prefix:
                scheme_user = prefix.rsplit(":", 1)[0]
                return f"{scheme_user}:****@{suffix}"
        return uri

    def _ensure_indexes(self) -> None:
        """Tạo unique index cho trường 'url' trong crawled_logs (Idempotent operation)."""
        try:
            self.crawled_logs.create_index(
                [("url", pymongo.ASCENDING)],
                unique=True,
                name="unique_crawled_url",
            )
            logger.info("✅ Đã kiểm tra/khởi tạo Unique Index trên crawled_logs['url'].")
        except Exception as e:
            logger.warning(
                f"⚠️ Lưu ý khi tạo index cho crawled_logs (DB có thể khởi tạo muộn): {e}"
            )

    def is_url_crawled(self, url: str) -> bool:
        """
        Kiểm tra xem URL đã được cào trước đó chưa (Idempotency).
        Chỉ bỏ qua nếu URL đã cào thành công ('status': 'success').
        Nếu trước đó 'failed', cho phép cào lại.
        """
        record = self.crawled_logs.find_one({"url": url})
        if record and record.get("status") == "success":
            return True
        return False

    def insert_herb_data(self, data: Dict[str, Any], source_url: str) -> Any:
        """Lưu bản ghi dược liệu vào collection herbs_raw."""
        document = {
            **data,
            "source_url": source_url,
            "crawled_at": time.time(),
        }
        result = self.herbs_raw.insert_one(document)
        logger.info(f"🌿 Đã lưu dữ liệu dược liệu vào herbs_raw (ID: {result.inserted_id}).")
        return result.inserted_id

    def log_crawl(
        self,
        url: str,
        status: str,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Ghi nhận hoặc cập nhật trạng thái cào URL vào crawled_logs.
        Sử dụng upsert để đảm bảo tính Idempotency.
        """
        log_entry = {
            "url": url,
            "status": status,
            "updated_at": time.time(),
        }
        if error_message:
            log_entry["error_message"] = error_message
        if metadata:
            log_entry["metadata"] = metadata

        self.crawled_logs.update_one(
            {"url": url},
            {"$set": log_entry, "$setOnInsert": {"created_at": time.time()}},
            upsert=True,
        )
        logger.info(f"📝 Đã cập nhật log cào: [{status.upper()}] - {url}")

    def close(self) -> None:
        """Đóng kết nối MongoDB."""
        self.client.close()
        logger.info("Đã đóng kết nối MongoDB.")
