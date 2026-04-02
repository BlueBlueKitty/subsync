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

function buildDefaultOutputName(subtitleName, syncTool = "ffsubsync") {
  if (!subtitleName) {
    return "默认输出为原字幕名加引擎后缀，例如 movie.zh.ffsubsync.srt。";
  }
  const fileName = subtitleName.split("/").pop() || subtitleName;
  const stem = fileName.includes(".") ? fileName.slice(0, fileName.lastIndexOf(".")) : fileName;
  const ext = fileName.includes(".") ? fileName.slice(fileName.lastIndexOf(".")) : ".srt";
  return `默认输出为 ${stem}.${syncTool}${ext}`;
}

function updateOutputPreview() {
  const form = document.getElementById("task-form");
  const preview = document.getElementById("output-preview");
  if (!form || !preview) return;
  const subtitleMode = form.querySelector('input[name="subtitle_mode"]:checked')?.value || "media";
  const subtitleName = subtitleMode === "upload"
    ? document.getElementById("subtitle_file").files[0]?.name
    : form.subtitle_path.value;
  const syncTool = document.getElementById("sync_tool")?.value || "ffsubsync";
  preview.textContent = buildDefaultOutputName(subtitleName || "", syncTool);
}

function syncToolMeta(tool) {
  if (tool === "alass") {
    return "alass：支持使用视频中的内嵌字幕作为参考，可调 FPS 猜测、速度优化和分割惩罚。";
  }
  if (tool === "autosubsync") {
    return "autosubsync：支持最大位移与并行度设置；勾选内嵌字幕时，如检测到字幕轨会自动切换到更适合字幕参考的 ffsubsync 处理。";
  }
  return "ffsubsync：支持使用视频中的内嵌字幕作为参考、不修复帧率、黄金分割搜索，以及语音活动检测器选择。";
}

function syncToolLabel(tool) {
  return tool || "ffsubsync";
}

function renderBatchPreview(payload) {
  const preview = document.getElementById("batch-preview");
  const summary = document.getElementById("batch-preview-summary");
  const list = document.getElementById("batch-preview-list");
  const unmatched = document.getElementById("batch-preview-unmatched");
  if (!preview || !summary || !list || !unmatched) return;
  preview.classList.remove("hidden");
  summary.textContent = `已匹配 ${payload.matched_count} 组视频/字幕`;
  list.innerHTML = "";
  for (const pair of payload.pairs.slice(0, 12)) {
    const item = document.createElement("li");
    item.textContent = `${pair.video_name} <- ${pair.subtitle_name}`;
    list.appendChild(item);
  }
  if (payload.pairs.length > 12) {
    const item = document.createElement("li");
    item.textContent = `... 另有 ${payload.pairs.length - 12} 组已匹配`;
    list.appendChild(item);
  }
  unmatched.textContent = payload.unmatched_videos.length
    ? `未匹配视频 ${payload.unmatched_videos.length} 个`
    : "所有扫描到的视频都已匹配字幕。";
}

function bindRangeOutput(inputId, outputId) {
  const input = document.getElementById(inputId);
  const output = document.getElementById(outputId);
  if (!input || !output) return;
  const refresh = () => {
    output.textContent = input.value;
  };
  input.addEventListener("input", refresh);
  refresh();
}

async function triggerBrowserDownload(response, fallbackName = "download.bin") {
  const blob = await response.blob();
  const disposition = response.headers.get("Content-Disposition") || "";
  const match = disposition.match(/filename="([^"]+)"/);
  const filename = match ? match[1] : fallbackName;
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  URL.revokeObjectURL(url);
  return filename;
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
  if (browser.dataset.role !== "shift-output-dir" && browser.dataset.role !== "scheduler-dir") {
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
    if (payload.directory !== undefined && payload.directory !== null) {
      const subtitleState = getBrowserState(subtitleBrowser);
      subtitleState.dir = payload.directory || "";
      await loadBrowser(subtitleBrowser, subtitleState.dir);
    }
    if (!payload.match) {
      updateSubtitleMatchHint("已自动跳转到视频同目录，但未找到可自动匹配的字幕，请手动选择或上传。");
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
  if (browser.dataset.role === "batch-video-dir") {
    return;
  }
  if (browser.dataset.role === "shift-output-dir") {
    return;
  }
  if (browser.dataset.role === "scheduler-dir") {
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
    if (browser.dataset.kind === "subtitle") {
      syncHomeManualSaveDirectoryFromSubtitle(path).catch(() => {});
    }
  }
  updateOutputPreview();
}

function selectCurrentDirectory(browser) {
  const state = getBrowserState(browser);
  const hiddenInput = document.querySelector('input[name="save_dir"]');
  hiddenInput.value = state.dir;
  browser.querySelector(".selected").textContent = state.dir ? `已选择目录：${state.dir}` : "已选择目录：/";
}

function getCurrentBrowserDir(browser) {
  const state = getBrowserState(browser);
  return state.dir || "";
}

function addLineToTextarea(textarea, value) {
  const normalized = value.trim();
  const visibleValue = normalized || "/";
  if (!textarea) return;
  const existingVisible = textarea.value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean);
  if (existingVisible.includes(visibleValue)) return;
  existingVisible.push(visibleValue);
  textarea.value = existingVisible.join("\n");
}

async function syncHomeManualSaveDirectoryFromSubtitle(path) {
  const saveDirBrowser = document.querySelector('.browser[data-role="home-shift-output-dir"]');
  if (!saveDirBrowser) return;
  const directory = path.includes("/") ? path.slice(0, path.lastIndexOf("/")) : "";
  await loadBrowser(saveDirBrowser, directory);
  selectCurrentDirectory(saveDirBrowser);
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
    if (selectedTaskId === task.task_id) {
      button.classList.add("active");
    }
    button.innerHTML = `
      <div class="task-item-head">
        <strong>${task.output_name || task.task_id}</strong>
        <span>${task.status}</span>
      </div>
      <p class="muted">${syncToolLabel(task.sync_tool)}</p>
      <div class="progress-bar"><span style="width:${task.progress}%"></span></div>
      <p class="muted">${task.progress_message || ""}</p>
    `;
    button.onclick = () => selectTask(task.task_id);
    container.appendChild(button);
  }
}

let selectedTaskId = null;

async function selectTask(taskId) {
  selectedTaskId = taskId;
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
  const syncToolNode = document.getElementById("task-sync-tool");
  if (syncToolNode) syncToolNode.textContent = syncToolLabel(task.sync_tool);
  document.getElementById("task-progress-text").textContent = `${task.progress}%`;
  document.getElementById("task-progress-bar").style.width = `${task.progress}%`;
  document.getElementById("task-progress-message").textContent = task.progress_message || "-";
  document.getElementById("task-output").textContent = task.output_path || "-";
  document.getElementById("task-error").textContent = task.error || "-";
  document.getElementById("task-log").textContent = log.log || "(暂无日志)";
  const stopButton = document.getElementById("stop-task-button");
  if (stopButton) {
    stopButton.disabled = !["queued", "running"].includes(task.status);
  }
  const downloadLink = document.getElementById("task-download-link");
  if (!downloadLink) {
    return;
  }
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
  const videoBrowserCard = document.getElementById("video-browser-card");
  const batchBrowserCard = document.getElementById("batch-browser-card");
  const subtitleBrowserCard = document.querySelector(".subtitle-browser");
  const autoSubmitModePanel = document.getElementById("auto-submit-mode-panel");
  const autoModePanel = document.getElementById("auto-mode-panel");
  const manualModePanel = document.getElementById("manual-mode-panel");
  const homeSavePanel = document.getElementById("home-shift-save-panel");
  const manualSuccess = document.getElementById("manual-success");
  const syncToolSelect = document.getElementById("sync_tool");

  for (const browser of document.querySelectorAll(".browser")) {
    if (browser.dataset.kind === "subtitle" && document.getElementById("subtitle-media-panel").classList.contains("hidden")) {
      continue;
    }
    mountBrowserControls(browser);
    loadBrowser(browser, "");
  }

  const homeSaveDirBrowser = document.querySelector('.browser[data-role="home-shift-output-dir"]');
  const batchDirBrowser = document.querySelector('.browser[data-role="batch-video-dir"]');
  if (homeSaveDirBrowser) {
    document.getElementById("select-home-save-dir").addEventListener("click", () => selectCurrentDirectory(homeSaveDirBrowser));
    selectCurrentDirectory(homeSaveDirBrowser);
  }
  if (batchDirBrowser) {
    document.getElementById("select-batch-dir").addEventListener("click", async () => {
      const state = getBrowserState(batchDirBrowser);
      form.batch_dir.value = state.dir;
      batchDirBrowser.querySelector(".selected").textContent = state.dir ? `已选择目录：${state.dir}` : "已选择目录：/";
      try {
        const params = new URLSearchParams({
          dir: state.dir,
          recursive: document.getElementById("batch_recursive").checked ? "true" : "false",
        });
        const payload = await apiGet(`/api/tasks/batch-preview?${params.toString()}`);
        renderBatchPreview(payload);
      } catch (error) {
        document.getElementById("form-error").textContent = error.message;
        document.getElementById("form-error").classList.remove("hidden");
      }
    });
    document.getElementById("batch_recursive").addEventListener("change", async () => {
      if (!form.batch_dir.value) return;
      const params = new URLSearchParams({
        dir: form.batch_dir.value,
        recursive: document.getElementById("batch_recursive").checked ? "true" : "false",
      });
      try {
        const payload = await apiGet(`/api/tasks/batch-preview?${params.toString()}`);
        renderBatchPreview(payload);
      } catch (_error) {}
    });
  }

  form.querySelectorAll('input[name="subtitle_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const uploadMode = radio.value === "upload" && radio.checked;
      document.getElementById("subtitle-media-panel").classList.toggle("hidden", uploadMode);
      document.getElementById("subtitle-upload-panel").classList.toggle("hidden", !uploadMode);
      updateOutputPreview();
    });
  });

  function syncActionMode() {
    const actionMode = form.querySelector('input[name="action_mode"]:checked')?.value || "auto";
    const isAuto = actionMode === "auto";
    const autoSubmitMode = form.querySelector('input[name="auto_submit_mode"]:checked')?.value || "single";
    const isBatch = isAuto && autoSubmitMode === "batch";
    videoBrowserCard.classList.toggle("hidden", !isAuto || isBatch);
    batchBrowserCard.classList.toggle("hidden", !isBatch);
    subtitleBrowserCard.classList.toggle("hidden", isBatch);
    autoSubmitModePanel.classList.toggle("hidden", !isAuto);
    autoModePanel.classList.toggle("hidden", !isAuto);
    manualModePanel.classList.toggle("hidden", isAuto);
    document.getElementById("subtitle-match-hint").classList.toggle("hidden", !isAuto || isBatch);
    document.getElementById("submit-button").textContent = !isAuto ? "开始手动调整" : isBatch ? "开始批量处理" : "提交同步任务";
  }

  function syncToolPanels() {
    const selectedTool = syncToolSelect?.value || "ffsubsync";
    document.getElementById("ffsubsync-options")?.classList.toggle("hidden", selectedTool !== "ffsubsync");
    document.getElementById("alass-options")?.classList.toggle("hidden", selectedTool !== "alass");
    document.getElementById("autosubsync-options")?.classList.toggle("hidden", selectedTool !== "autosubsync");
    const hint = document.getElementById("sync-tool-hint");
    if (hint) {
      hint.textContent = syncToolMeta(selectedTool);
    }
  }

  form.querySelectorAll('input[name="action_mode"]').forEach((radio) => {
    radio.addEventListener("change", syncActionMode);
  });
  form.querySelectorAll('input[name="auto_submit_mode"]').forEach((radio) => {
    radio.addEventListener("change", syncActionMode);
  });

  form.querySelectorAll('input[name="save_mode"]').forEach((radio) => {
    radio.addEventListener("change", () => {
      const saveMode = form.querySelector('input[name="save_mode"]:checked')?.value || "download";
      homeSavePanel.classList.toggle("hidden", saveMode === "download");
    });
  });

  ["subtitle_file"].forEach((id) => {
    const element = document.getElementById(id);
    if (!element) return;
    element.addEventListener("input", updateOutputPreview);
    if (element.type === "file") {
      element.addEventListener("change", updateOutputPreview);
    }
  });
  bindRangeOutput("alass_split_penalty", "alass_split_penalty_value");
  bindRangeOutput("autosubsync_max_shift_secs", "autosubsync_max_shift_secs_value");
  bindRangeOutput("autosubsync_parallelism", "autosubsync_parallelism_value");
  syncToolSelect?.addEventListener("change", syncToolPanels);
  updateOutputPreview();
  syncActionMode();
  const initialSaveMode = form.querySelector('input[name="save_mode"]:checked')?.value || "download";
  homeSavePanel.classList.toggle("hidden", initialSaveMode === "download");
  syncToolPanels();

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    const errorBox = document.getElementById("form-error");
    const submitButton = document.getElementById("submit-button");
    errorBox.classList.add("hidden");
    manualSuccess.classList.add("hidden");

    const actionMode = form.querySelector('input[name="action_mode"]:checked')?.value || "auto";
    const autoSubmitMode = form.querySelector('input[name="auto_submit_mode"]:checked')?.value || "single";
    const subtitleMode = form.querySelector('input[name="subtitle_mode"]:checked')?.value || "media";
    if (actionMode === "auto" && autoSubmitMode === "single" && subtitleMode === "media" && !form.subtitle_path.value) {
      errorBox.textContent = "请先选择字幕文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (actionMode === "auto" && autoSubmitMode === "single" && subtitleMode === "upload" && !form.subtitle_file.files.length) {
      errorBox.textContent = "请上传字幕文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (actionMode === "auto" && autoSubmitMode === "single" && !form.video_path.value) {
      errorBox.textContent = "自动同步前请先选择视频文件。";
      errorBox.classList.remove("hidden");
      return;
    }
    if (actionMode === "auto" && autoSubmitMode === "batch" && !form.batch_dir.value) {
      errorBox.textContent = "批量处理前请先选择一个目录。";
      errorBox.classList.remove("hidden");
      return;
    }

    submitButton.disabled = true;
    submitButton.textContent = actionMode === "auto" ? "提交中..." : "处理中...";
    try {
      const formData = new FormData();
      if (actionMode === "auto") {
        formData.append("sync_tool", syncToolSelect?.value || "ffsubsync");
        if (form.ffsubsync_use_embedded_subtitles.checked) {
          formData.append("ffsubsync_use_embedded_subtitles", "true");
        }
        if (form.no_fix_framerate.checked) formData.append("no_fix_framerate", "true");
        if (form.gss.checked) formData.append("gss", "true");
        formData.append("ffsubsync_vad", form.ffsubsync_vad.value);
        if (form.alass_use_embedded_subtitles.checked) {
          formData.append("alass_use_embedded_subtitles", "true");
        }
        if (form.alass_disable_fps_guessing.checked) formData.append("alass_disable_fps_guessing", "true");
        if (form.alass_disable_speed_optimization.checked) {
          formData.append("alass_disable_speed_optimization", "true");
        }
        formData.append("alass_split_penalty", form.alass_split_penalty.value);
        if (form.autosubsync_use_embedded_subtitles.checked) {
          formData.append("autosubsync_use_embedded_subtitles", "true");
        }
        formData.append("autosubsync_max_shift_secs", form.autosubsync_max_shift_secs.value);
        formData.append("autosubsync_parallelism", form.autosubsync_parallelism.value);

        if (autoSubmitMode === "batch") {
          formData.append("batch_dir", form.batch_dir.value);
          if (document.getElementById("batch_recursive").checked) {
            formData.append("recursive", "true");
          }
          const result = await apiPost("/api/tasks/batch", { method: "POST", body: formData });
          selectedTaskId = result.task_ids[0] || selectedTaskId;
          await refreshTaskList();
        } else {
          formData.append("video_path", form.video_path.value);
          formData.append("subtitle_mode", subtitleMode);
          formData.append("subtitle_path", subtitleMode === "media" ? form.subtitle_path.value : "");
          if (subtitleMode === "upload") {
            formData.append("subtitle_file", form.subtitle_file.files[0]);
          }

          const result = await apiPost("/api/tasks", { method: "POST", body: formData });
          selectedTaskId = result.task_id;
          await refreshTaskList();
        }
      } else {
        const saveMode = form.querySelector('input[name="save_mode"]:checked')?.value || "download";
        formData.append("subtitle_mode", subtitleMode);
        formData.append("subtitle_path", subtitleMode === "media" ? form.subtitle_path.value : "");
        formData.append("save_mode", saveMode);
        formData.append("save_dir", saveMode !== "download" ? (form.save_dir.value || "") : "");
        formData.append("offset_seconds", form.manual_offset_seconds.value);
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
          manualSuccess.textContent = `已保存到媒体目录：${payload.saved_path}`;
          manualSuccess.classList.remove("hidden");
        } else {
          const savedPath = response.headers.get("X-Saved-Path");
          await triggerBrowserDownload(response, "shifted-subtitle.srt");
          if (savedPath) {
            manualSuccess.textContent = `已保存到媒体目录：${savedPath}，并开始下载。`;
            manualSuccess.classList.remove("hidden");
          }
        }
      }
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    } finally {
      submitButton.disabled = false;
      syncActionMode();
    }
  });

  mountTaskPanel();
}

function splitLines(value) {
  return value
    .split(/\r?\n/)
    .map((item) => item.trim())
    .filter(Boolean)
    .map((item) => (item === "/" ? "" : item));
}

function renderSchedulerState(payload) {
  const config = payload.config;
  document.getElementById("scheduler_enabled").checked = config.enabled;
  document.getElementById("scheduler_run_on_startup").checked = config.run_on_startup;
  document.getElementById("scheduler_recursive").checked = config.recursive;
  document.getElementById("scheduler_scan_time").value = config.scan_time;
  document.getElementById("scheduler_include_dirs").value = (config.include_dirs || [])
    .map((item) => item || "/")
    .join("\n");
  document.getElementById("scheduler_exclude_dirs").value = (config.exclude_dirs || [])
    .map((item) => item || "/")
    .join("\n");
  document.getElementById("engine_ffsubsync").checked = (config.enabled_engines || []).includes("ffsubsync");
  document.getElementById("engine_alass").checked = (config.enabled_engines || []).includes("alass");
  document.getElementById("engine_autosubsync").checked = (config.enabled_engines || []).includes("autosubsync");

  document.getElementById("scheduler_ffsubsync_use_embedded_subtitles").checked = config.engine_options.ffsubsync_use_embedded_subtitles;
  document.getElementById("scheduler_ffsubsync_vad").value = config.engine_options.ffsubsync_vad;
  document.getElementById("scheduler_no_fix_framerate").checked = config.engine_options.no_fix_framerate;
  document.getElementById("scheduler_gss").checked = config.engine_options.gss;
  document.getElementById("scheduler_alass_use_embedded_subtitles").checked = config.engine_options.alass_use_embedded_subtitles;
  document.getElementById("scheduler_alass_disable_fps_guessing").checked = config.engine_options.alass_disable_fps_guessing;
  document.getElementById("scheduler_alass_disable_speed_optimization").checked = config.engine_options.alass_disable_speed_optimization;
  document.getElementById("scheduler_alass_split_penalty").value = config.engine_options.alass_split_penalty;
  document.getElementById("scheduler_autosubsync_use_embedded_subtitles").checked = config.engine_options.autosubsync_use_embedded_subtitles;
  document.getElementById("scheduler_autosubsync_max_shift_secs").value = config.engine_options.autosubsync_max_shift_secs;
  document.getElementById("scheduler_autosubsync_parallelism").value = config.engine_options.autosubsync_parallelism;
  document.getElementById("scheduler_alass_split_penalty_value").textContent = config.engine_options.alass_split_penalty;
  document.getElementById("scheduler_autosubsync_max_shift_secs_value").textContent = config.engine_options.autosubsync_max_shift_secs;
  document.getElementById("scheduler_autosubsync_parallelism_value").textContent = config.engine_options.autosubsync_parallelism;
  renderSchedulerStatus(payload.status);
}

function renderSchedulerStatus(status) {
  document.getElementById("scheduler-status-label").textContent = status.last_status || "-";
  document.getElementById("scheduler-last-started").textContent = status.last_started_at || "-";
  document.getElementById("scheduler-last-finished").textContent = status.last_finished_at || "-";
  document.getElementById("scheduler-last-summary").textContent = status.last_summary || "-";
  document.getElementById("scheduler-last-error").textContent = status.last_error || "-";
}

function collectSchedulerPayload() {
  const enabledEngines = ["ffsubsync", "alass", "autosubsync"].filter((engine) => {
    return document.getElementById(`engine_${engine}`).checked;
  });
  return {
    enabled: document.getElementById("scheduler_enabled").checked,
    run_on_startup: document.getElementById("scheduler_run_on_startup").checked,
    recursive: document.getElementById("scheduler_recursive").checked,
    scan_time: document.getElementById("scheduler_scan_time").value || "03:00",
    include_dirs: splitLines(document.getElementById("scheduler_include_dirs").value),
    exclude_dirs: splitLines(document.getElementById("scheduler_exclude_dirs").value),
    enabled_engines: enabledEngines,
    engine_options: {
      ffsubsync_use_embedded_subtitles: document.getElementById("scheduler_ffsubsync_use_embedded_subtitles").checked,
      ffsubsync_vad: document.getElementById("scheduler_ffsubsync_vad").value,
      no_fix_framerate: document.getElementById("scheduler_no_fix_framerate").checked,
      gss: document.getElementById("scheduler_gss").checked,
      alass_use_embedded_subtitles: document.getElementById("scheduler_alass_use_embedded_subtitles").checked,
      alass_disable_fps_guessing: document.getElementById("scheduler_alass_disable_fps_guessing").checked,
      alass_disable_speed_optimization: document.getElementById("scheduler_alass_disable_speed_optimization").checked,
      alass_split_penalty: Number(document.getElementById("scheduler_alass_split_penalty").value || "7"),
      autosubsync_use_embedded_subtitles: document.getElementById("scheduler_autosubsync_use_embedded_subtitles").checked,
      autosubsync_max_shift_secs: Number(document.getElementById("scheduler_autosubsync_max_shift_secs").value || "20"),
      autosubsync_parallelism: Number(document.getElementById("scheduler_autosubsync_parallelism").value || "3"),
    },
  };
}

function mountSettingsPage() {
  const form = document.getElementById("scheduler-form");
  if (!form) return;
  const errorBox = document.getElementById("scheduler-form-error");
  const successBox = document.getElementById("scheduler-form-success");
  const runNowButton = document.getElementById("scheduler-run-now-button");
  const dirBrowser = document.querySelector('.browser[data-role="scheduler-dir"]');

  bindRangeOutput("scheduler_alass_split_penalty", "scheduler_alass_split_penalty_value");
  bindRangeOutput("scheduler_autosubsync_max_shift_secs", "scheduler_autosubsync_max_shift_secs_value");
  bindRangeOutput("scheduler_autosubsync_parallelism", "scheduler_autosubsync_parallelism_value");

  if (dirBrowser) {
    mountBrowserControls(dirBrowser);
    loadBrowser(dirBrowser, "");
    document.getElementById("add-include-dir").addEventListener("click", () => {
      addLineToTextarea(document.getElementById("scheduler_include_dirs"), getCurrentBrowserDir(dirBrowser));
    });
    document.getElementById("add-exclude-dir").addEventListener("click", () => {
      addLineToTextarea(document.getElementById("scheduler_exclude_dirs"), getCurrentBrowserDir(dirBrowser));
    });
  }

  const refreshState = async () => {
    const payload = await apiGet("/api/settings/scheduler/status");
    renderSchedulerStatus(payload.status);
  };

  apiGet("/api/settings/scheduler").then(renderSchedulerState).catch((error) => {
    errorBox.textContent = error.message;
    errorBox.classList.remove("hidden");
  });

  form.addEventListener("submit", async (event) => {
    event.preventDefault();
    errorBox.classList.add("hidden");
    successBox.classList.add("hidden");
    try {
      const payload = collectSchedulerPayload();
      const response = await fetch("/api/settings/scheduler", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(data.detail || "请求失败");
      }
      const result = await response.json();
      renderSchedulerState(result);
      successBox.textContent = "扫描设置已保存。";
      successBox.classList.remove("hidden");
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    }
  });

  runNowButton.addEventListener("click", async () => {
    errorBox.classList.add("hidden");
    successBox.classList.add("hidden");
    try {
      const response = await fetch("/api/settings/scheduler/run-now", {
        method: "POST",
        credentials: "same-origin",
      });
      if (!response.ok) {
        const data = await response.json().catch(() => ({ detail: "请求失败" }));
        throw new Error(data.detail || "请求失败");
      }
      const result = await response.json();
      document.getElementById("scheduler-status-label").textContent = result.last_status || "-";
      document.getElementById("scheduler-last-summary").textContent = result.last_summary || "-";
      document.getElementById("scheduler-last-error").textContent = result.last_error || "-";
      successBox.textContent = "已触发扫描任务。";
      successBox.classList.remove("hidden");
      setTimeout(() => refreshState().catch(() => {}), 500);
    } catch (error) {
      errorBox.textContent = error.message;
      errorBox.classList.remove("hidden");
    }
  });

  setInterval(() => refreshState().catch(() => {}), 5000);
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
  const initialSaveMode = form.querySelector('input[name="save_mode"]:checked')?.value || "download";
  savePanel.classList.toggle("hidden", initialSaveMode === "download");
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
mountSettingsPage();
