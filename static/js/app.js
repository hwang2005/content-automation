import { api } from "./api-client.js";

const $ = (id) => document.getElementById(id);
const state = {
  projects: [], formats: [], projectId: null, view: "writer", sourceType: "url",
  status: null, result: null, generating: false, historyPage: 1,
  editingProject: null, editingFormat: null,
};
let toastTimer;
let confirmResolve;
let workspaceVersion = 0;

function node(tag, text = "", className = "") {
  const item = document.createElement(tag);
  if (text) item.textContent = text;
  if (className) item.className = className;
  return item;
}

function icon(name) {
  const svg = document.createElementNS("http://www.w3.org/2000/svg", "svg");
  svg.classList.add("icon");
  svg.setAttribute("aria-hidden", "true");
  const use = document.createElementNS("http://www.w3.org/2000/svg", "use");
  use.setAttribute("href", `/static/icons.svg#${name}`);
  svg.append(use);
  return svg;
}

function actionButton(text, handler, className = "button secondary", iconName) {
  const button = node("button", "", className);
  button.type = "button";
  if (iconName) button.append(icon(iconName));
  if (text) button.append(document.createTextNode(text));
  button.addEventListener("click", () => {
    Promise.resolve(handler(button)).catch((error) => toast(error.message, true));
  });
  return button;
}

function toast(message, error = false) {
  $("toast").textContent = message;
  $("toast").classList.toggle("error", error);
  $("toast").hidden = false;
  clearTimeout(toastTimer);
  toastTimer = setTimeout(() => { $("toast").hidden = true; }, error ? 7500 : 3500);
}

function errorAt(id, message = "") {
  $(id).textContent = message;
  $(id).hidden = !message;
}

function currentProject() {
  return state.projects.find((project) => project.id === state.projectId);
}

function dirty() {
  return state.result && $("post-editor").value !== state.result.generated_content;
}

function rememberProject(id) {
  try { localStorage.setItem("studio-project", id || ""); } catch { /* Private mode. */ }
}

function rememberedProject() {
  try { return localStorage.getItem("studio-project"); } catch { return null; }
}

async function confirmAction(title, message, confirmLabel = "Xóa") {
  if (confirmResolve) return false;
  $("confirm-title").textContent = title;
  $("confirm-message").textContent = message;
  $("confirm-ok").textContent = confirmLabel;
  $("confirm-dialog").showModal();
  return new Promise((resolve) => { confirmResolve = resolve; });
}

function finishConfirm(value) {
  $("confirm-dialog").close();
  const resolve = confirmResolve;
  confirmResolve = null;
  resolve?.(value);
}

async function busy(button, work) {
  button.disabled = true;
  try { return await work(); } finally { button.disabled = false; }
}

function renderProjectSelector() {
  const select = $("project-select");
  select.replaceChildren();
  if (!state.projects.length) select.add(new Option("Chưa có dự án", ""));
  for (const project of state.projects) select.add(new Option(project.name, project.id));
  select.value = state.projectId || "";
  select.disabled = state.generating || !state.projects.length;
}

function renderView() {
  const hasProject = Boolean(currentProject());
  $("no-project").hidden = hasProject;
  for (const name of ["writer", "formats", "history"]) {
    $(`view-${name}`).hidden = !hasProject || state.view !== name;
  }
  for (const button of document.querySelectorAll("[data-view]")) {
    const active = button.dataset.view === state.view;
    button.classList.toggle("active", active);
    if (active) button.setAttribute("aria-current", "page");
    else button.removeAttribute("aria-current");
  }
}

async function navigate(view) {
  state.view = view;
  renderView();
  if (view === "formats" && state.projectId) renderFormats();
  if (view === "history" && state.projectId) await loadHistory(1);
}

function renderNotice() {
  const messages = [];
  if (state.status && !state.status.database_ready) messages.push("Chưa kết nối được database hoặc chưa chạy migration.");
  if (state.status && !state.status.openai_ready) messages.push("Chưa cấu hình OPENAI_API_KEY. Bạn vẫn có thể thiết lập dự án và dạng bài.");
  if (state.status?.environment === "development" && !state.status.password_enabled) messages.push("Chế độ local chưa bật mật khẩu. Hãy cấu hình APP_PASSWORD trước khi chia sẻ.");
  const notice = $("setup-notice");
  notice.replaceChildren();
  notice.hidden = !messages.length;
  if (messages.length) {
    notice.append(document.createTextNode(messages.join(" ")));
    notice.append(actionButton("Xem cấu hình", showSettings, ""));
  }
  const ready = state.status?.database_ready && state.status?.openai_ready;
  $("connection-badge").classList.toggle("connected", Boolean(ready));
  $("connection-badge").classList.toggle("attention", !ready);
  $("connection-text").textContent = ready ? "Studio sẵn sàng" : "Cần cấu hình";
  renderGenerateButton();
}

function renderGenerateButton() {
  const active = state.formats.filter((format) => format.is_active).length;
  $("generate-button").disabled = state.generating || !active || !state.status?.openai_ready || !state.projectId;
  $("generate-button").querySelector("span").textContent = state.generating ? "Studio đang viết…" : "Phân tích & viết bài";
  $("auto-format-description").textContent = active
    ? `${active} dạng bài đang bật trong dự án này`
    : "Chưa có dạng bài đang bật — hãy thêm ở mục Dạng bài";
  $("nav-format-count").textContent = state.formats.length;
  $("project-select").disabled = state.generating || !state.projects.length;
  $("new-project-button").disabled = state.generating;
  $("edit-project-button").disabled = state.generating;
  $("add-format-button").disabled = state.generating;
  $("starter-formats-button").disabled = state.generating;
}

async function loadProjects(preferred = state.projectId) {
  state.projects = await api("/projects");
  state.projectId = state.projects.some((project) => project.id === preferred)
    ? preferred : state.projects[0]?.id || null;
  rememberProject(state.projectId);
  renderProjectSelector();
}

async function loadFormats() {
  const version = ++workspaceVersion;
  const id = state.projectId;
  const formats = id ? await api(`/projects/${id}/formats`) : [];
  if (version !== workspaceVersion || id !== state.projectId) return;
  state.formats = formats;
  renderGenerateButton();
  renderFormats();
}

async function selectProject(id) {
  if (state.generating) return;
  if (dirty() && !(await confirmAction("Bỏ sửa đổi chưa lưu?", "Bài viết hiện tại có thay đổi chưa được lưu.", "Bỏ sửa đổi"))) {
    $("project-select").value = state.projectId;
    return;
  }
  state.projectId = id;
  state.result = null;
  state.formats = [];
  rememberProject(id);
  resetResult();
  errorAt("generate-error");
  renderProjectSelector();
  renderView();
  renderGenerateButton();
  try {
    await loadFormats();
    if (state.view === "history") await loadHistory(1);
  } catch (error) { toast(error.message, true); }
}

function resetResult() {
  $("result-empty").hidden = false;
  $("result-loading").hidden = true;
  $("result-content").hidden = true;
  $("result-state").textContent = "Bản nháp";
  $("result-state").className = "pill neutral";
}

function safeLink(value) {
  try {
    const parsed = new URL(value);
    return ["http:", "https:"].includes(parsed.protocol) ? parsed.href : null;
  } catch { return null; }
}

function renderEvidence(post) {
  const list = $("evidence-list");
  list.replaceChildren();
  for (const source of post.sources || []) {
    const card = node("div", "", "source-evidence");
    const url = safeLink(source.url);
    if (url) {
      const link = node("a", source.title);
      link.href = url;
      link.target = "_blank";
      link.rel = "noopener noreferrer";
      card.append(link);
    } else card.append(node("strong", source.title));
    card.append(node("p", `${source.id} · ${url ? new URL(url).hostname : "Nội dung được dán thủ công"}`));
    list.append(card);
  }
  for (const fact of post.facts?.items || []) {
    const item = node("div", "", "fact-item");
    item.append(node("strong", `${fact.label}: `), document.createTextNode(fact.value));
    if (fact.quote) item.append(node("blockquote", fact.quote));
    item.append(node("span", fact.source_id, "fact-source"));
    list.append(item);
  }
  const meta = node("p", `${post.model} · ${number(post.input_tokens)} input / ${number(post.output_tokens)} output tokens · Mức phù hợp do AI tự đánh giá: ${Math.round(post.confidence * 100)}% (không phải xác suất đã hiệu chuẩn).`, "input-hint");
  list.append(meta);
}

function number(value) { return new Intl.NumberFormat("vi-VN").format(value || 0); }

function renderResult(post) {
  state.result = post;
  $("result-empty").hidden = true;
  $("result-loading").hidden = true;
  $("result-content").hidden = false;
  $("selected-format-name").textContent = post.selected_format_name;
  $("selection-reason").textContent = post.selection_reason;
  $("post-editor").value = post.generated_content;
  $("result-state").textContent = "Đã lưu";
  $("result-state").className = "pill active";
  $("save-post-button").disabled = true;
  updateEditorCount();
  const warnings = $("post-warnings");
  warnings.replaceChildren();
  warnings.hidden = !post.warnings?.length;
  if (post.warnings?.length) {
    warnings.append(node("strong", "Lưu ý trước khi đăng"));
    const list = node("ul");
    post.warnings.forEach((warning) => list.append(node("li", warning)));
    warnings.append(list);
  }
  renderEvidence(post);
}

function updateEditorCount() {
  $("post-char-count").textContent = `${number($("post-editor").value.length)} ký tự`;
  $("save-post-button").disabled = !dirty() || !$("post-editor").value.trim();
  if (state.result) {
    $("result-state").textContent = dirty() ? "Chưa lưu sửa đổi" : "Đã lưu";
    $("result-state").className = dirty() ? "pill neutral" : "pill active";
  }
}

function sourceTab(type) {
  state.sourceType = type;
  for (const button of document.querySelectorAll("[data-source]")) {
    const active = button.dataset.source === type;
    button.classList.toggle("active", active);
    button.setAttribute("aria-selected", String(active));
    button.tabIndex = active ? 0 : -1;
  }
  $("url-source").hidden = type !== "url";
  $("facebook-source").hidden = type !== "facebook_paste";
  $("source-url").required = type === "url";
  $("source-url").disabled = type !== "url";
  $("source-text").required = type !== "url";
  $("source-text").disabled = type === "url";
  $("source-text").minLength = type === "url" ? 0 : 30;
  errorAt("generate-error");
}

async function generate(event) {
  event.preventDefault();
  if (state.generating || !state.projectId) return;
  if (dirty() && !(await confirmAction("Viết bài mới?", "Sửa đổi chưa lưu của bài hiện tại sẽ không được giữ lại.", "Tiếp tục"))) return;
  const projectId = state.projectId;
  const payload = {
    project_id: projectId, source_type: state.sourceType,
    source_url: state.sourceType === "url" ? $("source-url").value.trim() : null,
    source_text: state.sourceType === "facebook_paste" ? $("source-text").value.trim() : "",
    follow_related: $("follow-related").checked,
    additional_instructions: $("additional-instructions").value.trim(),
  };
  errorAt("generate-error");
  state.generating = true;
  renderGenerateButton();
  $("result-empty").hidden = true;
  $("result-content").hidden = true;
  $("result-loading").hidden = false;
  $("result-state").textContent = "Đang viết";
  $("result-panel")?.setAttribute("aria-busy", "true");
  try {
    const result = await api("/generate", { method: "POST", body: payload, timeout: 345000 });
    renderResult(result);
    const project = currentProject();
    if (project) project.post_count += 1;
    toast("Bài viết đã được tạo và lưu vào lịch sử.");
  } catch (error) {
    errorAt("generate-error", error.message);
    if (state.result) renderResult(state.result);
    else resetResult();
  } finally {
    state.generating = false;
    $("result-loading").hidden = true;
    $("result-panel")?.removeAttribute("aria-busy");
    renderGenerateButton();
  }
}

function openProjectEditor(project = null) {
  if (state.generating) return;
  state.editingProject = project?.id || null;
  $("project-dialog-title").textContent = project ? "Chỉnh sửa dự án" : "Tạo dự án mới";
  $("project-name").value = project?.name || "";
  $("project-description").value = project?.description || "";
  $("project-guide").value = project?.writing_guide || "";
  $("delete-project-button").hidden = !project;
  errorAt("project-form-error");
  $("project-dialog").showModal();
  $("project-name").focus();
}

async function saveProject(event) {
  event.preventDefault();
  errorAt("project-form-error");
  const button = event.submitter;
  try {
    await busy(button, async () => {
      const editing = state.editingProject;
      const item = await api(editing ? `/projects/${editing}` : "/projects", {
        method: editing ? "PUT" : "POST",
        body: { name: $("project-name").value.trim(), description: $("project-description").value.trim(), writing_guide: $("project-guide").value.trim() },
      });
      $("project-dialog").close();
      if (!editing) { state.result = null; resetResult(); state.view = "formats"; }
      await loadProjects(item.id);
      await loadFormats();
      renderView();
      toast(editing ? "Đã cập nhật dự án." : "Đã tạo dự án. Thêm dạng bài để bắt đầu nhé!");
    });
  } catch (error) { errorAt("project-form-error", error.message); }
}

async function deleteProject() {
  const item = state.projects.find((project) => project.id === state.editingProject);
  if (!item || !(await confirmAction("Xóa dự án này?", `“${item.name}” cùng toàn bộ dạng bài và lịch sử sẽ bị xóa vĩnh viễn.`))) return;
  try {
    await api(`/projects/${item.id}`, { method: "DELETE" });
    $("project-dialog").close();
    state.result = null;
    resetResult();
    await loadProjects();
    await loadFormats();
    renderView();
    if (state.view === "history" && state.projectId) await loadHistory(1);
    toast("Đã xóa dự án.");
  } catch (error) { errorAt("project-form-error", error.message); }
}

function formatPayload(format) {
  return Object.fromEntries(["name", "description", "structure", "writing_guide", "samples", "detection_keywords", "is_active"].map((key) => [key, format[key]]));
}

function renderFormats() {
  const project = currentProject();
  $("guide-project-name").textContent = project?.name || "";
  $("guide-project-description").textContent = project?.writing_guide || project?.description || "Chưa có hướng dẫn chung. Thêm giọng văn và nguyên tắc để mọi bài viết nhất quán hơn.";
  $("formats-count").textContent = state.formats.length;
  $("formats-empty").hidden = Boolean(state.formats.length);
  const grid = $("format-grid");
  grid.replaceChildren();
  for (const format of state.formats) {
    const card = node("article", "", "format-card");
    const head = node("div", "", "format-card-head");
    head.append(icon("layers"), node("h3", format.name), node("span", format.is_active ? "Đang bật" : "Tạm dừng", `pill ${format.is_active ? "active" : "inactive"}`));
    card.append(head, node("p", format.description || format.structure));
    const footer = node("div", "", "format-card-footer");
    footer.append(node("span", `${format.samples.length} bài mẫu`));
    const toggle = actionButton(format.is_active ? "Tạm dừng" : "Bật lại", async (button) => {
      if (state.generating) return toast("Hãy đợi bài viết hiện tại hoàn thành.");
      await busy(button, async () => {
        await api(`/projects/${state.projectId}/formats/${format.id}`, { method: "PUT", body: { ...formatPayload(format), is_active: !format.is_active } });
        await loadFormats();
      });
    });
    const edit = actionButton("Chỉnh sửa", () => openFormatEditor(format), "button secondary", "pen");
    const remove = actionButton("", async () => {
      if (state.generating) return toast("Hãy đợi bài viết hiện tại hoàn thành.");
      if (!(await confirmAction("Xóa dạng bài?", `Xóa “${format.name}”? Các bài đã tạo vẫn được giữ trong lịch sử.`))) return;
      await api(`/projects/${state.projectId}/formats/${format.id}`, { method: "DELETE" });
      await loadFormats();
      toast("Đã xóa dạng bài.");
    }, "icon-button", "trash");
    remove.setAttribute("aria-label", `Xóa dạng bài ${format.name}`);
    footer.append(toggle, edit, remove);
    card.append(footer);
    grid.append(card);
  }
}

function addSample(text = "") {
  const container = $("samples-list");
  if (container.children.length >= 8) return toast("Mỗi dạng bài hỗ trợ tối đa 8 bài mẫu.");
  const item = node("div", "", "sample-item");
  const top = node("div", "", "sample-item-top");
  const label = node("label", "Bài mẫu");
  const textarea = node("textarea");
  textarea.rows = 5;
  textarea.maxLength = 10000;
  textarea.value = text;
  textarea.placeholder = "Dán bài viết mẫu tại đây. AI chỉ tham khảo phong cách, không dùng dữ kiện của bài mẫu cho chương trình mới.";
  textarea.id = `sample-${crypto.randomUUID()}`;
  label.htmlFor = textarea.id;
  const remove = actionButton("", () => { item.remove(); renumberSamples(); }, "icon-button", "close");
  remove.setAttribute("aria-label", "Xóa bài mẫu này");
  top.append(label, remove);
  item.append(top, textarea);
  container.append(item);
  renumberSamples();
}

function renumberSamples() {
  [...$("samples-list").children].forEach((item, i) => { item.querySelector("label").textContent = `Bài mẫu ${i + 1}`; });
  $("add-sample-button").disabled = $("samples-list").children.length >= 8;
}

function openFormatEditor(format = null) {
  if (state.generating || !state.projectId) return;
  state.editingFormat = format?.id || null;
  $("format-dialog-title").textContent = format ? "Chỉnh sửa dạng bài" : "Thêm dạng bài";
  $("format-name").value = format?.name || "";
  $("format-description").value = format?.description || "";
  $("format-keywords").value = format?.detection_keywords.join(", ") || "";
  $("format-structure").value = format?.structure || "";
  $("format-guide").value = format?.writing_guide || "";
  $("format-active").checked = format?.is_active ?? true;
  $("samples-list").replaceChildren();
  for (const sample of format?.samples || []) addSample(sample);
  if (!format?.samples?.length) addSample();
  errorAt("format-form-error");
  $("format-dialog").showModal();
  $("format-name").focus();
}

async function saveFormat(event) {
  event.preventDefault();
  errorAt("format-form-error");
  const payload = {
    name: $("format-name").value.trim(), description: $("format-description").value.trim(),
    structure: $("format-structure").value.trim(), writing_guide: $("format-guide").value.trim(),
    samples: [...$("samples-list").querySelectorAll("textarea")].map((item) => item.value.trim()).filter(Boolean),
    detection_keywords: [...new Set($("format-keywords").value.split(",").map((item) => item.trim()).filter(Boolean))],
    is_active: $("format-active").checked,
  };
  try {
    await busy(event.submitter, async () => {
      const path = `/projects/${state.projectId}/formats${state.editingFormat ? `/${state.editingFormat}` : ""}`;
      await api(path, { method: state.editingFormat ? "PUT" : "POST", body: payload });
      $("format-dialog").close();
      await loadFormats();
      toast("Đã lưu dạng bài và hướng dẫn.");
    });
  } catch (error) { errorAt("format-form-error", error.message); }
}

async function starterFormats() {
  try {
    await busy($("starter-formats-button"), async () => {
      await api(`/projects/${state.projectId}/starter-formats`, { method: "POST" });
      await loadFormats();
      toast("Đã thêm 3 dạng gợi ý. Chỉnh hướng dẫn và bổ sung bài mẫu của bạn nhé.");
    });
  } catch (error) { toast(error.message, true); }
}

function dateLabel(value) {
  // SQLite development timestamps may not include a timezone; they are stored as UTC.
  const normalized = /Z$|[+-]\d\d:\d\d$/.test(value) ? value : `${value}Z`;
  return new Intl.DateTimeFormat("vi-VN", { dateStyle: "medium", timeStyle: "short" }).format(new Date(normalized));
}

async function loadHistory(page = 1) {
  const projectId = state.projectId;
  if (!projectId) return;
  try {
    const data = await api(`/projects/${projectId}/posts?page=${page}&page_size=12`);
    if (state.projectId !== projectId) return;
    state.historyPage = data.page;
    $("history-empty").hidden = data.total > 0;
    $("history-pagination").hidden = data.total <= data.page_size;
    $("history-prev").disabled = page <= 1;
    $("history-next").disabled = page * data.page_size >= data.total;
    $("history-page-label").textContent = `Trang ${page} / ${Math.max(1, Math.ceil(data.total / data.page_size))}`;
    const list = $("history-list");
    list.replaceChildren();
    for (const post of data.items) {
      const card = node("article", "", "history-card");
      const head = node("div", "", "history-card-top");
      const time = node("time", dateLabel(post.created_at));
      time.dateTime = post.created_at;
      head.append(node("span", post.selected_format_name, "pill active"), time);
      card.append(head, node("h3", post.source_title), node("p", post.generated_content, "history-preview"));
      const actions = node("div", "", "history-card-actions");
      actions.append(node("span", post.source_type === "url" ? "Nguồn website" : "Nội dung đã dán", "small muted"));
      const open = actionButton("Mở & chỉnh sửa", async (button) => {
        if (state.generating) return toast("Hãy đợi bài đang viết hoàn thành.");
        if (dirty() && !(await confirmAction("Bỏ sửa đổi chưa lưu?", "Mở bài khác sẽ thay thế nội dung đang chỉnh sửa.", "Tiếp tục"))) return;
        await busy(button, async () => {
          const full = await api(`/projects/${projectId}/posts/${post.id}`);
          if (state.projectId !== projectId) return;
          renderResult(full);
          await navigate("writer");
          $("result-heading").scrollIntoView({ behavior: "smooth", block: "center" });
        });
      }, "button secondary", "pen");
      const remove = actionButton("", async () => {
        if (!(await confirmAction("Xóa bài viết?", "Bài viết này sẽ bị xóa vĩnh viễn khỏi lịch sử."))) return;
        await api(`/projects/${projectId}/posts/${post.id}`, { method: "DELETE" });
        if (state.result?.id === post.id) { state.result = null; resetResult(); }
        const newPage = data.items.length === 1 && page > 1 ? page - 1 : page;
        await loadHistory(newPage);
        toast("Đã xóa bài viết.");
      }, "icon-button", "trash");
      remove.setAttribute("aria-label", "Xóa bài viết này");
      actions.append(open, remove);
      card.append(actions);
      list.append(card);
    }
  } catch (error) { toast(error.message, true); }
}

async function savePost() {
  if (!state.result) return;
  const post = state.result;
  const content = $("post-editor").value;
  try {
    await busy($("save-post-button"), async () => {
      const result = await api(`/projects/${post.project_id}/posts/${post.id}`, { method: "PATCH", body: { generated_content: content } });
      if (state.result?.id === result.id) {
        const pendingEdits = $("post-editor").value;
        renderResult(result);
        if (pendingEdits !== content) {
          $("post-editor").value = pendingEdits;
          updateEditorCount();
        }
      }
      toast("Đã lưu sửa đổi.");
    });
  } catch (error) { toast(error.message, true); }
  updateEditorCount();
}

async function copyPost() {
  const content = $("post-editor").value;
  if (!content) return;
  try {
    await navigator.clipboard.writeText(content);
    toast("Đã sao chép văn bản thuần & emoji.");
  } catch {
    $("post-editor").focus();
    $("post-editor").select();
    toast("Không truy cập được clipboard. Bài viết đã được chọn; nhấn Ctrl/Cmd + C.");
  }
}

function downloadPost() {
  if (!state.result) return;
  const blob = new Blob([$("post-editor").value], { type: "text/plain;charset=utf-8" });
  const url = URL.createObjectURL(blob);
  const anchor = node("a");
  anchor.href = url;
  anchor.download = `bai-viet-${state.result.id.slice(0, 8)}.txt`;
  document.body.append(anchor);
  anchor.click();
  anchor.remove();
  setTimeout(() => URL.revokeObjectURL(url), 1000);
}

async function updateStatus() {
  state.status = await api("/status");
  renderNotice();
  const container = $("settings-status");
  container.replaceChildren();
  const rows = [
    ["Database", state.status.database_ready ? state.status.database_type : "Chưa sẵn sàng"],
    ["OpenAI", state.status.openai_ready ? "Đã cấu hình API key" : "Chưa có API key"],
    ["Mô hình", state.status.model],
    ["Môi trường", state.status.environment === "production" ? "Render / Production" : "Local / Development"],
    ["Bảo vệ truy cập", state.status.password_enabled ? "Mật khẩu không gian làm việc" : "Chưa bật (chỉ dùng local)"],
  ];
  for (const [label, value] of rows) {
    const row = node("div", "", "status-row");
    row.append(node("span", label), node("strong", value));
    container.append(row);
  }
  if (state.status.password_enabled) {
    container.append(actionButton("Đăng xuất khỏi không gian làm việc", logout, "button secondary"));
  }
}

async function showSettings() {
  if (!$("settings-dialog").open) $("settings-dialog").showModal();
  try { await updateStatus(); } catch (error) { toast(error.message, true); }
}

function showLogin(message = "") {
  $("app-shell").hidden = true;
  $("login-screen").hidden = false;
  errorAt("login-error", message);
}

async function bootstrap() {
  $("boot-error").hidden = true;
  try {
    const session = await api("/session");
    if (!session.auth_configured) {
      showLogin("Máy chủ chưa cấu hình APP_PASSWORD (ít nhất 12 ký tự) và SESSION_SECRET (ít nhất 32 ký tự). Cập nhật trên Render trước khi đăng nhập.");
      return;
    }
    if (!session.authenticated) { showLogin(); return; }
    $("login-screen").hidden = true;
    $("app-shell").hidden = false;
    $("logout-button").hidden = !session.password_required;
    await updateStatus();
    if (state.status.database_ready) {
      await loadProjects(state.projectId || rememberedProject());
      await loadFormats();
    }
    renderView();
    if (state.view === "history" && state.projectId) await loadHistory(1);
  } catch (error) {
    $("app-shell").hidden = true;
    $("login-screen").hidden = true;
    $("boot-error").hidden = false;
    $("boot-error-message").textContent = error.message;
  }
}

document.querySelectorAll("[data-view]").forEach((button) => button.addEventListener("click", () => navigate(button.dataset.view)));
document.querySelectorAll("[data-source]").forEach((button) => {
  button.addEventListener("click", () => sourceTab(button.dataset.source));
  button.addEventListener("keydown", (event) => {
    if (!["ArrowLeft", "ArrowRight"].includes(event.key)) return;
    event.preventDefault();
    const next = state.sourceType === "url" ? "facebook_paste" : "url";
    sourceTab(next);
    document.querySelector(`[data-source="${next}"]`).focus();
  });
});
document.querySelectorAll("[data-close-dialog]").forEach((button) => button.addEventListener("click", () => button.closest("dialog").close()));
$("confirm-cancel").addEventListener("click", () => finishConfirm(false));
$("confirm-ok").addEventListener("click", () => finishConfirm(true));
$("confirm-dialog").addEventListener("cancel", (event) => { event.preventDefault(); finishConfirm(false); });
$("project-select").addEventListener("change", (event) => selectProject(event.target.value));
$("new-project-button").addEventListener("click", () => openProjectEditor());
$("first-project-button").addEventListener("click", () => openProjectEditor());
$("edit-project-button").addEventListener("click", () => openProjectEditor(currentProject()));
$("project-form").addEventListener("submit", saveProject);
$("delete-project-button").addEventListener("click", deleteProject);
$("add-format-button").addEventListener("click", () => openFormatEditor());
$("format-form").addEventListener("submit", saveFormat);
$("add-sample-button").addEventListener("click", () => addSample());
$("starter-formats-button").addEventListener("click", starterFormats);
$("generate-form").addEventListener("submit", generate);
$("source-text").addEventListener("input", () => { $("source-char-count").textContent = `${number($("source-text").value.length)} / 50.000`; });
$("post-editor").addEventListener("input", updateEditorCount);
$("save-post-button").addEventListener("click", savePost);
$("copy-button").addEventListener("click", copyPost);
$("download-button").addEventListener("click", downloadPost);
$("sidebar-guide").addEventListener("click", () => navigate("formats"));
$("history-new-button").addEventListener("click", () => navigate("writer"));
$("history-prev").addEventListener("click", () => loadHistory(state.historyPage - 1));
$("history-next").addEventListener("click", () => loadHistory(state.historyPage + 1));
$("settings-button").addEventListener("click", showSettings);
$("refresh-status-button").addEventListener("click", async () => {
  try {
    await busy($("refresh-status-button"), async () => {
      await updateStatus();
      if (state.status.database_ready) {
        await loadProjects();
        await loadFormats();
        renderView();
      }
      toast("Đã cập nhật trạng thái.");
    });
  } catch (error) { toast(error.message, true); }
});
$("login-form").addEventListener("submit", async (event) => {
  event.preventDefault();
  errorAt("login-error");
  try {
    await busy(event.submitter, async () => {
      await api("/login", { method: "POST", body: { password: $("login-password").value } });
      $("login-password").value = "";
      await bootstrap();
    });
  } catch (error) { errorAt("login-error", error.message); }
});
async function logout() {
  if (state.generating) return toast("Hãy đợi bài đang viết hoàn thành.");
  if (dirty() && !(await confirmAction("Đăng xuất?", "Các chỉnh sửa chưa lưu sẽ bị bỏ lại.", "Đăng xuất"))) return;
  try {
    await api("/logout", { method: "POST" });
    // Do not leave workspace content behind the login overlay.
    window.location.reload();
  } catch (error) { toast(error.message, true); }
}
$("logout-button").addEventListener("click", logout);
$("retry-boot").addEventListener("click", bootstrap);
window.addEventListener("session-expired", () => {
  for (const dialog of document.querySelectorAll("dialog[open]")) dialog.close();
  showLogin("Phiên làm việc đã hết hạn. Vui lòng đăng nhập lại.");
});
window.addEventListener("beforeunload", (event) => {
  if (state.generating || dirty()) { event.preventDefault(); event.returnValue = ""; }
});
document.addEventListener("keydown", (event) => {
  if (event.key.toLowerCase() !== "n" || event.ctrlKey || event.metaKey || event.altKey) return;
  if (["INPUT", "TEXTAREA", "SELECT"].includes(document.activeElement.tagName) || document.querySelector("dialog[open]")) return;
  navigate("writer");
});
sourceTab("url");
bootstrap();
