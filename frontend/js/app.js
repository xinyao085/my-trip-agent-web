import { createApp, ref, reactive, nextTick } from "https://cdn.jsdelivr.net/npm/vue@3/dist/vue.esm-browser.prod.js";
import { marked }                              from "https://esm.sh/marked@14";
import { planTrip, chatWithAgent, fetchHistory, fetchConversation, deleteConversation } from "./api.js?v=4";
import { consumePlanStream, consumeChatStream } from "./stream.js?v=4";

const AGENT_STEPS = [
  { key: "1", label: "Agent 1 · 景点搜索", delay: 0     },
  { key: "2", label: "Agent 2 · 天气查询", delay: 5000  },
  { key: "3", label: "Agent 3 · 酒店搜索", delay: 10000 },
];

createApp({
  setup() {
    // ── 表单状态 ─────────────────────────────────────────────────
    const city         = ref("");
    const days         = ref(3);
    const extra        = ref("");
    const availableTags = ["历史文化", "自然风景", "美食", "购物", "艺术", "休闲", "亲子"];
    const selectedTags = ref([]);

    // ── 会话状态 ─────────────────────────────────────────────────
    const sessionId       = ref(null);
    const isStreaming     = ref(false);
    const chatEnabled     = ref(false);
    const chatInput       = ref("");
    const showResetBtn    = ref(false);
    const showSessionInfo = ref(false);
    const sessionInfoText = ref("");

    // ── 历史记录状态 ─────────────────────────────────────────────
    const historyItems      = ref([]);
    const isHistoryView     = ref(false);
    const viewingSessionId  = ref(null);

    // ── UI 状态 ──────────────────────────────────────────────────
    const statusState = ref("idle");
    const statusText  = ref("就绪");
    const inputHint   = ref("建立会话后可继续对话 · Enter 换行，点击发送");

    // ── 消息列表 & Agent 步骤 ────────────────────────────────────
    const messages   = ref([]);
    const agentSteps = reactive(AGENT_STEPS.map(s => ({ ...s, state: "waiting" })));
    const messagesEl = ref(null);

    let agentTimers      = [];
    let nextId           = 0;
    let abortController  = null;

    // ── 工具函数 ─────────────────────────────────────────────────
    function scrollBottom() {
      nextTick(() => {
        if (messagesEl.value) messagesEl.value.scrollTop = messagesEl.value.scrollHeight;
      });
    }

    function setStatus(state, text) {
      statusState.value = state;
      statusText.value  = text;
    }

    function adjustDays(delta) {
      days.value = Math.min(14, Math.max(1, days.value + delta));
    }

    function toggleTag(tag) {
      const idx = selectedTags.value.indexOf(tag);
      if (idx >= 0) selectedTags.value.splice(idx, 1);
      else selectedTags.value.push(tag);
    }

    function getPrefsText() {
      return [selectedTags.value.join("、"), extra.value.trim()].filter(Boolean).join("，");
    }

    function formatDate(dateStr) {
      if (!dateStr) return "";
      const d = new Date(dateStr.replace(" ", "T"));
      return `${d.getMonth() + 1}/${d.getDate()} ${String(d.getHours()).padStart(2, "0")}:${String(d.getMinutes()).padStart(2, "0")}`;
    }

    // ── 消息管理 ─────────────────────────────────────────────────
    function addMessage(role, content = "", opts = {}) {
      const msg = {
        id: nextId++, type: "message", role, content,
        isStreaming: false, isMarkdown: false, renderedContent: "",
        ...opts,
      };
      messages.value.push(msg);
      scrollBottom();
      return msg;
    }

    function showAgentLoadingCard() {
      messages.value.push({ id: nextId++, type: "agent-loading" });
      agentSteps.forEach((s, i) => { s.state = i === 0 ? "spinning" : "waiting"; });
      agentTimers = AGENT_STEPS.slice(1).map(({ delay }, idx) =>
        setTimeout(() => {
          agentSteps[idx].state     = "done";
          agentSteps[idx + 1].state = "spinning";
        }, delay)
      );
      scrollBottom();
    }

    function removeAgentLoadingCard() {
      agentTimers.forEach(clearTimeout);
      agentTimers = [];
      const idx = messages.value.findIndex(m => m.type === "agent-loading");
      if (idx >= 0) messages.value.splice(idx, 1);
    }

    function createStreamer() {
      let aiMsg       = null;
      let accumulated = "";
      return {
        append(delta) {
          if (!aiMsg) aiMsg = addMessage("ai", "", { isStreaming: true });
          accumulated += delta;
          aiMsg.content = accumulated;
          scrollBottom();
        },
        finish(finalText) {
          if (!aiMsg) aiMsg = addMessage("ai", "");
          aiMsg.isStreaming     = false;
          aiMsg.isMarkdown      = true;
          aiMsg.renderedContent = marked.parse(finalText || accumulated);
          scrollBottom();
        },
      };
    }

    // ── 中断流式响应 ─────────────────────────────────────────────
    function stopStreaming() {
      abortController?.abort();
    }

    // ── POST /plan ───────────────────────────────────────────────
    async function startPlan() {
      if (!city.value.trim()) { alert("请输入目标城市"); return; }
      if (isStreaming.value) return;
      if (isHistoryView.value) exitHistoryView();

      const prefs = getPrefsText();
      addMessage("user", `📍 ${city.value}  ·  ${days.value} 天${prefs ? "  ·  " + prefs : ""}`);
      isStreaming.value = true;
      setStatus("loading", "Agent 工作中…");
      showAgentLoadingCard();

      abortController = new AbortController();
      const streamer = createStreamer();
      try {
        const res = await planTrip(
          { city: city.value, days: days.value, preferences: prefs },
          abortController.signal,
        );
        const { sessionId: sid, finalText, aborted } = await consumePlanStream(res, {
          onFirstChunk: removeAgentLoadingCard,
          onDelta:      (delta) => streamer.append(delta),
          signal:       abortController.signal,
        });
        if (aborted) {
          removeAgentLoadingCard();
          streamer.finish((finalText || "") + "\n\n---\n*已中断*");
          setStatus("idle", "已中断");
        } else {
          streamer.finish(finalText);
          if (sid) { sessionId.value = sid; enableChat(city.value, days.value, prefs); }
          setStatus("", "完成");
          loadHistory();
        }
      } catch (e) {
        removeAgentLoadingCard();
        if (e.name === "AbortError") {
          streamer.finish("*已中断*");
          setStatus("idle", "已中断");
        } else {
          streamer.finish(`**请求失败：** ${e.message}`);
          setStatus("idle", "出错");
        }
      } finally {
        isStreaming.value = false;
        abortController   = null;
      }
    }

    // ── POST /chat ───────────────────────────────────────────────
    async function sendChat() {
      const message = chatInput.value.trim();
      if (!message || !sessionId.value || isStreaming.value) return;

      chatInput.value = "";
      addMessage("user", message);
      isStreaming.value = true;
      setStatus("loading", "思考中…");

      abortController = new AbortController();
      const streamer = createStreamer();
      try {
        const res = await chatWithAgent(
          { sessionId: sessionId.value, message },
          abortController.signal,
        );
        const { finalText, aborted } = await consumeChatStream(res, {
          onDelta: (delta) => streamer.append(delta),
          signal:  abortController.signal,
        });
        if (aborted) {
          streamer.finish((finalText || "") + "\n\n---\n*已中断*");
          setStatus("idle", "已中断");
        } else {
          streamer.finish(finalText);
          setStatus("", "完成");
          loadHistory();
        }
      } catch (e) {
        if (e.name === "AbortError") {
          streamer.finish("*已中断*");
          setStatus("idle", "已中断");
        } else {
          streamer.finish(`**请求失败：** ${e.message}`);
          setStatus("idle", "出错");
        }
      } finally {
        isStreaming.value = false;
        abortController   = null;
      }
    }

    // ── 历史记录 ─────────────────────────────────────────────────
    async function loadHistory() {
      try {
        historyItems.value = await fetchHistory();
      } catch (_) {
        // 静默失败，不影响主流程
      }
    }

    async function viewConversation(sid) {
      if (isStreaming.value) return;
      try {
        const data = await fetchConversation(sid);
        messages.value = data.map(m => ({
          id: nextId++,
          type: "message",
          role: m.role,
          content: m.content,
          isStreaming: false,
          isMarkdown: m.role === "ai",
          renderedContent: m.role === "ai" ? marked.parse(m.content) : "",
        }));
        isHistoryView.value    = true;
        viewingSessionId.value = sid;
        chatEnabled.value      = false;
        inputHint.value        = "正在查看历史记录 · 点击「退出历史」可返回";
        scrollBottom();
      } catch (e) {
        alert("加载历史对话失败：" + e.message);
      }
    }

    function resumeSession(sid) {
      if (!sid || isStreaming.value) return;
      sessionId.value    = sid;
      isHistoryView.value    = false;
      viewingSessionId.value = null;
      chatEnabled.value  = true;
      showResetBtn.value = true;
      showSessionInfo.value = true;
      sessionInfoText.value = "已恢复历史会话 · 可继续修改计划";
      inputHint.value = "Enter 换行，点击发送 · 可要求修改计划、换城市或调整天数";
    }

    function exitHistoryView() {
      isHistoryView.value    = false;
      viewingSessionId.value = null;
      messages.value         = [];
      if (sessionId.value) {
        chatEnabled.value = true;
        inputHint.value   = "Enter 换行，点击发送 · 可要求修改计划、换城市或调整天数";
      } else {
        chatEnabled.value = false;
        inputHint.value   = "建立会话后可继续对话 · Enter 换行，点击发送";
      }
    }

    async function deleteHistoryItem(sid) {
      try {
        await deleteConversation(sid);
        historyItems.value = historyItems.value.filter(i => i.session_id !== sid);
        if (viewingSessionId.value === sid) exitHistoryView();
      } catch (e) {
        alert("删除失败：" + e.message);
      }
    }

    // ── UI 状态切换 ──────────────────────────────────────────────
    function enableChat(c, d, prefs) {
      chatEnabled.value     = true;
      showResetBtn.value    = true;
      showSessionInfo.value = true;
      sessionInfoText.value = `会话已建立 · ${c} ${d}天${prefs ? " · " + prefs : ""}`;
      inputHint.value = "Enter 换行，点击发送 · 可要求修改计划、换城市或调整天数";
    }

    function resetSession() {
      sessionId.value   = null;
      isStreaming.value = false;
      messages.value    = [];
      chatEnabled.value = false;
      chatInput.value   = "";
      showResetBtn.value    = false;
      showSessionInfo.value = false;
      isHistoryView.value    = false;
      viewingSessionId.value = null;
      inputHint.value = "建立会话后可继续对话 · Enter 换行，点击发送";
      setStatus("idle", "就绪");
    }

    function handleChatKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
    }

    // 启动时加载历史
    loadHistory();

    return {
      city, days, extra, chatInput, isStreaming, chatEnabled,
      showResetBtn, showSessionInfo, sessionInfoText,
      statusState, statusText, inputHint,
      availableTags, selectedTags, messages, agentSteps, messagesEl,
      historyItems, isHistoryView, viewingSessionId,
      adjustDays, toggleTag, startPlan, sendChat, stopStreaming, resetSession, handleChatKeydown,
      loadHistory, viewConversation, resumeSession, exitHistoryView, deleteHistoryItem, formatDate,
    };
  },
}).mount("#app");