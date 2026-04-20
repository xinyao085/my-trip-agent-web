import uuid
from typing import AsyncGenerator

from fastapi import APIRouter, HTTPException
from fastapi.responses import StreamingResponse
from langchain_core.messages import SystemMessage
from langchain_mcp_adapters.client import MultiServerMCPClient

from ..config import MCP_CONFIG
from ..schemas import PlanRequest, ChatRequest
from ..session import sessions
from ..agents import fetch_fresh_data, extract_new_params, stream_planner

router = APIRouter()


@router.post(
    "/plan",
    summary="生成旅行计划（流式）",
    description=(
        "启动 4 个 Agent 协作：Agent 1-3 分别查询景点 / 天气 / 酒店，"
        "Agent 4 汇总并流式输出行程计划。\n\n"
        "响应为纯文本流，**最后一行**格式固定为 `[SESSION_ID:xxx]`，"
        "前端解析后保存，用于后续 /chat 多轮对话。"
    ),
)
async def plan_trip(req: PlanRequest):
    async def generate() -> AsyncGenerator[str, None]:
        # StreamingResponse 一旦开始发送就无法改 HTTP 状态码，用 yield 错误标记保持连接完整
        try:
            mcp_client = MultiServerMCPClient(MCP_CONFIG)
            tools = await mcp_client.get_tools()

            attractions_info, weather_info, hotels_info, extra_info = await fetch_fresh_data(
                req.city, req.preferences, tools
            )

            planner_history: list = []
            system_prompt = (
                "你是专业旅行规划师。根据提供的景点、天气、酒店及额外要求信息，"
                "生成一份清晰、实用的分天行程计划，包含每天的景点安排、餐饮建议和住宿推荐。"
                "请严格围绕用户的偏好和额外要求来安排行程，在计划中明确体现这些要求。"
                "重要原则：只描述数据中明确提到的设施或特性，不要自行推断或捏造任何细节。"
                "如果数据中没有相关信息，请注明【建议出发前向景点/酒店确认】，而不是自行编写。"
            )
            pref_line = f"用户偏好与要求：{req.preferences}\n\n" if req.preferences else ""
            extra_line = f"额外要求相关查询结果：\n{extra_info}\n\n" if extra_info else ""
            user_query = (
                f"请为{req.city} {req.days}天旅行制定详细行程计划。\n\n"
                f"{pref_line}"
                f"景点信息：\n{attractions_info}\n\n"
                f"天气情况：\n{weather_info}\n\n"
                f"住宿选项：\n{hotels_info}\n\n"
                f"{extra_line}"
            )
            async for chunk in stream_planner(planner_history, user_query, system_prompt):
                yield chunk

            # session_id 通过流末尾标记行传递（StreamingResponse header 在首字节前已锁定）
            session_id = str(uuid.uuid4())
            sessions[session_id] = {
                "planner_history": planner_history,
                "tools": tools,
                "mcp_client": mcp_client,
                "city": req.city,
                "days": req.days,
                "preferences": req.preferences,
            }
            yield f"\n\n[SESSION_ID:{session_id}]"

        except Exception as e:
            yield f"\n\n[ERROR:{e}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@router.post(
    "/chat",
    summary="多轮对话修改计划（流式）",
    description=(
        "基于 /plan 返回的 session_id 继续对话。\n\n"
        "内部会先用 LLM 判断是否需要重新查询实时数据（换城市 / 天数 / 偏好），"
        "若需要则自动重新调用 Agent 1-3，再由 Agent 4 流式输出新计划。"
    ),
)
async def chat(req: ChatRequest):
    session = sessions.get(req.session_id)
    if not session:
        raise HTTPException(status_code=404, detail="会话不存在或已过期，请重新调用 /plan")

    async def generate() -> AsyncGenerator[str, None]:
        try:
            planner_history = session["planner_history"]
            tools = session["tools"]

            params = await extract_new_params(
                req.message,
                session["city"],
                session["days"],
                session["preferences"],
            )

            if params.get("needs_refresh"):
                session["city"] = params.get("city", session["city"])
                session["days"] = params.get("days", session["days"])
                session["preferences"] = params.get("preferences", session["preferences"])

                attractions_info, weather_info, hotels_info, extra_info = await fetch_fresh_data(
                    session["city"], session["preferences"], tools
                )

                # 注入新数据为 SystemMessage，保留历史上下文同时使用最新数据
                pref_line = f"用户偏好与要求：{session['preferences']}\n\n" if session['preferences'] else ""
                extra_line = f"额外要求相关查询结果：\n{extra_info}\n\n" if extra_info else ""
                planner_history.append(SystemMessage(content=(
                    f"[数据已更新] 以下是{session['city']}的最新数据，请基于此重新规划：\n\n"
                    f"{pref_line}"
                    f"景点信息：\n{attractions_info}\n\n"
                    f"天气情况：\n{weather_info}\n\n"
                    f"住宿选项：\n{hotels_info}\n\n"
                    f"{extra_line}"
                )))

            async for chunk in stream_planner(planner_history, req.message):
                yield chunk

        except Exception as e:
            yield f"\n\n[ERROR:{e}]"

    return StreamingResponse(generate(), media_type="text/plain; charset=utf-8")


@router.get("/health", summary="健康检查")
async def health_check():
    return {
        "status": "ok",
        "active_sessions": len(sessions),
    }
