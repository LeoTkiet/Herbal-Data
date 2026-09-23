import logging
import os
import time
from typing import Any, Dict, List, Optional

import pymongo
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

logger = logging.getLogger(__name__)


class DatabaseManager:
    """
    Manages MongoDB connections using a Lazy Creation pattern.
    Automatically prepares the 'herbal_db' database and 3 collections:
      - 'herbs_raw': Contains extracted pharmaceutical/medical herbal data.
      - 'crawled_logs': Stores crawl history with a Unique Index on 'url'.
      - 'keyword_logs': Stores crawled keyword/scientific_name entities for O(1) deduplication.
    """

    def __init__(self, mongo_uri: Optional[str] = None, db_name: str = "herbal_db"):
        self.mongo_uri = mongo_uri or os.getenv(
            "MONGO_URI", "mongodb://localhost:27017/"
        )
        self.db_name = db_name

        logger.info(f"Connecting to MongoDB at: {self._mask_uri(self.mongo_uri)}")
        self.client: MongoClient = MongoClient(self.mongo_uri)
        self.db: Database = self.client[self.db_name]

        # Initialize collection references
        self.herbs_raw: Collection = self.db["herbs_raw"]
        self.crawled_logs: Collection = self.db["crawled_logs"]
        self.keyword_logs: Collection = self.db["keyword_logs"]

        # Ensure unique and indexing configurations
        self._ensure_indexes()

    def _mask_uri(self, uri: str) -> str:
        """Mask credentials in the MongoDB connection URI if present."""
        if "@" in uri:
            prefix = uri.split("@")[0]
            suffix = uri.split("@")[1]
            if ":" in prefix:
                scheme_user = prefix.rsplit(":", 1)[0]
                return f"{scheme_user}:****@{suffix}"
        return uri

    def _ensure_indexes(self) -> None:
        """Create unique indexes for crawled_logs, keyword_logs and lookup indexes for herbs_raw."""
        try:
            self.crawled_logs.create_index(
                [("url", pymongo.ASCENDING)],
                unique=True,
                name="unique_crawled_url",
            )
            self.keyword_logs.create_index(
                [("keyword", pymongo.ASCENDING)],
                unique=True,
                name="unique_logged_keyword",
            )
            self.keyword_logs.create_index(
                [("scientific_name", pymongo.ASCENDING)],
                name="idx_logged_scientific",
            )
            self.herbs_raw.create_index(
                [("queried_name", pymongo.ASCENDING)],
                name="idx_queried_herb_name",
            )
            self.herbs_raw.create_index(
                [("herb_name.scientific", pymongo.ASCENDING)],
                name="idx_scientific_name",
            )
            logger.info("✅ Verified/created Indexes on crawled_logs, keyword_logs, and herbs_raw.")
        except Exception as e:
            logger.warning(
                f"⚠️ Note during MongoDB index creation (DB may be lazily initialized): {e}"
            )

    def is_url_crawled(self, url: str) -> bool:
        """
        Check if the URL has already been crawled previously (Idempotency).
        Only skips if the URL was crawled successfully ('status': 'success').
        If marked 'failed' previously, allow re-crawling.
        """
        record = self.crawled_logs.find_one({"url": url})
        if record and record.get("status") == "success":
            return True
        return False

    def save_or_update_herb_data(
        self,
        data: Dict[str, Any],
        source_urls: List[str],
        queried_herb_name: Optional[str] = None,
    ) -> Any:
        """
        Save or update herbal information in the herbs_raw collection.
        Ensures No Row Duplication: a plant species is stored in exactly one document.
        Merges medical properties and source_urls array if the herb already exists in the database.
        """
        scientific_name = data.get("herb_name", {}).get("scientific")
        local_names = data.get("herb_name", {}).get("local", [])
        clean_queried = queried_herb_name.strip().lower() if queried_herb_name else None

        # Build filter query to find existing herb document in DB to prevent duplicates
        or_conditions = []
        if clean_queried:
            or_conditions.append({"queried_name": clean_queried})
        if scientific_name and scientific_name.strip() and scientific_name.lower() != "null":
            or_conditions.append({"herb_name.scientific": scientific_name.strip()})
        if local_names:
            or_conditions.append({"herb_name.local": {"$in": local_names}})

        existing = None
        if or_conditions:
            existing = self.herbs_raw.find_one({"$or": or_conditions})

        now = time.time()
        clean_sources = list(dict.fromkeys([u.strip() for u in source_urls if u and u.strip()]))

        if existing:
            # Merge data to prevent duplicate information
            existing_herb_name = existing.get("herb_name", {})
            existing_local = existing_herb_name.get("local", [])
            merged_local = list(dict.fromkeys(existing_local + local_names))

            merged_props = list(
                dict.fromkeys(
                    existing.get("medicinal_properties", []) + data.get("medicinal_properties", [])
                )
            )
            merged_compounds = list(
                dict.fromkeys(
                    existing.get("active_compounds", []) + data.get("active_compounds", [])
                )
            )
            merged_diseases = list(
                dict.fromkeys(
                    existing.get("curable_diseases", []) + data.get("curable_diseases", [])
                )
            )

            existing_sources = existing.get("source_urls", [])
            if not existing_sources and existing.get("source_url"):
                existing_sources = [existing.get("source_url")]
            merged_sources = list(dict.fromkeys(existing_sources + clean_sources))

            update_doc = {
                "$set": {
                    "herb_name.scientific": (
                        scientific_name
                        if (scientific_name and scientific_name.lower() != "null")
                        else existing_herb_name.get("scientific")
                    ),
                    "herb_name.local": merged_local,
                    "medicinal_properties": merged_props,
                    "active_compounds": merged_compounds,
                    "curable_diseases": merged_diseases,
                    "source_urls": merged_sources,
                    "updated_at": now,
                }
            }
            if clean_queried and not existing.get("queried_name"):
                update_doc["$set"]["queried_name"] = clean_queried

            self.herbs_raw.update_one({"_id": existing["_id"]}, update_doc)
            logger.info(
                f"🌿 [No Duplicate] Updated and merged data for herb '{clean_queried or scientific_name}' in herbs_raw (ID: {existing['_id']})."
            )
            return existing["_id"]
        else:
            # Create a single new document
            document = {
                **data,
                "queried_name": clean_queried,
                "source_urls": clean_sources,
                "created_at": now,
                "updated_at": now,
            }
            result = self.herbs_raw.insert_one(document)
            logger.info(
                f"🌿 [No Duplicate] Saved unique record for herb '{clean_queried or scientific_name}' into herbs_raw (ID: {result.inserted_id})."
            )
            return result.inserted_id

    def insert_herb_data(self, data: Dict[str, Any], source_url: str) -> Any:
        """Backward compatibility wrapper: delegates to save_or_update_herb_data."""
        return self.save_or_update_herb_data(data, [source_url])

    def log_crawl(
        self,
        url: str,
        status: str,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record or update crawl status of a URL in crawled_logs.
        Uses upsert to guarantee Idempotency.
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
        logger.info(f"📝 Crawl log updated: [{status.upper()}] - {url}")

    def is_herb_in_database(
        self, keyword: str, scientific_name: Optional[str] = None
    ) -> bool:
        """
        Check if herbal data has already been synthesized and saved in herbs_raw.
        """
        clean_kw = keyword.strip().lower() if keyword else ""
        clean_sci = scientific_name.strip() if scientific_name else ""

        or_conditions = []
        if clean_kw:
            or_conditions.append({"queried_name": clean_kw})
            or_conditions.append({"herb_name.local": clean_kw})
        if clean_sci and clean_sci.lower() != "null":
            or_conditions.append({"herb_name.scientific": clean_sci})

        if not or_conditions:
            return False

        return self.herbs_raw.find_one({"$or": or_conditions}) is not None

    def is_keyword_searched(
        self, keyword: str, scientific_name: Optional[str] = None
    ) -> bool:
        """
        Perform O(1) check whether keyword or scientific_name has already been completed.
        Returns True (skip) if:
          - keyword_logs has status == 'completed' (or legacy 'searched'), OR
          - The herb already exists in herbs_raw.
        If status is 'interrupted' or 'failed', returns False to allow reprocessing.
        """
        clean_kw = keyword.strip().lower() if keyword else ""
        clean_sci = scientific_name.strip() if scientific_name else ""

        or_conditions = []
        if clean_kw:
            or_conditions.append({"keyword": clean_kw})
        if clean_sci and clean_sci.lower() != "null":
            or_conditions.append({"scientific_name": clean_sci})

        if not or_conditions:
            return False

        doc = self.keyword_logs.find_one({"$or": or_conditions})
        if doc:
            status = doc.get("status")
            if status in ("interrupted", "failed"):
                # Interrupted or failed; check if somehow already in herbs_raw
                return self.is_herb_in_database(keyword, scientific_name)
            # Status is 'completed' or 'searched'
            return True

        # Not found in keyword_logs; check if already saved in herbs_raw
        return self.is_herb_in_database(keyword, scientific_name)

    def log_keyword(
        self,
        keyword: str,
        status: str = "completed",
        scientific_name: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
    ) -> None:
        """
        Record or update keyword status in keyword_logs with O(1) Unique Index.
        Status can be: 'completed', 'interrupted', 'failed', 'processing'.
        Uses upsert to guarantee Idempotency.
        """
        clean_kw = keyword.strip().lower()
        clean_sci = (
            scientific_name.strip()
            if (scientific_name and scientific_name.lower() != "null")
            else None
        )

        doc: Dict[str, Any] = {
            "keyword": clean_kw,
            "status": status,
            "searched_at": time.time(),
            "metadata": metadata or {},
        }
        if clean_sci:
            doc["scientific_name"] = clean_sci

        self.keyword_logs.update_one(
            {"keyword": clean_kw},
            {"$set": doc, "$setOnInsert": {"created_at": time.time()}},
            upsert=True,
        )
        logger.info(
            f"📝 [Keyword Logs] Recorded keyword '{clean_kw}' (status: '{status}') in keyword_logs."
        )

    def sync_unprocessed_keywords(self) -> int:
        """
        Identify and reset keyword_logs records that have no corresponding entry in herbs_raw.
        Changes their status to 'interrupted' so subsequent crawler runs will process them.
        Returns the count of reset records.
        """
        cursor = self.keyword_logs.find({"status": {"$in": ["searched", "processing"]}})
        reset_count = 0
        for doc in cursor:
            kw = doc.get("keyword")
            sci = doc.get("scientific_name")
            if not self.is_herb_in_database(kw, sci):
                self.keyword_logs.update_one(
                    {"_id": doc["_id"]},
                    {"$set": {"status": "interrupted", "updated_at": time.time()}},
                )
                reset_count += 1

        if reset_count > 0:
            logger.info(
                f"🔄 [Keyword Logs Sync] Reset {reset_count} incomplete keywords to 'interrupted' for reprocessing."
            )
        return reset_count

    def close(self) -> None:
        """Close MongoDB connection."""
        self.client.close()
        logger.info("MongoDB connection closed.")
