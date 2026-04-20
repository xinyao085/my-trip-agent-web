import os
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from .routes.trip import router

_FRONTEND_DIR = os.path.join(os.path.dirname(__file__), "..", "frontend")

app = FastAPI(
    title="旅行规划 Multi-Agent API",
    description="基于 LangChain + MCP 的多 Agent 旅行规划服务",
    version="1.0.0",
)

# 开发阶段 allow_origins=["*"]；生产环境应改为具体域名
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)

# 静态文件必须在 API 路由之后挂载，否则会拦截 /plan、/chat 等请求
app.mount("/", StaticFiles(directory=_FRONTEND_DIR, html=True), name="frontend")
