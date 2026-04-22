/**
 * 将 reader.read() 包装为可中断版本。
 * abort 触发时立即 reject，不在 handler 里调 reader.cancel()（避免竞态），
 * 由调用方在 catch 里负责 reader.cancel()。
 */
function abortableRead(reader, signal) {
  if (signal?.aborted) {
    return Promise.reject(new DOMException("Aborted", "AbortError"));
  }
  return new Promise((resolve, reject) => {
    const onAbort = () => reject(new DOMException("Aborted", "AbortError"));
    signal?.addEventListener("abort", onAbort, { once: true });
    reader.read().then(
      (result) => { signal?.removeEventListener("abort", onAbort); resolve(result); },
      (err)    => { signal?.removeEventListener("abort", onAbort); reject(err); },
    );
  });
}

/**
 * 读取 /plan 的流式响应。
 *
 * 后端在流末尾附加协议标记：
 *   [SESSION_ID:xxx]  — 会话 ID
 *   [ERROR:xxx]       — 错误信息
 *
 * @param {Response}     response
 * @param {object}       callbacks
 * @param {Function}     callbacks.onFirstChunk
 * @param {Function}     callbacks.onDelta
 * @param {AbortSignal}  callbacks.signal
 * @returns {{ sessionId: string|null, finalText: string, aborted?: boolean }}
 */
export async function consumePlanStream(response, { onFirstChunk, onDelta, signal }) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let buffer      = "";
  let prevVisible = "";
  let isFirst     = true;

  try {
    while (true) {
      const { done, value } = await abortableRead(reader, signal);
      if (done) break;
      buffer += decoder.decode(value, { stream: true });

      const visible = buffer
        .replace(/\n\n\[SESSION_ID:[^\]]+\]$/, "")
        .replace(/\n\n\[ERROR:[^\]]+\]$/, "");
      const delta = visible.slice(prevVisible.length);
      prevVisible = visible;
      if (!delta) continue;

      if (isFirst) { isFirst = false; onFirstChunk?.(); }
      onDelta(delta);
    }
  } catch (e) {
    reader.cancel();
    if (e.name === "AbortError") {
      return { sessionId: null, finalText: prevVisible.trim(), aborted: true };
    }
    throw e;
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
 * 读取 /chat 的流式响应。
 *
 * @param {Response}     response
 * @param {object}       callbacks
 * @param {Function}     callbacks.onDelta
 * @param {AbortSignal}  callbacks.signal
 * @returns {{ finalText: string, aborted?: boolean }}
 */
export async function consumeChatStream(response, { onDelta, signal }) {
  const reader  = response.body.getReader();
  const decoder = new TextDecoder();
  let fullText = "";
  let prevLen  = 0;

  try {
    while (true) {
      const { done, value } = await abortableRead(reader, signal);
      if (done) break;
      fullText += decoder.decode(value, { stream: true });
      const delta = fullText.slice(prevLen);
      prevLen = fullText.length;
      onDelta(delta);
    }
  } catch (e) {
    reader.cancel();
    if (e.name === "AbortError") {
      return { finalText: fullText.trim(), aborted: true };
    }
    throw e;
  }

  return { finalText: fullText.trim() };
}
