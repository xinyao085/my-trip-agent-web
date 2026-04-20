# 进程内字典存储会话，生产环境应换成 Redis 并设置 TTL
# 每条 session 保存：planner_history、tools、mcp_client、city、days、preferences
sessions: dict[str, dict] = {}
