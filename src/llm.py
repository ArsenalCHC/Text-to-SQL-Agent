"""Ollama LLM 客户端（OpenAI 兼容接口）。

指向 GPU 4-7 上的独立 Ollama 实例（11435），与生产实例（11434 / GPU 0-3）物理隔离。
只依赖 requests（标准 pip 包），不依赖 openai/langchain，便于离线测试替换。
"""
from __future__ import annotations

import logging
import os
from typing import List, Optional

import requests
import yaml

logger = logging.getLogger(__name__)

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_CFG = os.path.join(ROOT, "config", "llm.yaml")


class OllamaLLM:
    """最小聊天客户端：chat(messages) -> str。"""

    def __init__(self, base_url: str, model: str, temperature: float = 0.0,
                 max_tokens: int = 1024, timeout: int = 120,
                 reasoning_effort: str = "none"):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.temperature = temperature
        self.max_tokens = max_tokens
        self.timeout = timeout
        self.reasoning_effort = reasoning_effort

    @classmethod
    def from_config(cls, cfg_path: Optional[str] = None, section: str = "llm") -> "OllamaLLM":
        path = cfg_path or os.getenv("LLM_CFG", DEFAULT_CFG)
        with open(path, "r", encoding="utf-8") as f:
            cfg = yaml.safe_load(f)
        m = cfg[section]
        return cls(
            base_url=os.getenv("OLLAMA_BASE_URL", m["base_url"]),
            model=os.getenv("OLLAMA_MODEL", m["model"]),
            temperature=m.get("temperature", 0.0),
            max_tokens=m.get("max_tokens", 1024),
            timeout=m.get("timeout", 120),
            reasoning_effort=m.get("reasoning_effort", "none"),
        )

    def chat(self, messages: List[dict], temperature: Optional[float] = None) -> str:
        """调用 /v1/chat/completions，返回首条回复文本。失败抛异常（由调用方决定重试/降级）。"""
        payload = {
            "model": self.model,
            "messages": messages,
            "temperature": self.temperature if temperature is None else temperature,
            "max_tokens": self.max_tokens,
            "stream": False,
        }
        # 思考型模型（qwen3.5 等）在 OpenAI 兼容端点默认开 thinking；
        # reasoning_effort="none" 显式关闭，避免 SQL 生成前多吐一段推理链拖慢并污染 content。
        if self.reasoning_effort:
            payload["reasoning_effort"] = self.reasoning_effort
        resp = requests.post(
            f"{self.base_url}/chat/completions", json=payload, timeout=self.timeout
        )
        resp.raise_for_status()
        data = resp.json()
        return data["choices"][0]["message"]["content"]

    def __call__(self, messages: List[dict], temperature: Optional[float] = None) -> str:
        """使实例可被直接调用，对齐 `callable(messages)->str` 契约。

        图节点（nodes.py）与离线假实现（_DemoLLM.__call__）都按「可调用」约定注入 LLM；
        这里作为薄别名转发到 chat()，保证 OllamaLLM 与假 LLM 可互换。
        """
        return self.chat(messages, temperature=temperature)

    def health_check(self) -> bool:
        try:
            r = requests.get(f"{self.base_url}/models", timeout=5)
            return r.status_code == 200
        except Exception as e:  # noqa: BLE001
            logger.warning("Ollama 健康检测失败: %s", e)
            return False


def extract_sql(text: str) -> str:
    """从 LLM 输出中抽取 SQL：
    优先取 ```sql ...``` 代码块；否则去掉 ``` 围栏后整段当作 SQL。
    """
    import re

    m = re.search(r"```sql\s*(.*?)```", text, re.DOTALL | re.IGNORECASE)
    if m:
        return m.group(1).strip()
    m = re.search(r"```\s*(.*?)```", text, re.DOTALL)
    if m:
        return m.group(1).strip()
    return text.strip()
