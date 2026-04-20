import os
import subprocess
import contextlib

from dotenv import load_dotenv, find_dotenv
from langchain_openai import ChatOpenAI
import mcp.client.stdio as _mcp_stdio_mod

# 从当前目录向上查找 .env，找不到则回退到 my-trip-agent 目录
_dotenv_path = find_dotenv(usecwd=True)
if _dotenv_path:
    load_dotenv(_dotenv_path, override=False)
else:
    _fallback = os.path.join(os.path.dirname(__file__), "..", "..", "my-trip-agent", ".env")
    load_dotenv(_fallback, override=False)

# 启动时校验必要环境变量
_missing = [k for k in ("LLM_API_KEY", "AMAP_API_KEY") if not os.getenv(k)]
if _missing:
    raise RuntimeError(
        f"缺少必要的环境变量：{', '.join(_missing)}\n"
        "请在 my-trip-agent-web/.env 或 my-trip-agent/.env 中配置后重启。"
    )

# LLM 在模块级别初始化一次，所有请求复用同一实例（ChatOpenAI 本身无状态）
llm = ChatOpenAI(
    model=os.getenv("LLM_MODEL_ID", "qwen-turbo"),
    api_key=os.getenv("LLM_API_KEY"),
    base_url=os.getenv("LLM_BASE_URL"),
)

# MCP Server 配置；过滤 None 值防止 langchain-mcp-adapters 报 TypeError
_amap_key = os.getenv("AMAP_API_KEY")
MCP_CONFIG = {
    "amap": {
        "command": "uvx",
        "args": ["amap-mcp-server"],
        "env": {k: v for k, v in {"AMAP_MAPS_API_KEY": _amap_key}.items() if v is not None},
        "transport": "stdio",
    }
}

# 猴子补丁：屏蔽 MCP 子进程的 stderr，避免协议日志混入 uvicorn 输出
_original_stdio_client = _mcp_stdio_mod.stdio_client

@contextlib.asynccontextmanager
async def _silent_stdio_client(server, **kwargs):
    server.stderr = subprocess.DEVNULL
    async with _original_stdio_client(server, **kwargs) as streams:
        yield streams

_mcp_stdio_mod.stdio_client = _silent_stdio_client
