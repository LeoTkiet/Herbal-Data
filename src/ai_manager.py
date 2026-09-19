import json
import logging
import os
import re
from typing import Any, Dict, List, Optional

import warnings

warnings.filterwarnings("ignore", category=FutureWarning)

import google.generativeai as genai
from google.api_core.exceptions import ResourceExhausted

logger = logging.getLogger(__name__)

HERB_EXTRACTION_SYSTEM_PROMPT = """
Bạn là một chuyên gia dược liệu học và y học cổ truyền Việt Nam.
Nhiệm vụ của bạn là đọc và phân tích văn bản bài báo khoa học y khoa/dược học, sau đó trích xuất thông tin về cây thuốc/dược liệu theo đúng định dạng JSON bên dưới.

YÊU CẦU BẮT BUỘC:
1. Chỉ trả về một JSON object hợp lệ duy nhất, KHÔNG kèm theo lời dẫn hoặc văn bản giải thích.
2. Cấu trúc JSON bắt buộc phải tuân theo schema:
{
  "herb_name": {
    "scientific": "Tên khoa học tiếng Latinh (nếu không có thì ghi null)",
    "local": ["Tên gọi địa phương hoặc tên tiếng Việt 1", "Tên 2"]
  },
  "medicinal_properties": ["Tính chất dược lý 1", "Tính chất dược lý 2"],
  "active_compounds": ["Hợp chất hóa thực vật / hoạt chất 1", "Hoạt chất 2"],
  "curable_diseases": ["Bệnh hoặc triệu chứng hỗ trợ điều trị 1", "Bệnh 2"]
}
3. Các danh sách (local, medicinal_properties, active_compounds, curable_diseases) phải là mảng string. Nếu bài báo không đề cập mục nào thì để mảng rỗng [].
""".strip()


class GeminiKeyPool:
    """
    Quản lý luân chuyển danh sách Gemini API Keys (API Key Rotation)
    và tương tác trích xuất dữ liệu qua model gemini-1.5-flash.
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model_name: str = "gemini-1.5-flash",
    ):
        if api_keys:
            self.keys = [k.strip() for k in api_keys if k and k.strip()]
        else:
            raw_env_keys = os.getenv("GEMINI_KEYS", "")
            self.keys = [k.strip() for k in raw_env_keys.split(",") if k.strip()]

        if not self.keys:
            raise ValueError(
                "Không tìm thấy Gemini API Key nào. Vui lòng cấu hình biến GEMINI_KEYS trong .env!"
            )

        self.current_index = 0
        self.model_name = model_name
        self.model = None
        self._init_current_model()

    @property
    def current_key(self) -> str:
        return self.keys[self.current_index]

    def _init_current_model(self) -> None:
        """Khởi tạo hoặc tái cấu hình model với API key hiện tại."""
        key = self.current_key
        masked_key = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
        logger.info(
            f"Sử dụng Gemini API Key [Index: {self.current_index + 1}/{len(self.keys)}]: {masked_key}"
        )

        genai.configure(api_key=key)
        self.model = genai.GenerativeModel(
            model_name=self.model_name,
            generation_config={
                "response_mime_type": "application/json",
                "temperature": 0.2,
            },
            system_instruction=HERB_EXTRACTION_SYSTEM_PROMPT,
        )

    def rotate_key(self) -> str:
        """Chuyển sang API key tiếp theo trong pool."""
        self.current_index = (self.current_index + 1) % len(self.keys)
        logger.warning(
            f"🔄 Đã kích hoạt luân chuyển Key! Chuyển sang Key index {self.current_index + 1}/{len(self.keys)}."
        )
        self._init_current_model()
        return self.current_key

    def _clean_json_text(self, text: str) -> str:
        """Loại bỏ markdown code block nếu LLM vô tình trả về."""
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def extract_herb_data(self, raw_text: str) -> Dict[str, Any]:
        """
        Gửi văn bản nghiên cứu tới Gemini để trích xuất dữ liệu.
        Tự động bắt lỗi ResourceExhausted (429) và luân chuyển key.
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("Văn bản đầu vào trống, không thể trích xuất!")

        max_attempts = len(self.keys)
        attempts = 0

        prompt = f"Hãy phân tích và trích xuất dữ liệu dược liệu từ bài nghiên cứu sau:\n\n{raw_text}"

        while attempts < max_attempts:
            try:
                response = self.model.generate_content(prompt)
                raw_json_str = response.text
                clean_json_str = self._clean_json_text(raw_json_str)
                parsed_data = json.loads(clean_json_str)
                return parsed_data

            except ResourceExhausted as e:
                attempts += 1
                logger.warning(
                    f"⚠️ Lỗi Quota 429 (ResourceExhausted) tại Key {self.current_index + 1}/{len(self.keys)}: {e}"
                )
                if attempts < max_attempts:
                    self.rotate_key()
                else:
                    logger.error("❌ Tất cả các API Key trong pool đều đã cạn kiệt Quota!")
                    raise RuntimeError(
                        "Tất cả Gemini API Keys đều chạm ngưỡng giới hạn (429 ResourceExhausted)!"
                    ) from e

            except json.JSONDecodeError as json_err:
                logger.error(f"❌ Lỗi giải mã JSON từ phản hồi LLM: {json_err}")
                raise

            except Exception as e:
                logger.error(f"❌ Lỗi không xác định khi gọi Gemini API: {e}")
                raise
