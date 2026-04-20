# Trip Planner — 多 Agent AI 旅行规划 Web 应用

基于 **LangChain + MCP + FastAPI + Vue 3** 的多 Agent 协作旅行规划应用。输入目标城市、天数和偏好，4 个 AI Agent 自动协作完成景点搜索、天气查询、酒店推荐，并流式生成完整行程计划，支持多轮对话修改。

---

## 功能特性

- **4 Agent 流水线**：景点搜索 → 天气查询 → 酒店推荐 → 规划师流式生成行程
- **MCP 工具集成**：通过高德地图 MCP Server 获取实时地图数据
- **流式输出**：打字机效果实时展示 AI 生成内容
- **多轮对话**：行程生成后可继续追问修改，LLM 自动判断是否需要重新查询数据
- **智能参数感知**：换城市/天数/偏好时自动触发 Agent 1-3 重新获取实时数据

---

## 技术栈

| 层 | 技术 |
|---|---|
| 后端框架 | FastAPI + Uvicorn |
| AI 框架 | LangChain + LangGraph |
| LLM | Qwen（通过阿里云 DashScope，兼容 OpenAI 接口） |
| 工具协议 | MCP（Model Context Protocol）+ 高德地图 MCP Server |
| 前端 | Vue 3（CDN ESM）+ Vanilla JS，无构建工具 |
| 流式传输 | FastAPI StreamingResponse + Web Streams API |

---

## 项目结构

```
my-trip-agent-web/
├── backend/
│   ├── main.py            # FastAPI 应用入口，挂载路由和静态文件
│   ├── config.py          # LLM 和 MCP 配置初始化
│   ├── agents.py          # 手写工具调用循环的 Agent 实现
│   ├── agents_react.py    # 基于 LangGraph create_react_agent 的实现（可替换）
│   ├── session.py         # 进程内会话存储
│   ├── schemas.py         # Pydantic 请求模型
│   └── routes/
│       └── trip.py        # /plan 和 /chat 路由
├── frontend/
│   ├── index.html         # Vue 3 单页应用
│   ├── css/style.css
│   └── js/
│       ├── app.js         # Vue 组件逻辑
│       ├── api.js         # fetch 封装
│       └── stream.js      # 流式响应解析
├── .env                   # 环境变量（需自行配置）
└── run.py                 # 启动入口
```

---

## 快速开始

### 1. 安装依赖

```bash
pip install fastapi uvicorn langchain langchain-openai langchain-mcp-adapters langgraph python-dotenv
```

### 2. 配置环境变量

在项目根目录创建 `.env` 文件：

```env
LLM_MODEL_ID=qwen-turbo
LLM_API_KEY=你的阿里云 DashScope API Key
LLM_BASE_URL=https://dashscope.aliyuncs.com/compatible-mode/v1
AMAP_API_KEY=你的高德地图 API Key
```

- **LLM_API_KEY**：在 [阿里云百炼](https://bailian.console.aliyun.com/) 获取
- **AMAP_API_KEY**：在 [高德开放平台](https://lbs.amap.com/) 获取

### 3. 启动服务

```bash
python run.py
```

浏览器访问 **http://localhost:8000**

---

## API 说明

### `POST /plan` — 生成旅行计划（流式）

**请求体：**
```json
{
  "city": "成都",
  "days": 3,
  "preferences": "美食、历史文化"
}
```

**响应：** 纯文本流，末尾附加 `[SESSION_ID:xxx]` 用于后续多轮对话。

---

### `POST /chat` — 多轮对话修改计划（流式）

**请求体：**
```json
{
  "session_id": "由 /plan 返回的 session_id",
  "message": "把第二天改成自然风景主题"
}
```

**响应：** 纯文本流。

---

### `GET /health` — 健康检查

```json
{ "status": "ok", "active_sessions": 2 }
```

---

## 切换 Agent 实现

项目提供两种 Agent 实现，在 `backend/routes/trip.py` 第 12 行切换：

```python
# 手写工具循环（默认）
from ..agents import fetch_fresh_data, extract_new_params, stream_planner

# LangGraph ReAct Agent
from ..agents_react import fetch_fresh_data, extract_new_params, stream_planner
```

| | `agents.py` | `agents_react.py` |
|---|---|---|
| 工具循环 | 手写，最多 5 轮 | LangGraph 托管，最多 10 步 |
| 可调试性 | 一般 | 完整消息链，便于排查 |
| 额外依赖 | 无 | `langgraph` |