"""LLM 配置层：DeepSeek（OpenAI 兼容）ChatOpenAI 实例。

对齐 stock_review_crew 的 config 模式：从 .env 读取 DEEPSEEK_* 变量，
提供常规（temperature=0.7）与严格（temperature=0.1）两个实例。

无 Key 时模块仍可导入（使用占位 Key），调用方通过 ``llm_available()``
判断并走规则引擎降级，不会发起网络请求。
"""

import os

from dotenv import load_dotenv
from langchain_openai import ChatOpenAI

load_dotenv()

DEEPSEEK_API_KEY = (os.getenv("DEEPSEEK_API_KEY") or "").strip()
DEEPSEEK_API_BASE = (
    os.getenv("DEEPSEEK_API_BASE")
    or os.getenv("DEEPSEEK_BASE_URL")
    or "https://opencode.ai/zen/go/v1"
)
DEEPSEEK_MODEL = os.getenv("DEEPSEEK_MODEL") or "deepseek-v4-flash"

# ChatOpenAI 在没有任何 Key 时初始化即抛错；占位 Key 保证无 Key 环境可导入，
# 实际调用前用 llm_available() 判断，因此不会真正发起请求。
_PLACEHOLDER_API_KEY = "sk-not-configured"


def _make_llm(temperature: float) -> ChatOpenAI:
    return ChatOpenAI(
        model=DEEPSEEK_MODEL,
        api_key=DEEPSEEK_API_KEY or _PLACEHOLDER_API_KEY,
        base_url=DEEPSEEK_API_BASE,
        temperature=temperature,
        timeout=120,
        max_retries=2,
    )


# 常规生成：分析师点评、辩论、最终报告
llm = _make_llm(0.7)

# 严格模式：主持人分歧判断
llm_strict = _make_llm(0.1)


def llm_available() -> bool:
    """是否有可用的 DeepSeek API Key（无 Key 时走规则引擎降级）。"""
    return bool(DEEPSEEK_API_KEY)
