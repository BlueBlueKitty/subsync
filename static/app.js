async function apiGet(url) {
  const response = await fetch(url, { credentials: "same-origin" });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(data.detail || "请求失败");
  }
  return response.json();
}

async function apiPost(url, options = {}) {
  const response = await fetch(url, { credentials: "same-origin", ...options });
  if (!response.ok) {
    const data = await response.json().catch(() => ({ detail: "请求失败" }));
    throw new Error(data.detail || "请求失败");
  }
  return response.json();
}

function debounce(fn, wait) {
  let timer = null;
  return (...args) => {
    clearTimeout(timer);
    timer = setTimeout(() => fn(...args), wait);
  };
}

function updateSubtitleMatchHint(message, isError = false) {
  const hint = document.getElementById("subtitle-match-hint");
  if (!hint) return;
  hint.textContent = message;
  hint.classList.toggle("error-text", isError);
}

function buildDefaultOutputName(videoPath, subtitleName) {
  if (!videoPath) {
    return "默认输出到视频所在目录，并优先使用视频文件名。";
  }
  const videoName = videoPath.split("/").pop() || "";
  const stem = videoName.includes(".") ? videoName.slice(0, videoName.lastIndexOf(".")) : videoName;
  let ext = ".srt";
  if (subtitleName && subtitleName.includes(".")) {
    ext = subtitleName.slice(subtitleName.lastIndexOf("."));
  }
  return `默认输出为 ${stem}${ext}，若已存在则自动追加 2、3...`;
}

function updateOutputPreview() {
  const form = document.getElementById("task-form");
  const outputInput = document.getElementById("output_name");
  const preview = document.getElementById("output-preview");
  if (!form || !outputInput || !preview) return;
  if (outputInput.value.trim()) {
    preview.textContent = `将输出为 ${outputInput.value.trim()}`;
    return;
  }
  const subtitleMode = form.querySelector('input[name="subtitle_mode"]:checked')?.value || "media";
  const subtitleName = subtitleMode === "upload"
    ? document.getElementById("subtitle_file").files[0]?.name
    : form.subtitle_path.value;
  preview.textContent = buildDefaultOutputName(form.video_path.value, subtitleName || "");
}

function getBrowserState(browser) {
  if (!browser._state) {
    browser._state = {
      dir: "",
      search: "",
      sort_by: "name",
      order: "asc",
      requestId: 0,
    };
  }
  return browser._state;
}

function renderBreadcrumbs(browser, breadcrumbs) {
  const container = browser.querySelector(".breadcrumbs");
  container.innerHTML = "";
  for (const crumb of breadcrumbs) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "crumb";
    button.textContent = crumb.name;
    button.onclick = () => loadBrowser(browser, crumb.path);
    container.appendChild(button);
  }
}

function renderBrowser(browser, payload) {
  const entries = browser.querySelector(".entries");
  renderBreadcrumbs(browser, payload.breadcrumbs);
  entries.innerHTML = "";
  for (const dir of payload.directories) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "entry dir";
    button.innerHTML = `<span>📁 ${dir.name}</span>`;
    button.onclick = () => loadBrowser(browser, dir.path);
    entries.appendChild(button);
  }
  if (browser.dataset.role !== "shift-output-dir") {
    for (const file of payload.files) {
      const button = document.createElement("button");
      button.type = "button";
      button.className = "entry file";
      const modified = new Date(file.modified_at * 1000).toLocaleString();
      button.innerHTML = `<span>${file.name}</span><small>${modified}</small>`;
      button.onclick = () => selectFile(browser, file.path);
      entries.appendChild(button);
    }
  }
  if (!payload.directories.length && !payload.files.length) {
    entries.innerHTML = `<div class="hint">当前目录没有匹配内容。</div>`;
  }
}

async function loadBrowser(browser, dir = null) {
  const state = getBrowserState(browser);
  if (dir !== null) state.dir = dir;
  const currentRequestId = ++state.requestId;
  const params = new URLSearchParams({
    kind: browser.dataset.kind,
    dir: state.dir,
    sort_by: state.sort_by,
    order: state.order,
    search: state.search,
  });
  const entries = browser.querySelector(".entries");
  entries.dataset.loading = "true";
  try {
    const payload = await apiGet(`/api/files?${params.toString()}`);
    if (currentRequestId !== state.requestId) return;
    renderBrowser(browser, payload);
  } catch (error) {
    if (currentRequestId !== state.requestId) return;
    entries.innerHTML = `<div class="alert">${error.message}</div>`;
  } finally {
    if (currentRequestId === state.requestId) {
      entries.dataset.loading = "false";
    }
  }
}

async function tryAutoMatchSubtitle(videoPath) {
  try {
    const payload = await apiGet(`/api/subtitles/match?video_path=${encodeURIComponent(videoPath)}`);
    const subtitleBrowser = document.querySelector('.browser[data-kind="subtitle"]');
    if (!subtitleBrowser) return;
    if (payload.match?.directory !== undefined) {
      const subtitleState = getBrowserState(subtitleBrowser);
      subtitleState.dir = payload.match.directory || "";
      await loadBrowser(subtitleBrowser, subtitleState.dir);
    }
    if (!payload.match) {
      updateSubtitleMatchHint("当前视频所在目录未找到可自动匹配的字幕，请手动选择或上传。");
      return;
    }
    document.querySelector('input[name="subtitle_path"]').value = payload.match.path;
    subtitleBrowser.querySelector(".selected").textContent = `已自动匹配：${payload.match.path}`;
    updateSubtitleMatchHint(`已自动匹配字幕：${payload.match.name}`);
    updateOutputPreview();
  } catch (error) {
    updateSubtitleMatchHint(`自动匹配字幕失败：${error.message}`, true);
  }
}

function selectFile(browser, path) {
  const kind = browser.dataset.kind;
  if (browser.dataset.role === "shift-output-dir") {
    return;
  }
  const inputName = browser.dataset.role === "shift-subtitle" ? "subtitle_path" : `${kind}_path`;
  const hiddenInput = document.querySelector(`input[name="${inputName}"]`);
  hiddenInput.value = path;
  browser.querySelector(".selected").textContent = `已选择：${path}`;
  if (kind === "video") {
    tryAutoMatchSubtitle(path);
  } else if (browser.dataset.role !== "shift-subtitle") {
    updateSubtitleMatchHint("已手动选择字幕文件。");
  }
  updateOutputPreview();
}

function selectCurrentDirectory(browser) {
  const state = getBrowserState(browser);
  const hiddenInput = document.querySelector('input[name="save_dir"]');
  hiddenInput.value = state.dir;
  browser.querySelector(".selected").textContent = state.dir ? `已选择目录：${state.dir}` : "已选择目录：/";
}

function mountBrowserControls(browser) {
  const state = getBrowserState(browser);
  const sortSelect = browser.querySelector(".sort-select");
  const searchInput = browser.querySelector(".search-input");
  const refreshButton = browser.querySelector(".refresh-button");
  const debouncedSearch = debounce(() => loadBrowser(browser), 250);

  sortSelect.addEventListener("change", () => {
    const [sort_by, order] = sortSelect.value.split(":");
    state.sort_by = sort_by;
    state.order = order;
    loadBrowser(browser);
  });

  searchInput.addEventListener("input", () => {
    state.search = searchInput.value.trim();
    debouncedSearch();
  });

  refreshButton.addEventListener("click", () => loadBrowser(browser));
}

function renderTaskList(tasks) {
  const container = document.getElementById("tasks-list");
  if (!container) return;
  container.innerHTML = "";
  for (const task of tasks) {
    const button = document.createElement("button");
    button.type = "button";
    button.className = "task-item";
    button.dataset.taskId = task.task_id;
    button.innerHTML = `
      <div class="task-item-head">
        <strong>${task.output_name || task.task_id}</strong>
        <span>${task.status}</span>
      </div>
      <div class="progress-bar"><span style="width:${task.progress}%"></span></div>
      <p class="muted">${task.progress_message || ""}</p>
    `;
    button.onclick = () => selectTask(task.task_id);
    container.appendChild(button);
  }
}

let selectedTaskId = null;

function collapseSelectedTask() {
  selectedTaskId = null;
  const panel = document.getElementById("task-detail-panel");
  if (panel) panel.classList.add("hidden");
}

async function selectTask(taskId) {
  if (selectedTaskId === taskId) {
    collapseSelectedTask();
    return;
  }
  selectedTaskId = taskId;
  const panel = document.getElementById("task-detail-panel");
  if (panel) panel.classList.remove("hidden");
  await refreshSelectedTask();
}

async function refreshTaskList() {
  const payload = await apiGet("/api/tasks");
  renderTaskList(payload.tasks);
  if (!selectedTaskId && payload.tasks.length) {
    selectedTaskId = payload.tasks[0].task_id;
  }
  if (selectedTaskId) {
    await refreshSelectedTask();
  }
}

async function refreshSelectedTask() {
  if (!selectedTaskId) return;
  const [task, log] = await Promise.all([
    apiGet(`/api/tasks/${selectedTaskId}`),
    apiGet(`/api/tasks/${selectedTaskId}/log`),
  ]);
  document.getElementById("task-status").textContent = task.status;
  document.getElementById("task-progress-text").textContent = `${task.progress}%`;
  document.getElementById("task-progress-bar").style.width = `${task.progress}%`;
  document.getElementById("task-progress-message").textContent = task.progress_message || "-";
  document.getElementById("task-output").textContent = task.output_path || "-";
  document.getElementById("task-error").textContent = task.error || "-";
  document.getElementById("task-log").textContent = log.log || "(暂无日志)";
  const stopButton = document.getElementById("stop-task-button");
  stopButton.disabled = !["queued", "running"].includes(task.status);
  const downloadLink = document.getElementById("task-download-link");
  if (task.can_download_output && task.status === "succeeded") {
    downloadLink.href = `/api/tasks/${task.task_id}/download`;
    downloadLink.classList.remove("hidden");
  } else {
    downloadLink.classList.add("hidden");
  }
}

function mountTaskPanel() {
  const container = document.getElementById("tasks-list");
  if (!container) return;
  const refreshButton = document.getElementById("refresh-tasks-button");
  const stopButton = document.getElementById("stop-task-button");
  refreshButton.addEventListener("click", () => refreshTaskList().catch(() => {}));
  stopButton.addEventListener("click", async () => {
    if (!selectedTaskId) return;
    try {
      await apiPost(`/api/tasks/${selectedTaskId}/stop`, { method: "POST" });
      await refreshTaskList();
    } catch (_error) {}
  });
  refreshTaskList().catch(() => {});
  setInterval(() => refreshTaskList().catch(() => {}), 2500);
}

function mountHomePage() {
  const form = document.getElementById("task-form");
  if (!form) return;

  for (const browser of document.querySelectorAll(".browser")) {
    if (browser.dataset.kind === "subtitle" && document.getElementById("subtitle-media-panel").classList.contains("hidden")) {
      continue;
    }
    mountBrowserControls(browser);
    loadBrowser(browser, "");
  }

  form.querySelectorAll('input[name="subtitle_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const uploadMode = radio.value === "upload" && radio.checked;
      document.getElementById("subtitle-media-panel").classList.toggle("hidden", uploadMode);
      document.getElementById("subtitle-upload-panel").classList.toggle("hidden", !uploadMode);
      updateOutputPreview();
    });
  });

  ["output_name", "subtitle_file"].forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    element.addEventListener("input", updateOutputPreview);
    if (element.type === "file") {
      element.addEventListener("change", updateOutputPreview);
    }
  });
  updateOutputPreview();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorBox = document.getElementById("form-error");
    const submitButton = document.getElementById("submit-button");
    errorBox.classList.add("hidden");

    const subtitleMode = form.querySelector('input[name="subtitle_mode"]:checked')?.value || "media";
    if (!form.video_path.value) {
      errorBox.textContent = "请先选择视频文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (subtitleMode === "media" && !form.subtitle_path.value) {
      errorBox.textContent = "请先选择字幕文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (subtitleMode === "upload" && !form.subtitle_file.files.length) {
      errorBox.textContent = "请上传字幕文件。";
      errorBox.classList.remove("hidden");
      return;
    }

    const formData = new FormData();
    formData.append("video_path", form.video_path.value);
    formData.append("subtitle_mode", subtitleMode);
    formData.append("subtitle_path", subtitleMode === "media" ? form.subtitle_path.value : "");
    formData.append("output_name", form.output_name.value.trim());
    formData.append("encoding", form.encoding.value.trim());
    formData.append("max_offset_seconds", form.max_offset_seconds.value);
    if (form.no_fix_framerate.checked) formData.append("no_fix_framerate", "true");
    if (form.gss.checked) formData.append("gss", "true");
    if (subtitleMode === "upload") {
      formData.append("subtitle_file", form.subtitle_file.files[0]);
    }

    submitButton.disabled = true;
    submitButton.textContent = "提交中...";
    try {
      const result = await apiPost("/api/tasks", { method: "POST", body: formData });
      selectedTaskId = result.task_id;
      await refreshTaskList();
      document.getElementById("task-detail-panel").scrollIntoView({ behavior: "smooth", block: "start" });
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "提交同步任务";
    }
  });

  mountTaskPanel();
}

function mountTaskPage() {
  if (!window.TASK_ID) return;
  selectedTaskId = window.TASK_ID;
  refreshSelectedTask().catch(() => {});
}

function mountSubtitleToolsPage() {
  const form = document.getElementById("subtitle-shift-form");
  if (!form) return;
  const mediaPanel = document.getElementById("shift-media-panel");
  const uploadPanel = document.getElementById("shift-upload-panel");
  const savePanel = document.getElementById("shift-save-panel");
  const subtitleBrowser = document.querySelector('.browser[data-role="shift-subtitle"]');
  const saveDirBrowser = document.querySelector('.browser[data-role="shift-output-dir"]');
  if (subtitleBrowser) {
    mountBrowserControls(subtitleBrowser);
    loadBrowser(subtitleBrowser, "");
  }
  if (saveDirBrowser) {
    mountBrowserControls(saveDirBrowser);
    loadBrowser(saveDirBrowser, "");
    document.getElementById("select-shift-save-dir").addEventListener("click", () => selectCurrentDirectory(saveDirBrowser));
    selectCurrentDirectory(saveDirBrowser);
  }
  form.querySelectorAll('input[name="subtitle_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const uploadMode = form.querySelector('input[name="subtitle_mode"]:checked')?.value === "upload";
      mediaPanel.classList.toggle("hidden", uploadMode);
      uploadPanel.classList.toggle("hidden", !uploadMode);
    });
  });
  form.querySelectorAll('input[name="save_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const saveMode = form.querySelector('input[name="save_mode"]:checked')?.value || "download";
      savePanel.classList.toggle("hidden", saveMode === "download");
    });
  });
  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorBox = document.getElementById("subtitle-shift-error");
    const successBox = document.getElementById("subtitle-shift-success");
    const submitButton = document.getElementById("subtitle-shift-submit");
    errorBox.classList.add("hidden");
    successBox.classList.add("hidden");
    const subtitleMode = form.querySelector('input[name="subtitle_mode"]:checked')?.value || "media";
    const saveMode = form.querySelector('input[name="save_mode"]:checked')?.value || "download";
    if (subtitleMode === "media" && !form.subtitle_path.value) {
      errorBox.textContent = "请先选择字幕文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (subtitleMode === "upload" && !form.subtitle_file.files.length) {
      errorBox.textContent = "请上传字幕文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (saveMode !== "download" && subtitleMode === "upload" && form.save_dir.value === undefined) {
      errorBox.textContent = "请选择保存目录。";
      errorBox.classList.remove("hidden");
      return;
    }
    submitButton.disabled = true;
    submitButton.textContent = "处理中...";
    try {
      const formData = new FormData();
      formData.append("subtitle_mode", subtitleMode);
      formData.append("subtitle_path", subtitleMode === "media" ? form.subtitle_path.value : "");
      formData.append("save_mode", saveMode);
      formData.append("save_dir", saveMode !== "download" ? (form.save_dir.value || "") : "");
      formData.append("offset_seconds", form.offset_seconds.value);
      if (subtitleMode === "upload") {
        formData.append("subtitle_file", form.subtitle_file.files[0]);
      }
      const response = await fetch("/api/subtitles/shift", {
        method: "POST",
        body: formData,
        credentials: "same-origin",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(data.detail || "请求失败");
      }
      if (saveMode === "save") {
        const payload = await response.json();
        successBox.textContent = `已保存到媒体目录：${payload.saved_path}`;
        successBox.classList.remove("hidden");
        return;
      }
      const blob = await response.blob();
      const disposition = response.headers.get("Content-Disposition") || "";
      const savedPath = response.headers.get("X-Saved-Path");
      const match = disposition.match(/filename="([^"]+)"/);
      const filename = match ? match[1] : "shifted-subtitle.srt";
      const url = URL.createObjectURL(blob);
      const link = document.createElement("a");
      link.href = url;
      link.download = filename;
      document.body.appendChild(link);
      link.click();
      link.remove();
      URL.revokeObjectURL(url);
      if (savedPath) {
        successBox.textContent = `已保存到媒体目录：${savedPath}，并开始下载。`;
        successBox.classList.remove("hidden");
      }
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      submitButton.disabled = false;
      submitButton.textContent = "开始处理";
    }
  });
}

mountHomePage();
mountTaskPage();
mountSubtitleToolsPage();
