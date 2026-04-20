"""
agents_react.py — 使用 LangGraph create_react_agent 替代手写工具循环的版本。

与 agents.py 的主要区别：
  - run_single_agent: 由 LangGraph ReAct Agent 托管工具调用循环（自动 Reason→Act→Observe）
  - stream_planner / fetch_fresh_data / extract_new_params: 逻辑不变，直接复用

对外接口（函数签名）与 agents.py 完全相同，可直接在 routes/trip.py 中替换导入：
    from ..agents_react import fetch_fresh_data, extract_new_params, stream_planner
"""

import json
import re
from typing import AsyncGenerator

from langchain_core.messages import HumanMessage, SystemMessage, AIMessage
from langgraph.prebuilt import create_react_agent

from .config import llm


async def run_single_agent(system_prompt: str, user_query: str, tools: list) -> str:
    """
    用 LangGraph ReAct Agent 运行单个工具调用任务。

    create_react_agent 内部自动处理：
      Thought → Tool Call → Observation → … → Final Answer
    默认最多递归 25 步（recursion_limit），此处限制为 10 步防止意外循环。

    返回最后一条 AIMessage 的文字内容；若 Agent 未生成文字则返回最后一条 ToolMessage。
    """
    if not tools:
        response = await llm.ainvoke([
            SystemMessage(content=system_prompt),
            HumanMessage(content=user_query),
        ])
        return response.content

    agent = create_react_agent(
        model=llm,
        tools=tools,
        # prompt 相当于 system prompt，在每轮消息前注入（langgraph 1.x 中 state_modifier 已改名）
        prompt=system_prompt,
    )

    result = await agent.ainvoke(
        {"messages": [HumanMessage(content=user_query)]},
        config={"recursion_limit": 10},
    )

    # result["messages"] 末尾是最终 AIMessage（Final Answer）
    messages = result["messages"]
    for msg in reversed(messages):
        if isinstance(msg, AIMessage) and msg.content:
            return msg.content
        # 若 LLM 以工具调用结束（极少见），退而返回最后一条工具结果
        if hasattr(msg, "content") and msg.content:
            return str(msg.content)

    return "Agent 未返回结果"


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
    规划师的流式生成器（不使用工具，纯 LLM 生成）。
    过滤 <think>...</think> 推理块，只推送可见内容给客户端。
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

    history.append(AIMessage(content=full_response))