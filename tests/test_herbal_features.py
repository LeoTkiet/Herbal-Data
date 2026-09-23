import json
import os
import sys
import unittest
from unittest.mock import MagicMock, patch

from main_scraper import load_herbs_from_file
from src.db_manager import DatabaseManager
from src.herb_name_spider import HerbNameSpider
from src.pipeline import HerbalScrapingPipeline
from src.spider import PDFSpider


class TestHerbalFeatures(unittest.TestCase):

    def test_vietnamese_herbs_json_seed_data(self):
        """Verify that vietnamese_herbs.json contains at least 10 herb species with complete seed data."""
        json_path = "vietnamese_herbs.json"
        self.assertTrue(os.path.exists(json_path), f"File {json_path} does not exist.")
        with open(json_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        self.assertIsInstance(data, list)
        self.assertGreaterEqual(len(data), 10)
        # Verify first 10 seed herbs
        for item in data[:10]:
            self.assertIn("name", item)
            self.assertIn("scientific_name", item)
            self.assertTrue(bool(item["name"]))
            self.assertTrue(bool(item["scientific_name"]))

    def test_load_herbs_from_file_json_and_txt(self):
        """Verify reading herb entities from both JSON and TXT formats."""
        # Read from vietnamese_herbs.json
        entities = load_herbs_from_file("vietnamese_herbs.json")
        self.assertGreaterEqual(len(entities), 10)
        first_herb = entities[0]
        self.assertEqual(first_herb["name"], "Sâm Ngọc Linh")
        self.assertEqual(first_herb["scientific_name"], "Panax vietnamensis")

        # Read from comma-separated TXT
        with patch("builtins.open", unittest.mock.mock_open(read_data="sâm ngọc linh, xạ đen, cà gai leo")), \
             patch("os.path.exists", return_value=True):
            txt_entities = load_herbs_from_file("dummy.txt")
            self.assertEqual(len(txt_entities), 3)
            self.assertEqual(txt_entities[0]["name"], "sâm ngọc linh")

    def test_herb_name_spider_parse_text(self):
        """Verify local name and scientific name extraction by HerbNameSpider."""
        spider = HerbNameSpider()
        parsed1 = spider.parse_herb_name_text("Ba kích (Morinda officinalis)")
        self.assertIsNotNone(parsed1)
        self.assertEqual(parsed1["name"], "Ba kích")
        self.assertEqual(parsed1["scientific_name"], "Morinda officinalis")

        parsed2 = spider.parse_herb_name_text("Sâm Ngọc Linh")
        self.assertIsNotNone(parsed2)
        self.assertEqual(parsed2["name"], "Sâm Ngọc Linh")
        self.assertEqual(parsed2["scientific_name"], "")

    def test_spider_query_format(self):
        """Verify DDGS search query syntax: {herb_name} nghiên cứu filetype:pdf"""
        spider = PDFSpider()
        query = spider.generate_search_query("sâm ngọc linh")
        self.assertEqual(query, "sâm ngọc linh nghiên cứu filetype:pdf")

    @patch("src.db_manager.MongoClient")
    def test_db_manager_keyword_logs_o1_and_scientific_dedup(self, mock_mongo_client):
        """Verify O(1) keyword_logs lookup and deduplication on scientific_name."""
        db_mgr = DatabaseManager.__new__(DatabaseManager)
        mock_keyword_logs = MagicMock()
        db_mgr.keyword_logs = mock_keyword_logs
        db_mgr.herbs_raw = MagicMock()
        db_mgr.herbs_raw.find_one.return_value = None
        db_mgr.crawled_logs = MagicMock()

        # Simulate keyword has not been searched yet
        mock_keyword_logs.find_one.return_value = None
        self.assertFalse(
            db_mgr.is_keyword_searched("sâm ngọc linh", "Panax vietnamensis")
        )

        # Log keyword into keyword_logs
        db_mgr.log_keyword(
            keyword="sâm ngọc linh",
            status="searched",
            scientific_name="Panax vietnamensis",
        )
        mock_keyword_logs.update_one.assert_called_once()
        filter_arg = mock_keyword_logs.update_one.call_args[0][0]
        set_doc = mock_keyword_logs.update_one.call_args[0][1]["$set"]
        self.assertEqual(filter_arg, {"keyword": "sâm ngọc linh"})
        self.assertEqual(set_doc["status"], "searched")
        self.assertEqual(set_doc["scientific_name"], "Panax vietnamensis")

        # Simulate already exists in keyword_logs
        mock_keyword_logs.find_one.return_value = {
            "keyword": "sâm ngọc linh",
            "scientific_name": "Panax vietnamensis",
            "status": "searched",
        }

        # Matches local name -> True (skip)
        self.assertTrue(db_mgr.is_keyword_searched("sâm ngọc linh"))

        # Matches scientific name -> True (skip)
        self.assertTrue(
            db_mgr.is_keyword_searched("tên khác", scientific_name="Panax vietnamensis")
        )

    @patch("src.db_manager.MongoClient")
    def test_db_manager_no_row_duplicated_insert_and_upsert(self, mock_mongo_client):
        """Verify No Row Duplication guarantee in herbs_raw."""
        db_mgr = DatabaseManager.__new__(DatabaseManager)
        mock_collection = MagicMock()
        db_mgr.herbs_raw = mock_collection
        db_mgr.crawled_logs = MagicMock()
        db_mgr.keyword_logs = MagicMock()

        # Insert new record
        mock_collection.find_one.return_value = None
        mock_insert_result = MagicMock()
        mock_insert_result.inserted_id = "mock_id_1"
        mock_collection.insert_one.return_value = mock_insert_result

        first_data = {
            "herb_name": {"scientific": "Panax vietnamensis", "local": ["Sâm Ngọc Linh"]},
            "medicinal_properties": ["Bổ dưỡng", "Chống oxy hóa"],
            "active_compounds": ["Majonoside-R2"],
            "curable_diseases": ["Suy nhược cơ thể"],
        }
        res1 = db_mgr.save_or_update_herb_data(
            first_data,
            source_urls=["https://example.com/paper1.pdf"],
            queried_herb_name="sâm ngọc linh",
        )
        self.assertEqual(res1, "mock_id_1")
        mock_collection.insert_one.assert_called_once()

        # Update existing record (Merge into previous document)
        mock_collection.reset_mock()
        mock_collection.find_one.return_value = {
            "_id": "mock_id_1",
            "queried_name": "sâm ngọc linh",
            "herb_name": {"scientific": "Panax vietnamensis", "local": ["Sâm Ngọc Linh"]},
            "medicinal_properties": ["Bổ dưỡng"],
            "active_compounds": ["Majonoside-R2"],
            "curable_diseases": ["Suy nhược"],
            "source_urls": ["https://example.com/paper1.pdf"],
        }
        second_data = {
            "herb_name": {"scientific": "Panax vietnamensis", "local": ["Sâm Việt Nam"]},
            "medicinal_properties": ["Kháng stress"],
            "active_compounds": ["Ginsenoside Rb1"],
            "curable_diseases": ["Căng thẳng"],
        }
        res2 = db_mgr.save_or_update_herb_data(
            second_data,
            source_urls=["https://example.com/paper2.pdf"],
            queried_herb_name="sâm ngọc linh",
        )
        self.assertEqual(res2, "mock_id_1")
        mock_collection.insert_one.assert_not_called()
        mock_collection.update_one.assert_called_once()

    @patch("src.pipeline.DatabaseManager")
    @patch("src.pipeline.GeminiKeyPool")
    @patch("src.pipeline.PDFProcessor")
    def test_pipeline_process_herb_single_ai_call_for_multiple_pdfs(
        self, mock_pdf_cls, mock_ai_cls, mock_db_cls
    ):
        """Verify pipeline consolidates all PDFs for an herb and calls Gemini exactly once."""
        pipeline = HerbalScrapingPipeline.__new__(HerbalScrapingPipeline)
        pipeline.pdf_processor = mock_pdf_cls.return_value
        pipeline.ai_pool = mock_ai_cls.return_value
        pipeline.db = mock_db_cls.return_value
        pipeline.min_delay = 0
        pipeline.max_delay = 0

        pipeline.db.is_url_crawled.return_value = False
        pipeline.db.is_herb_in_database.return_value = False
        pipeline.pdf_processor.download_pdf.side_effect = ["/tmp/herb1.pdf", "/tmp/herb2.pdf"]
        pipeline.pdf_processor.extract_text.side_effect = [
            "Tài liệu nghiên cứu 1 về sâm ngọc linh...",
            "Tài liệu nghiên cứu 2 về hoạt chất sâm ngọc linh...",
        ]
        pipeline.ai_pool.extract_herb_data.return_value = {
            "herb_name": {"scientific": "Panax vietnamensis", "local": ["Sâm Ngọc Linh"]},
            "medicinal_properties": ["Tăng cường sinh lực"],
            "active_compounds": ["Majonoside-R2"],
            "curable_diseases": ["Suy nhược"],
        }
        pipeline.db.save_or_update_herb_data.return_value = "saved_doc_id"

        urls = ["https://example.com/pdf1.pdf", "https://example.com/pdf2.pdf"]

        with patch("os.path.exists", return_value=True), patch("os.remove") as mock_remove:
            success = pipeline.process_herb("sâm ngọc linh", urls)

        self.assertTrue(success)
        self.assertEqual(pipeline.pdf_processor.download_pdf.call_count, 2)
        self.assertEqual(pipeline.pdf_processor.extract_text.call_count, 2)
        self.assertEqual(mock_remove.call_count, 2)
        self.assertEqual(pipeline.ai_pool.extract_herb_data.call_count, 1)

    @patch("src.herb_name_spider.requests.get")
    def test_herb_name_spider_update_with_limit(self, mock_get):
        """Verify HerbNameSpider stops exactly when target limit is reached."""
        spider = HerbNameSpider()
        # Mock HTML returning 5 new herbs
        fake_html = """
        <div id="mw-pages">
            <ul>
                <li><a href="#">Cây thuốc 1</a></li>
                <li><a href="#">Cây thuốc 2</a></li>
                <li><a href="#">Cây thuốc 3</a></li>
                <li><a href="#">Cây thuốc 4</a></li>
                <li><a href="#">Cây thuốc 5</a></li>
            </ul>
        </div>
        """
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.text = fake_html
        mock_get.return_value = mock_response

        # Mock empty list file
        with patch.object(spider, "load_master_list", return_value=[]), \
             patch.object(spider, "save_master_list") as mock_save:
            added = spider.update_master_list(
                json_path="test_mock.json", source_url="https://fake.url", limit=3
            )
            self.assertEqual(added, 3)
            saved_list = mock_save.call_args[0][1]
            self.assertEqual(len(saved_list), 3)

    def test_main_scraper_phase_arguments(self):
        """Verify CLI argument parsing for phase groups: all, phase0, phase12."""
        from main_scraper import parse_arguments

        # Test phase0
        with patch("sys.argv", ["main_scraper.py", "--phase", "phase0", "--phase0-limit", "50"]):
            args = parse_arguments()
            self.assertEqual(args.phase, "phase0")
            self.assertEqual(args.phase0_limit, 50)

        # Test phase12
        with patch("sys.argv", ["main_scraper.py", "--phase", "phase12", "--max-results", "8"]):
            args = parse_arguments()
            self.assertEqual(args.phase, "phase12")
            self.assertEqual(args.max_results, 8)

        # Test all (default)
        with patch("sys.argv", ["main_scraper.py", "--phase0-limit", "25", "--max-results", "4", "--phase12-limit", "10"]):
            args = parse_arguments()
            self.assertEqual(args.phase, "all")
            self.assertEqual(args.phase0_limit, 25)
            self.assertEqual(args.max_results, 4)
            self.assertEqual(args.phase12_limit, 10)

        # Test phase12 with phase12-limit
        with patch("sys.argv", ["main_scraper.py", "--phase", "phase12", "--phase12-limit", "3"]):
            args = parse_arguments()
            self.assertEqual(args.phase, "phase12")
            self.assertEqual(args.phase12_limit, 3)

    @patch("src.db_manager.MongoClient")
    def test_db_manager_sync_unprocessed_keywords(self, mock_mongo_client):
        """Verify sync_unprocessed_keywords identifies missing herbs in herbs_raw and resets status."""
        db_mgr = DatabaseManager.__new__(DatabaseManager)
        db_mgr.keyword_logs = MagicMock()
        db_mgr.herbs_raw = MagicMock()

        # Simulate 2 keywords in keyword_logs: one in herbs_raw, one missing
        incomplete_doc = {
            "_id": "mock_id_1",
            "keyword": "chi ba gạc",
            "scientific_name": None,
            "status": "searched",
        }
        db_mgr.keyword_logs.find.return_value = [incomplete_doc]
        db_mgr.herbs_raw.find_one.return_value = None  # Missing from herbs_raw

        reset_count = db_mgr.sync_unprocessed_keywords()
        self.assertEqual(reset_count, 1)
        db_mgr.keyword_logs.update_one.assert_called_once()
        update_args = db_mgr.keyword_logs.update_one.call_args
        self.assertEqual(update_args[0][0], {"_id": "mock_id_1"})
        self.assertEqual(update_args[0][1]["$set"]["status"], "interrupted")

    def test_graceful_shutdown_interruptible_sleep(self):
        """Verify interruptible_sleep exits promptly when shutdown_requested is True."""
        import main_scraper
        main_scraper.shutdown_requested = False
        self.assertTrue(main_scraper.interruptible_sleep(0.05))

        main_scraper.shutdown_requested = True
        self.assertFalse(main_scraper.interruptible_sleep(5.0))
        main_scraper.shutdown_requested = False

    @patch("src.ai_manager.genai")
    def test_ai_manager_default_model_gemini_36_flash(self, mock_genai):
        """Verify GeminiKeyPool defaults to gemini-3.6-flash."""
        from src.ai_manager import GeminiKeyPool
        with patch.dict(os.environ, {"GEMINI_KEYS": "fake_key_1,fake_key_2"}):
            pool = GeminiKeyPool()
            self.assertEqual(pool.model_name, "gemini-3.6-flash")


if __name__ == "__main__":
    unittest.main()
