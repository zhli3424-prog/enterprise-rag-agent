const $ = (selector) => document.querySelector(selector);
const state = { user: null, conversationId: null, busy: false };
const departments = { all: "全公司", engineering: "研发部", finance: "财务部" };

async function api(path, options = {}) {
  const response = await fetch(path, { credentials: "same-origin", ...options });
  if (!response.ok) {
    let message = `请求失败 (${response.status})`;
    try { message = (await response.json()).detail || message; } catch (_) {}
    throw new Error(message);
  }
  return response;
}

function showApp(user) {
  state.user = user;
  $("#login-view").classList.add("hidden");
  $("#app-view").classList.remove("hidden");
  $("#profile-name").textContent = user.username;
  $("#profile-meta").textContent = `${user.role === "admin" ? "管理员" : "员工"} · ${departments[user.department] || user.department}`;
  $("#avatar").textContent = user.username[0].toUpperCase();
  $("#upload-form").classList.toggle("hidden", user.role !== "admin");
  checkHealth();
  loadDocuments();
  loadConversations();
}

async function bootstrap() {
  try { showApp((await (await api("/api/auth/me")).json()).user); } catch (_) {}
}

$("#login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  $("#login-error").textContent = "";
  try {
    const response = await api("/api/auth/login", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ username: $("#username").value, password: $("#password").value })
    });
    showApp((await response.json()).user);
  } catch (error) { $("#login-error").textContent = error.message; }
});

document.querySelectorAll("[data-user]").forEach((button) => button.addEventListener("click", () => {
  $("#username").value = button.dataset.user;
  $("#password").value = button.dataset.password;
}));

$("#logout").addEventListener("click", async () => {
  await api("/api/auth/logout", { method: "POST" });
  location.reload();
});

document.querySelectorAll(".nav-item").forEach((button) => button.addEventListener("click", () => {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.remove("active"));
  button.classList.add("active");
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.add("hidden"));
  $(`#${button.dataset.panel}`).classList.remove("hidden");
  $("#page-title").textContent = button.dataset.panel === "chat-panel" ? "智能问答" : "知识文档";
}));

async function checkHealth() {
  const pill = $("#health-pill");
  try {
    const health = await (await api("/api/health")).json();
    pill.className = `health-pill ${health.deepseek_configured ? "ok" : "bad"}`;
    pill.querySelector("span").textContent = health.deepseek_configured ? "服务正常" : "缺少 DeepSeek Key";
  } catch (_) { pill.className = "health-pill bad"; pill.querySelector("span").textContent = "服务异常"; }
}

async function loadDocuments() {
  const body = $("#document-list");
  body.replaceChildren();
  try {
    const documents = (await (await api("/api/documents")).json()).documents;
    $("#empty-docs").classList.toggle("hidden", documents.length > 0);
    documents.forEach((item) => {
      const row = document.createElement("tr");
      const name = window.document.createElement("td");
      const strong = window.document.createElement("strong"); strong.textContent = item.title;
      const small = window.document.createElement("small"); small.textContent = item.filename;
      name.append(strong, small);
      const department = window.document.createElement("td"); department.textContent = departments[item.department] || item.department;
      const status = window.document.createElement("td"); const badge = window.document.createElement("span");
      badge.className = `badge ${item.status}`; badge.textContent = item.status; status.append(badge);
      const count = window.document.createElement("td"); count.textContent = String(item.chunk_count ?? 0);
      const actions = window.document.createElement("td");
      if (state.user.role === "admin") {
        const remove = window.document.createElement("button"); remove.className = "icon-button"; remove.textContent = "删除";
        remove.addEventListener("click", () => removeDocument(item.id, item.title)); actions.append(remove);
      }
      row.append(name, department, status, count, actions); body.append(row);
    });
  } catch (error) { $("#empty-docs").textContent = error.message; $("#empty-docs").classList.remove("hidden"); }
}

$("#refresh-docs").addEventListener("click", loadDocuments);

$("#upload-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  const status = $("#upload-status"); status.textContent = "正在上传…";
  try {
    await api("/api/documents", { method: "POST", body: new FormData(event.currentTarget) });
    status.textContent = "上传成功，Worker 正在建立索引。";
    event.currentTarget.reset(); loadDocuments();
  } catch (error) { status.textContent = error.message; }
});

async function removeDocument(id, title) {
  if (!confirm(`确认删除“${title}”及全部向量吗？`)) return;
  try { await api(`/api/documents/${id}`, { method: "DELETE" }); loadDocuments(); }
  catch (error) { alert(error.message); }
}

document.querySelectorAll(".suggestions button").forEach((button) => button.addEventListener("click", () => {
  $("#question").value = button.textContent; $("#question").focus();
}));

$("#question").addEventListener("input", (event) => {
  event.target.style.height = "auto";
  event.target.style.height = `${Math.min(event.target.scrollHeight, 140)}px`;
});
$("#question").addEventListener("keydown", (event) => {
  if (event.key === "Enter" && !event.shiftKey) { event.preventDefault(); $("#chat-form").requestSubmit(); }
});

function userMessage(text) {
  const node = document.createElement("div"); node.className = "message user"; node.textContent = text; $("#messages").append(node);
}

function assistantMessage() {
  const node = document.createElement("div"); node.className = "message assistant";
  const status = document.createElement("p"); status.className = "status-line"; status.textContent = "正在连接知识库…";
  const answer = document.createElement("div"); answer.className = "answer";
  const citations = document.createElement("div"); citations.className = "citations";
  const metrics = document.createElement("div"); metrics.className = "metrics";
  node.append(status, answer, citations, metrics); $("#messages").append(node);
  return { node, status, answer, citations, metrics };
}

function renderSources(container, sources) {
  container.replaceChildren();
  sources.forEach((source, index) => {
    const node = document.createElement("div"); node.className = "citation";
    const title = document.createElement("strong"); title.textContent = `[${index + 1}] ${source.title} · ${source.page ? `第 ${source.page} 页` : `片段 ${source.ordinal + 1}`}`;
    const excerpt = document.createElement("p"); excerpt.textContent = source.excerpt;
    node.append(title, excerpt); container.append(node);
  });
}

function showChatPanel() {
  document.querySelectorAll(".nav-item").forEach((item) => item.classList.toggle("active", item.dataset.panel === "chat-panel"));
  document.querySelectorAll(".panel").forEach((panel) => panel.classList.add("hidden"));
  $("#chat-panel").classList.remove("hidden");
  $("#page-title").textContent = "智能问答";
}

function newConversation() {
  if (state.busy) return;
  state.conversationId = null;
  $("#messages").replaceChildren();
  $("#welcome").classList.remove("hidden");
  document.querySelectorAll(".conversation-item").forEach((item) => item.classList.remove("active"));
  showChatPanel();
  $("#question").focus();
}

async function loadConversations() {
  const container = $("#conversation-list");
  container.replaceChildren();
  try {
    const conversations = (await (await api("/api/conversations")).json()).conversations;
    $("#empty-conversations").classList.toggle("hidden", conversations.length > 0);
    conversations.forEach((conversation) => {
      const button = document.createElement("button");
      button.type = "button";
      button.className = `conversation-item${conversation.id === state.conversationId ? " active" : ""}`;
      button.textContent = conversation.title;
      button.title = conversation.title;
      button.addEventListener("click", () => restoreConversation(conversation.id));
      container.append(button);
    });
  } catch (error) {
    $("#empty-conversations").textContent = error.message;
    $("#empty-conversations").classList.remove("hidden");
  }
}

async function restoreConversation(id) {
  if (state.busy) return;
  try {
    const data = await (await api(`/api/conversations/${id}`)).json();
    state.conversationId = data.conversation.id;
    $("#messages").replaceChildren();
    $("#welcome").classList.add("hidden");
    data.messages.forEach((message) => {
      if (message.role === "user") {
        userMessage(message.content);
      } else if (message.role === "assistant") {
        const assistant = assistantMessage();
        assistant.status.textContent = "";
        assistant.answer.textContent = message.content;
        renderSources(assistant.citations, message.citations || []);
      }
    });
    showChatPanel();
    loadConversations();
  } catch (error) {
    alert(error.message);
  }
}

$("#new-conversation").addEventListener("click", newConversation);

async function parseEventStream(response, handlers) {
  const reader = response.body.getReader(); const decoder = new TextDecoder(); let buffer = "";
  while (true) {
    const { value, done } = await reader.read(); buffer += decoder.decode(value || new Uint8Array(), { stream: !done });
    const blocks = buffer.split("\n\n"); buffer = blocks.pop();
    for (const block of blocks) {
      let event = "message", data = "";
      block.split("\n").forEach((line) => { if (line.startsWith("event: ")) event = line.slice(7); if (line.startsWith("data: ")) data += line.slice(6); });
      if (data && handlers[event]) handlers[event](JSON.parse(data));
    }
    if (done) break;
  }
}

$("#chat-form").addEventListener("submit", async (event) => {
  event.preventDefault(); if (state.busy) return;
  const question = $("#question").value.trim(); if (!question) return;
  state.busy = true; $(".send").disabled = true; $("#welcome").classList.add("hidden");
  userMessage(question); $("#question").value = ""; const assistant = assistantMessage();
  window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" });
  try {
    const response = await api("/api/chat/stream", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ question, conversation_id: state.conversationId })
    });
    await parseEventStream(response, {
      meta: (data) => {
        const created = state.conversationId === null;
        state.conversationId = data.conversation_id;
        if (created) loadConversations();
      },
      status: (data) => { assistant.status.textContent = data.message; },
      sources: (data) => renderSources(assistant.citations, data),
      delta: (data) => { assistant.answer.textContent += data.text; assistant.status.textContent = ""; },
      done: (data) => { const m = data.metrics || {}; assistant.metrics.textContent = `检索 ${m.retrieval_ms || 0} ms · 首字 ${m.first_token_ms || 0} ms · 总计 ${m.total_ms || 0} ms · Token ${(m.prompt_tokens || 0) + (m.completion_tokens || 0)}`; },
      error: (data) => { assistant.status.textContent = "请求失败"; assistant.answer.textContent = data.message; }
    });
  } catch (error) { assistant.status.textContent = "请求失败"; assistant.answer.textContent = error.message; }
  finally { state.busy = false; $(".send").disabled = false; window.scrollTo({ top: document.body.scrollHeight, behavior: "smooth" }); }
});

bootstrap();
