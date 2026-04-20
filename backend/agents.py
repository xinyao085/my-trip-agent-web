import json
import re
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage, ToolMessage

from .config import llm


async def run_single_agent(system_prompt: str, user_query: str, tools: list) -> str:
    """
    运行单个 Agent，允许 LLM 最多调用 5 轮工具后返回结果。
    工具调用完成后直接返回原始数据，不再让 LLM 二次总结。
    """
    llm_with_tools = llm.bind_tools(tools) if tools else llm
    messages = [
        SystemMessage(content=system_prompt),
        HumanMessage(content=user_query),
    ]

    for _ in range(5):
        response = await llm_with_tools.ainvoke(messages)
        messages.append(response)

        if not response.tool_calls:
            return response.content

        last_tool_result = ""
        for tool_call in response.tool_calls:
            tool = next((t for t in tools if t.name == tool_call["name"]), None)

            if tool is None:
                # LangChain 要求每个 tool_call_id 都有对应的 ToolMessage，缺失会报错
                messages.append(ToolMessage(
                    content=f"工具 {tool_call['name']} 未找到",
                    tool_call_id=tool_call["id"],
                ))
                continue

            tool_result = await tool.ainvoke(tool_call["args"])
            messages.append(ToolMessage(
                content=str(tool_result),
                tool_call_id=tool_call["id"],
            ))
            last_tool_result = str(tool_result)

        return last_tool_result

    return "Agent 迭代超限"


async def fetch_fresh_data(city: str, preferences: str, tools: list) -> tuple[str, str, str, str]:
    """依次运行 Agent 1-4，获取景点 / 天气 / 酒店 / 额外要求数据。"""
    pref_text = preferences or "热门"

    attractions_info = await run_single_agent(
        system_prompt="你是景点搜索专家。使用工具搜索景点。",
        user_query=f"搜索{city}的{pref_text}景点",
        tools=tools,
    )
    weather_info = await run_single_agent(
        system_prompt="你是天气查询专家。使用工具查询天气。",
        user_query=f"查询{city}的天气情况",
        tools=tools,
    )
    hotels_info = await run_single_agent(
        system_prompt="你是酒店推荐专家。使用工具搜索酒店。",
        user_query=f"搜索{city}的酒店",
        tools=tools,
    )
    extra_info = ""
    if preferences:
        extra_info = await run_single_agent(
            system_prompt="你是旅行信息搜索专家。根据用户的特殊需求，使用工具搜索相关的真实信息。",
            user_query=f"搜索{city}符合以下要求的旅行相关信息：{preferences}",
            tools=tools,
        )
    return attractions_info, weather_info, hotels_info, extra_info


async def extract_new_params(
    user_input: str,
    current_city: str,
    current_days: int,
    current_preferences: str,
) -> dict:
    """
    用 LLM 判断用户消息是否需要重新查询实时数据。
    返回结构：{"needs_refresh": bool, "city": str, "days": int, "preferences": str}
    """
    prompt = (
        "判断以下用户消息是否需要重新获取旅行数据（如换城市、换天数、换偏好等实质性变化）。\n"
        f"当前参数 — 城市：{current_city}，天数：{current_days}，偏好：{current_preferences or '无'}\n"
        f"用户消息：{user_input}\n\n"
        "如果需要重新查数据，返回：\n"
        '{"needs_refresh": true, "city": "新城市或原城市", "days": 新天数或原天数, "preferences": "新偏好或原偏好"}\n'
        "如果只是调整计划文字（顺序、措辞、餐厅建议等），返回：\n"
        '{"needs_refresh": false, "city": "原城市", "days": 原天数, "preferences": "原偏好"}\n'
        "只返回 JSON，不要其他内容。"
    )
    response = await llm.ainvoke([HumanMessage(content=prompt)])
    try:
        text = response.content.strip()
        if text.startswith("```"):
            text = text.split("```")[1]
            if text.startswith("json"):
                text = text[4:]
        return json.loads(text.strip())
    except Exception:
        return {
            "needs_refresh": False,
            "city": current_city,
            "days": current_days,
            "preferences": current_preferences,
        }


async def stream_planner(
    history: list,
    user_query: str,
    system_prompt: str = "",
) -> AsyncGenerator[str, None]:
    """
    Agent 4（规划师）的流式生成器。
    过滤 <think>...</think> 推理块，只推送可见内容给客户端。
    history 由调用方传入并原地追加，实现多轮对话上下文连续性。
    """
    if system_prompt and not history:
        history.append(SystemMessage(content=system_prompt))

    history.append(HumanMessage(content=user_query))

    full_response = ""
    visible_sent = 0

    async for chunk in llm.astream(history):
        if not chunk.content:
            continue
        full_response += chunk.content

        visible = re.sub(r"<think>.*?</think>", "", full_response, flags=re.DOTALL)
        visible = re.sub(r"<think>.*$", "", visible, flags=re.DOTALL)

        delta = visible[visible_sent:]
        if delta:
            visible_sent = len(visible)
            yield delta

    # 存入历史保留完整原始文本（含思考块），保证下一轮上下文完整
    history.append(AIMessage(content=full_response))
