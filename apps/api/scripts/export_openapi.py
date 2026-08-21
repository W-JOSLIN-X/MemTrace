"""Export the generated FastAPI OpenAPI document to the contract directory."""

from __future__ import annotations

import json
import os
import sys
from importlib import import_module
from pathlib import Path
from unittest.mock import patch

PROJECT_ROOT = Path(__file__).resolve().parents[3]
API_ROOT = Path(__file__).resolve().parents[1]
OUTPUT_PATH = PROJECT_ROOT / "contracts" / "openapi.json"
SAFE_IMPORT_ENV = {
    "APP_NAME": "MemTrace API",
    "APP_ENV": "development",
    "APP_VERSION": "0.1.0",
    "LOG_LEVEL": "WARNING",
    "MOCK_MODE": "true",
    "LLM_API_KEY": "",
    "LLM_BASE_URL": "https://api.deepseek.com",
    "LLM_MODEL": "deepseek-v4-flash",
    "MEMTRACE_DATA_DIR": "data",
    "MEMTRACE_WEB_DIST": "",
    "PROVIDER_TIMEOUT_SECONDS": "60",
    "MAX_TASKS": "100",
    "MAX_SUBSCRIBERS_PER_TASK": "8",
    "SUBSCRIBER_QUEUE_SIZE": "64",
    "SSE_HEARTBEAT_SECONDS": "15",
    "MOCK_CHUNK_DELAY_MS": "250",
}


def build_document() -> dict[str, object]:
    sys.path.insert(0, str(API_ROOT / "src"))
    config_module = import_module("memtrace_api.config")
    # memtrace_api.main exposes the ASGI app for Uvicorn and therefore creates
    # one Settings instance at import time. Pin every setting during that
    # import and the explicit factory call so aliases from a caller's malformed
    # environment cannot affect this artifact.
    with patch.dict(os.environ, SAFE_IMPORT_ENV, clear=False):
        main_module = import_module("memtrace_api.main")
        settings = config_module.Settings(
            _env_file=None,
            app_name="MemTrace API",
            app_env="development",
            app_version=config_module.APP_VERSION,
            mock_mode=True,
            llm_api_key=None,
            memtrace_data_dir=PROJECT_ROOT / "data",
            memtrace_web_dist=None,
        )
        return main_module.create_app(settings).openapi()


def main() -> None:
    OUTPUT_PATH.write_text(
        json.dumps(build_document(), ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(OUTPUT_PATH)


if __name__ == "__main__":
    main()
