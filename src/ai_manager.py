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
You are an expert in pharmacognosy and Vietnamese traditional herbal medicine.
Your task is to read and analyze synthesized text from medical and pharmaceutical research papers about a medicinal herb, then cross-reference, synthesize, and extract comprehensive information about that medicinal plant according to the JSON format below.

MANDATORY REQUIREMENTS:
1. Return ONLY a single valid JSON object, with NO introductory text or markdown formatting outside the JSON.
2. Synthesize and consolidate knowledge from ALL provided research documents, completely eliminating duplicate information.
3. The JSON structure must strictly follow this schema:
{
  "herb_name": {
    "scientific": "Accurate Latin scientific name",
    "local": ["Local Vietnamese name 1", "Local name 2 (or null if not available)"]
  },
  "medicinal_properties": ["Pharmacological property 1", "Pharmacological property 2"],
  "active_compounds": ["Phytochemical compound / active constituent 1", "Active constituent 2"],
  "curable_diseases": ["Disease or symptom supported in treatment 1", "Disease 2"]
}
4. All list fields (local, medicinal_properties, active_compounds, curable_diseases) must be deduplicated string arrays. If a field is not mentioned in the source documents, return an empty array [].
""".strip()


class GeminiKeyPool:
    """
    Manages rotation across a pool of Gemini API Keys (API Key Rotation)
    and handles data extraction via the Gemini model (default: gemini-2.5-flash).
    """

    def __init__(
        self,
        api_keys: Optional[List[str]] = None,
        model_name: Optional[str] = None,
    ):
        if api_keys:
            self.keys = [k.strip() for k in api_keys if k and k.strip()]
        else:
            raw_env_keys = os.getenv("GEMINI_KEYS", "")
            self.keys = [k.strip() for k in raw_env_keys.split(",") if k.strip()]

        if not self.keys:
            raise ValueError(
                "No Gemini API Keys found. Please configure the GEMINI_KEYS variable in your .env file!"
            )

        self.current_index = 0
        self.model_name = model_name or os.getenv("GEMINI_MODEL", "gemini-3.6-flash")
        self.model = None
        self._init_current_model()

    @property
    def current_key(self) -> str:
        return self.keys[self.current_index]

    def _init_current_model(self) -> None:
        """Initialize or reconfigure the model with the current active API key."""
        key = self.current_key
        masked_key = f"{key[:8]}...{key[-4:]}" if len(key) > 12 else "***"
        logger.info(
            f"Using Gemini API Key [Index: {self.current_index + 1}/{len(self.keys)}]: {masked_key} (Model: {self.model_name})"
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
        """Rotate to the next API key in the pool."""
        self.current_index = (self.current_index + 1) % len(self.keys)
        logger.warning(
            f"🔄 Key rotation triggered! Switched to Key index {self.current_index + 1}/{len(self.keys)}."
        )
        self._init_current_model()
        return self.current_key

    def _clean_json_text(self, text: str) -> str:
        """Strip markdown code block fences if accidentally returned by LLM."""
        cleaned = text.strip()
        cleaned = re.sub(r"^```(?:json)?\s*", "", cleaned, flags=re.IGNORECASE)
        cleaned = re.sub(r"\s*```$", "", cleaned)
        return cleaned.strip()

    def extract_herb_data(self, raw_text: str) -> Dict[str, Any]:
        """
        Send research text to Gemini for structured data extraction.
        Automatically catches ResourceExhausted (429) and recoverable API errors, rotating keys.
        """
        if not raw_text or not raw_text.strip():
            raise ValueError("Input text is empty, cannot perform extraction!")

        max_attempts = len(self.keys)
        attempts = 0

        prompt = f"Analyze and extract herbal medicine data from the following research text:\n\n{raw_text}"

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
                    f"⚠️ Quota 429 Error (ResourceExhausted) on Key {self.current_index + 1}/{len(self.keys)}: {e}"
                )
                if attempts < max_attempts:
                    self.rotate_key()
                else:
                    logger.error("❌ All API Keys in the pool have exhausted their quota!")
                    raise RuntimeError(
                        "All Gemini API Keys have reached their quota limit (429 ResourceExhausted)!"
                    ) from e

            except json.JSONDecodeError as json_err:
                logger.error(f"❌ JSON decoding error from LLM response: {json_err}")
                raise

            except Exception as e:
                attempts += 1
                logger.warning(
                    f"⚠️ API error on Key {self.current_index + 1}/{len(self.keys)} ({type(e).__name__}: {e})."
                )
                if attempts < max_attempts:
                    logger.info("Rotating to next API key in pool and retrying...")
                    self.rotate_key()
                else:
                    logger.error(f"❌ All {max_attempts} keys in the pool failed: {e}")
                    raise
