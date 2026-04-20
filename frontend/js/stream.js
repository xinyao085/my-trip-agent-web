/**
 * 读取 /plan 的流式响应。
 *
 * 后端在流末尾附加协议标记：
 *   [SESSION_ID:xxx]  — 会话 ID
 *   [ERROR:xxx]       — 错误信息（HTTP 200 已发出，只能嵌在流里）
 *
 * @param {Response} response   fetch 返回的 Response 对象
 * @param {object}   callbacks
 * @param {Function} callbacks.onFirstChunk  第一个可见文字到达时调用（用于移除 loading 卡片）
 * @param {Function} callbacks.onDelta       每次新增文字时调用，参数为 delta 字符串
 * @returns {{ sessionId: string|null, finalText: string }}
 */
export async function consumePlanStream(response, { onFirstChunk, onDelta }) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer      = "";
  let prevVisible = "";
  let isFirst     = true;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    buffer += decoder.decode(value, { stream: true });

    // 从可见文本中临时去掉末尾的协议标记再计算 delta
    const visible = buffer
      .replace(/\n\n\[SESSION_ID:[^\]]+\]$/, "")
      .replace(/\n\n\[ERROR:[^\]]+\]$/, "");
    const delta = visible.slice(prevVisible.length);
    prevVisible = visible;
    if (!delta) continue;

    if (isFirst) { isFirst = false; onFirstChunk?.(); }
    onDelta(delta);
  }

  const errorMatch = buffer.match(/\[ERROR:([^\]]+)\]/);
  if (errorMatch) throw new Error(errorMatch[1]);

  const sidMatch  = buffer.match(/\[SESSION_ID:([^\]]+)\]/);
  const sessionId = sidMatch?.[1] ?? null;

  const finalText = buffer
    .replace(/\n\n\[SESSION_ID:[^\]]+\]$/, "")
    .replace(/\n\n\[ERROR:[^\]]+\]$/, "")
    .trim();

  return { sessionId, finalText };
}

/**
 * 读取 /chat 的流式响应（无协议标记，直接是纯文本流）。
 *
 * @param {Response} response
 * @param {object}   callbacks
 * @param {Function} callbacks.onDelta  每次新增文字时调用
 * @returns {{ finalText: string }}
 */
export async function consumeChatStream(response, { onDelta }) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let fullText = "";
  let prevLen  = 0;

  while (true) {
    const { done, value } = await reader.read();
    if (done) break;
    fullText += decoder.decode(value, { stream: true });
    const delta = fullText.slice(prevLen);
    prevLen = fullText.length;
    onDelta(delta);
  }

  return { finalText: fullText.trim() };
}