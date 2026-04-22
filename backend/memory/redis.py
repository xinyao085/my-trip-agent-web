"""
memory/redis.py — Redis 持久化长期记忆模块

数据结构：
  conv:{session_id}   Hash   — 对话元数据 (city, days, preferences, created_at, updated_at)
  conv:index          Sorted Set — session_id → UNIX 时间戳，用于按时间倒序列表
  msg:{session_id}    List   — 消息 JSON 列表（按 RPUSH 顺序）

环境变量：REDIS_HOST / REDIS_PORT / REDIS_PASSWORD / REDIS_DB
"""

import json
import os
import time
from datetime import datetime

import redis.asyncio as aioredis

_redis: aioredis.Redis | None = None


def _get_redis() -> aioredis.Redis:
    global _redis
    if _redis is None:
        password = os.getenv("REDIS_PASSWORD") or None
        _redis = aioredis.Redis(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            password=password,
            db=int(os.getenv("REDIS_DB", 0)),
            decode_responses=True,
        )
    return _redis


def _now() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


async def ping() -> bool:
    """启动时检查 Redis 连通性，失败则抛出异常。"""
    await _get_redis().ping()
    return True


async def save_conversation(session_id: str, city: str, days: int, preferences: str) -> None:
    r = _get_redis()
    now = _now()
    await r.hset(f"conv:{session_id}", mapping={
        "city": city,
        "days": str(days),
        "preferences": preferences or "",
        "created_at": now,
        "updated_at": now,
    })
    await r.zadd("conv:index", {session_id: time.time()})


async def save_message(session_id: str, role: str, content: str) -> None:
    r = _get_redis()
    msg = json.dumps({"role": role, "content": content, "created_at": _now()}, ensure_ascii=False)
    await r.rpush(f"msg:{session_id}", msg)
    now = _now()
    await r.hset(f"conv:{session_id}", "updated_at", now)
    await r.zadd("conv:index", {session_id: time.time()})


async def get_conversations() -> list[dict]:
    r = _get_redis()
    session_ids = await r.zrevrange("conv:index", 0, -1)
    result = []
    for sid in session_ids:
        data = await r.hgetall(f"conv:{sid}")
        if data:
            result.append({
                "session_id": sid,
                "city": data.get("city", ""),
                "days": int(data.get("days", 0)),
                "preferences": data.get("preferences", ""),
                "created_at": data.get("created_at", ""),
                "updated_at": data.get("updated_at", ""),
            })
    return result


async def get_messages(session_id: str) -> list[dict]:
    r = _get_redis()
    raw = await r.lrange(f"msg:{session_id}", 0, -1)
    return [json.loads(m) for m in raw]


async def delete_conversation(session_id: str) -> None:
    r = _get_redis()
    await r.delete(f"conv:{session_id}", f"msg:{session_id}")
    await r.zrem("conv:index", session_id)
