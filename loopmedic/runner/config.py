from __future__ import annotations

import os
from pathlib import Path

from agents import (
    Model,
    OpenAIChatCompletionsModel,
    OpenAIResponsesModel,
    set_tracing_disabled,
)
from openai import AsyncOpenAI

GO_BASE_URL = "https://opencode.ai/zen/go/v1"
# DeepSeek V4 Flash is the experiment default: Chat Completions, tool
# calling works after the Go China-hosting opt-in, and prompts are not
# used for training. Muse Spark 1.2 is the Responses-API fallback.
DEFAULT_MODEL = "deepseek-v4-flash"
RESPONSES_MODELS = frozenset(
    {
        "muse-spark-1.2-contributor",
        "grok-4.5",
        "gpt-5.6-luna",
    }
)
TOOL_CALL_CAP = 15
PROJECT_ROOT = Path(__file__).resolve().parents[2]
SECRET_ENV_KEYS = frozenset({"OPENCODE_API_KEY", "OPENAI_API_KEY"})


class ToolBudgetExceeded(Exception):
    def __init__(self, cap: int) -> None:
        super().__init__(f"tool call cap {cap} exceeded")
        self.cap = cap


def load_dotenv(paths: tuple[Path, ...] | None = None) -> None:
    search = paths or (Path.cwd() / ".env", PROJECT_ROOT / ".env")
    for path in search:
        if not path.is_file():
            continue
        for raw in path.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, value = line.partition("=")
            name = key.strip()
            parsed = value.strip().strip('"')
            if name in SECRET_ENV_KEYS:
                os.environ[name] = parsed
            else:
                os.environ.setdefault(name, parsed)


def api_key() -> str:
    load_dotenv()
    key = os.environ.get("OPENCODE_API_KEY") or os.environ.get(
        "OPENAI_API_KEY",
        "",
    )
    if not key:
        raise RuntimeError("OPENCODE_API_KEY is not set")
    return key


def model_name() -> str:
    load_dotenv()
    return os.environ.get("LOOPMEDIC_MODEL", DEFAULT_MODEL)


def build_model() -> Model:
    set_tracing_disabled(True)
    client = AsyncOpenAI(base_url=GO_BASE_URL, api_key=api_key())
    name = model_name()
    if name in RESPONSES_MODELS:
        return OpenAIResponsesModel(model=name, openai_client=client)
    return OpenAIChatCompletionsModel(model=name, openai_client=client)
