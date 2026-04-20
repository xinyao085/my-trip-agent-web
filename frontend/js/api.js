const API_BASE = "http://localhost:8000";

/**
 * POST /plan — 首次规划，返回 streaming Response
 */
export async function planTrip({ city, days, preferences }) {
  const res = await fetch(`${API_BASE}/plan`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ city, days, preferences }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res;
}

/**
 * POST /chat — 多轮对话，返回 streaming Response
 */
export async function chatWithAgent({ sessionId, message }) {
  const res = await fetch(`${API_BASE}/chat`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ session_id: sessionId, message }),
  });
  if (!res.ok) {
    const err = await res.json();
    throw new Error(err.detail || `HTTP ${res.status}`);
  }
  return res;
}