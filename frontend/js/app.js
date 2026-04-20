import { createApp, ref, reactive, nextTick } from "https://cdn.jsdelivr.net/npm/vue@3/dist/vue.esm-browser.prod.js";
import { marked }                              from "https://esm.sh/marked@14";
import { planTrip, chatWithAgent }             from "./api.js";
import { consumePlanStream, consumeChatStream } from "./stream.js";

// Agent 加载卡片的步骤配置（label 纯展示，延迟时间对应实际串行耗时估算）
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

    // ── UI 状态 ──────────────────────────────────────────────────
    const statusState = ref("idle");
    const statusText  = ref("就绪");
    const inputHint   = ref("建立会话后可继续对话 · Enter 换行，点击发送");

    // ── 消息列表 & Agent 步骤 ────────────────────────────────────
    const messages   = ref([]);
    const agentSteps = reactive(AGENT_STEPS.map(s => ({ ...s, state: "waiting" })));
    const messagesEl = ref(null);

    let agentTimers = [];
    let nextId      = 0;

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

      // 定时切换各步骤状态（估算值）
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

    /**
     * 创建一个流式文字更新器，绑定到一条响应式 AI 消息。
     * append(delta) — 追加增量文字
     * finish(text)  — 流结束，渲染最终 Markdown
     */
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

    // ── POST /plan ───────────────────────────────────────────────
    async function startPlan() {
      if (!city.value.trim()) { alert("请输入目标城市"); return; }
      if (isStreaming.value) return;

      const prefs = getPrefsText();
      addMessage("user", `📍 ${city.value}  ·  ${days.value} 天${prefs ? "  ·  " + prefs : ""}`);
      isStreaming.value = true;
      setStatus("loading", "Agent 工作中…");
      showAgentLoadingCard();

      const streamer = createStreamer();
      try {
        const res = await planTrip({ city: city.value, days: days.value, preferences: prefs });
        const { sessionId: sid, finalText } = await consumePlanStream(res, {
          onFirstChunk: removeAgentLoadingCard,
          onDelta:      (delta) => streamer.append(delta),
        });
        streamer.finish(finalText);
        if (sid) { sessionId.value = sid; enableChat(city.value, days.value, prefs); }
        setStatus("", "完成");
      } catch (e) {
        removeAgentLoadingCard();
        streamer.finish(`**请求失败：** ${e.message}`);
        setStatus("idle", "出错");
      } finally {
        isStreaming.value = false;
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

      const streamer = createStreamer();
      try {
        const res = await chatWithAgent({ sessionId: sessionId.value, message });
        const { finalText } = await consumeChatStream(res, {
          onDelta: (delta) => streamer.append(delta),
        });
        streamer.finish(finalText);
        setStatus("", "完成");
      } catch (e) {
        streamer.finish(`**请求失败：** ${e.message}`);
        setStatus("idle", "出错");
      } finally {
        isStreaming.value = false;
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
      inputHint.value = "建立会话后可继续对话 · Enter 换行，点击发送";
      setStatus("idle", "就绪");
    }

    function handleChatKeydown(e) {
      if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendChat(); }
    }

    return {
      city, days, extra, chatInput, isStreaming, chatEnabled,
      showResetBtn, showSessionInfo, sessionInfoText,
      statusState, statusText, inputHint,
      availableTags, selectedTags, messages, agentSteps, messagesEl,
      adjustDays, toggleTag, startPlan, sendChat, resetSession, handleChatKeydown,
    };
  },
}).mount("#app");