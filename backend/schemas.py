from pydantic import BaseModel, Field


class PlanRequest(BaseModel):
    city: str = Field(description="目标城市，例如：北京、上海、成都")
    days: int = Field(default=3, ge=1, le=14, description="旅行天数（1-14 天）")
    preferences: str = Field(default="", description="偏好，例如：历史文化、自然风景、美食")


class ChatRequest(BaseModel):
    session_id: str = Field(description="由 /plan 返回的会话 ID")
    message: str = Field(description="用户的追问或修改要求")
