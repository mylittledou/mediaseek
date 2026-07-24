// MediaSeek M3U8 Downloader Frontend Application Logic

let defaultDownloadDir = "/downloads";
let tasksMap = new Map(); // Store all tasks by ID
let socket = null;

document.addEventListener("DOMContentLoaded", () => {
  initAuth();
  initTabs();
  initForm();
});

// --------------------------------------------------------------------------
// Authentication Logic
// --------------------------------------------------------------------------
async function checkAuth() {
  try {
    const res = await fetch("/api/auth-check");
    if (res.ok) {
      const data = await res.json();
      isAuthenticated = data.authenticated;
      toggleAuthUI(isAuthenticated);
      if (isAuthenticated) {
        fetchConfig();
        if (!socket || socket.readyState !== WebSocket.OPEN) {
          connectWebSocket();
        }
      }
    } else {
      toggleAuthUI(false);
    }
  } catch (err) {
    toggleAuthUI(false);
  }
}

function toggleAuthUI(authed) {
  const loginView = document.getElementById("login-view");
  const appDashboard = document.getElementById("app-dashboard");

  if (authed) {
    if (loginView) loginView.style.display = "none";
    if (appDashboard) appDashboard.style.display = "flex";
  } else {
    if (loginView) loginView.style.display = "flex";
    if (appDashboard) appDashboard.style.display = "none";
    if (socket) {
      socket.close();
      socket = null;
    }
  }
}

function initAuth() {
  const loginForm = document.getElementById("login-form");
  const logoutBtn = document.getElementById("btn-logout");

  if (loginForm) {
    loginForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      const username = document.getElementById("login-user").value.trim();
      const password = document.getElementById("login-pass").value.trim();

      if (!username || !password) {
        showToast("请输入用户名和密码", "error");
        return;
      }

      try {
        const res = await fetch("/api/login", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ username, password })
        });

        if (res.ok) {
          showToast("身份验证成功，欢迎回来！", "success");
          loginForm.reset();
          checkAuth();
        } else {
          const err = await res.json();
          showToast(err.detail || "用户名或密码错误", "error");
        }
      } catch (err) {
        showToast("登录请求失败，请检查网络", "error");
      }
    });
  }

  if (logoutBtn) {
    logoutBtn.addEventListener("click", async () => {
      if (!confirm("确定要退出登录吗？")) return;
      try {
        await fetch("/api/logout", { method: "POST" });
        showToast("已安全退出登录", "success");
        checkAuth();
      } catch (e) {
        showToast("退出失败", "error");
      }
    });
  }

  // Initial check on load
  checkAuth();
}

// --------------------------------------------------------------------------
// Configuration & Data Fetching
// --------------------------------------------------------------------------
async function fetchConfig() {
  try {
    const res = await fetch("/api/config");
    if (res.ok) {
      const data = await res.json();
      defaultDownloadDir = data.default_download_dir;
      
      const defaultTag = document.getElementById("default-path-tag");
      if (defaultTag) defaultTag.textContent = defaultDownloadDir;

      const pathInput = document.getElementById("save-path");
      if (pathInput && !pathInput.value) {
        pathInput.value = defaultDownloadDir;
      }
    }
  } catch (err) {
    console.error("Failed to load config:", err);
  }
}

// --------------------------------------------------------------------------
// WebSocket Connection
// --------------------------------------------------------------------------
function connectWebSocket() {
  if (!isAuthenticated) return;

  const protocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const wsUrl = `${protocol}//${window.location.host}/ws`;

  socket = new WebSocket(wsUrl);

  const statusBadge = document.getElementById("ws-status");
  const statusDot = statusBadge.querySelector(".status-dot");
  const statusText = statusBadge.querySelector(".status-text");

  socket.onopen = () => {
    statusDot.className = "status-dot online";
    statusText.textContent = "已连接服务";
  };

  socket.onmessage = (event) => {
    try {
      const msg = JSON.parse(event.data);
      if (msg.type === "init") {
        tasksMap.clear();
        msg.data.forEach(task => tasksMap.set(task.id, task));
        renderAll();
      } else if (msg.type === "progress") {
        tasksMap.set(msg.data.id, msg.data);
        renderAll();
      }
    } catch (e) {
      console.error("WS message parse error:", e);
    }
  };

  socket.onclose = () => {
    statusDot.className = "status-dot offline";
    statusText.textContent = "未连接服务";
    if (isAuthenticated) {
      setTimeout(connectWebSocket, 3000);
    }
  };

  socket.onerror = (err) => {
    console.error("WS error:", err);
    socket.close();
  };
}

// --------------------------------------------------------------------------
// Tab Navigation
// --------------------------------------------------------------------------
function initTabs() {
  const tabBtns = document.querySelectorAll(".tab-btn");
  const tabContents = document.querySelectorAll(".tab-content");

  tabBtns.forEach(btn => {
    btn.addEventListener("click", () => {
      const targetTabId = btn.getAttribute("data-tab");

      tabBtns.forEach(b => b.classList.remove("active"));
      tabContents.forEach(c => c.classList.remove("active"));

      btn.classList.add("active");
      document.getElementById(targetTabId).classList.add("active");
    });
  });
}

function switchTab(tabId) {
  const btn = document.querySelector(`.tab-btn[data-tab="${tabId}"]`);
  if (btn) btn.click();
}

// --------------------------------------------------------------------------
// Form Handler
// --------------------------------------------------------------------------
function initForm() {
  const form = document.getElementById("download-form");
  const pasteBtn = document.getElementById("btn-paste");
  const resetPathBtn = document.getElementById("btn-reset-path");

  if (pasteBtn) {
    pasteBtn.addEventListener("click", async () => {
      try {
        const text = await navigator.clipboard.readText();
        if (text) {
          document.getElementById("m3u8-url").value = text.trim();
          showToast("已从剪贴板粘贴链接", "success");
        }
      } catch (err) {
        showToast("无法读取剪贴板，请手动粘贴", "error");
      }
    });
  }

  if (resetPathBtn) {
    resetPathBtn.addEventListener("click", () => {
      document.getElementById("save-path").value = defaultDownloadDir;
      showToast("已重置存储路径为默认值", "success");
    });
  }



  form.addEventListener("submit", async (e) => {
    e.preventDefault();

    let url = document.getElementById("m3u8-url").value.trim();
    let title = document.getElementById("video-title").value.trim();
    const save_path = document.getElementById("save-path").value.trim() || defaultDownloadDir;
    const concurrency = parseInt(document.getElementById("concurrency").value, 10);

    if (!url) {
      showToast("请输入 M3U8 链接地址或网页地址", "error");
      return;
    }

    if (!url.toLowerCase().includes(".m3u8") && !url.toLowerCase().includes(".mp4")) {
      showToast("警告：链接可能不是标准的视频流地址", "success");
    }

    try {
      const res = await fetch("/api/tasks", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ url, title, save_path, concurrency })
      });

      if (res.ok) {
        const newTask = await res.json();
        tasksMap.set(newTask.id, newTask);
        showToast("下载任务建立成功！", "success");
        form.reset();
        document.getElementById("save-path").value = defaultDownloadDir;
        
        renderAll();
        switchTab("tab-downloading");
      } else {
        const err = await res.json();
        showToast(err.detail || "添加任务失败", "error");
      }
    } catch (err) {
      showToast("网络请求失败，请检查连通性", "error");
    }
  });
}

// --------------------------------------------------------------------------
// UI Rendering & Task Management
// --------------------------------------------------------------------------
function renderAll() {
  const downloadingList = document.getElementById("downloading-list");
  const historyList = document.getElementById("history-list");
  const downloadingCount = document.getElementById("downloading-count");
  const historyCount = document.getElementById("history-count");

  const activeTasks = [];
  const historyTasks = [];

  tasksMap.forEach(task => {
    if (["pending", "downloading", "merging", "paused"].includes(task.status)) {
      activeTasks.push(task);
    } else {
      historyTasks.push(task);
    }
  });

  // Update Counters
  downloadingCount.textContent = activeTasks.length;
  historyCount.textContent = historyTasks.length;

  // Sort Tasks (newest completed/created at the VERY TOP)
  activeTasks.sort((a, b) => getTaskSortTime(b) - getTaskSortTime(a));
  historyTasks.sort((a, b) => getTaskSortTime(b) - getTaskSortTime(a));

  // Render Downloading
  if (activeTasks.length === 0) {
    downloadingList.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M21 15v4a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2v-4"></path><polyline points="7 10 12 15 17 10"></polyline><line x1="12" y1="15" x2="12" y2="3"></line></svg>
        </div>
        <h3>暂无正在下载的任务</h3>
        <p>前往“添加下载”页面输入 M3U8 视频链接开始体验吧！</p>
      </div>`;
  } else {
    downloadingList.innerHTML = activeTasks.map(createTaskCardHtml).join("");
  }

  // Render History
  if (historyTasks.length === 0) {
    historyList.innerHTML = `
      <div class="empty-state">
        <div class="empty-icon">
          <svg viewBox="0 0 24 24" width="48" height="48" fill="none" stroke="currentColor" stroke-width="1.5"><path d="M12 8v4l3 3"></path><circle cx="12" cy="12" r="10"></circle></svg>
        </div>
        <h3>暂无下载历史记录</h3>
        <p>完成的下载任务会自动归档保存在这里。</p>
      </div>`;
  } else {
    historyList.innerHTML = historyTasks.map(createHistoryCardHtml).join("");
  }
}

function createTaskCardHtml(task) {
  const statusMap = {
    pending: { label: "准备中", class: "paused" },
    downloading: { label: "下载中", class: "downloading" },
    merging: { label: "切片合并中", class: "merging" },
    paused: { label: "已暂停", class: "paused" }
  };

  const statusInfo = statusMap[task.status] || { label: task.status, class: "downloading" };
  const progressPercent = task.progress || 0;
  const isDownloading = task.status === "downloading";

  return `
    <div class="task-card" data-id="${task.id}">
      <div class="task-card-header">
        <div class="task-info">
          <h3>${escapeHtml(task.title || task.filename)}</h3>
          <p>${escapeHtml(task.url)}</p>
        </div>
        <span class="badge-status ${statusInfo.class}">${statusInfo.label}</span>
      </div>

      <div class="progress-container">
        <div class="progress-bar-bg">
          <div class="progress-bar-fill ${isDownloading ? 'active' : ''}" style="width: ${progressPercent}%"></div>
        </div>
        <div class="progress-metrics">
          <span>进度: ${progressPercent.toFixed(1)}%</span>
          <span>${formatBytes(task.downloaded_bytes)} ${task.total_bytes ? '/ ' + formatBytes(task.total_bytes) : ''}</span>
        </div>
      </div>

      <div class="task-details">
        <div class="detail-item">
          <span>🧩 片段:</span>
          <strong>${task.downloaded_segments} / ${task.total_segments || '?'} 片</strong>
        </div>
        <div class="detail-item">
          <span>⚡ 速率:</span>
          <strong>${formatSpeed(task.speed)}</strong>
        </div>
        <div class="detail-item">
          <span>⏱ 剩余:</span>
          <strong>${formatEta(task.eta)}</strong>
        </div>
        <div class="detail-item">
          <span>📁 目录:</span>
          <strong title="${escapeHtml(task.save_path)}">${escapeHtml(task.save_path)}</strong>
        </div>
      </div>

      <div class="card-actions">
        ${task.status === "downloading" ? `
          <button class="btn-action" onclick="pauseTask('${task.id}')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><rect x="6" y="4" width="4" height="16"></rect><rect x="14" y="4" width="4" height="16"></rect></svg>
            暂停
          </button>
        ` : ''}

        ${task.status === "paused" ? `
          <button class="btn-action" onclick="resumeTask('${task.id}')">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polygon points="5 3 19 12 5 21 5 3"></polygon></svg>
            恢复
          </button>
        ` : ''}

        <button class="btn-action danger" onclick="cancelTask('${task.id}')">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
          取消
        </button>
      </div>
    </div>`;
}

function createHistoryCardHtml(task) {
  const isSuccess = task.status === "completed";
  const statusClass = isSuccess ? "completed" : "failed";
  const statusLabel = isSuccess ? "已完成" : (task.status === "cancelled" ? "已取消" : "下载失败");

  return `
    <div class="task-card" data-id="${task.id}">
      <div class="task-card-header">
        <div class="task-info">
          <h3>${escapeHtml(task.title || task.filename)}</h3>
          <p>${escapeHtml(task.full_filepath || task.url)}</p>
        </div>
        <span class="badge-status ${statusClass}">${statusLabel}</span>
      </div>

      <div class="task-details">
        <div class="detail-item">
          <span>📦 大小:</span>
          <strong>${formatBytes(task.downloaded_bytes || task.total_bytes)}</strong>
        </div>
        <div class="detail-item">
          <span>🧩 片段:</span>
          <strong>${task.downloaded_segments} / ${task.total_segments || '?'} 片</strong>
        </div>
        <div class="detail-item">
          <span>🕒 完成时间:</span>
          <strong>${formatDate(task.completed_at || task.created_at)}</strong>
        </div>
        <div class="detail-item">
          <span>📁 保存路径:</span>
          <strong title="${escapeHtml(task.save_path)}">${escapeHtml(task.save_path)}</strong>
        </div>
      </div>

      ${task.error_message ? `
        <div style="font-size: 0.8rem; color: var(--accent-rose); background: rgba(244,63,94,0.1); padding: 0.5rem; border-radius: 6px;">
          ❌ 失败原因: ${escapeHtml(task.error_message)}
        </div>
      ` : ''}

      <div class="card-actions">
        <button class="btn-action" onclick="retryTask('${task.url}', '${escapeHtml(task.title)}')">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="23 4 23 10 17 10"></polyline><path d="M20.49 15a9 9 0 1 1-2.12-9.36L23 10"></path></svg>
          重新下载
        </button>

        <button class="btn-action danger" onclick="deleteTaskRecord('${task.id}', false)">
          <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><polyline points="3 6 5 6 21 6"></polyline><path d="M19 6v14a2 2 0 0 1-2 2H7a2 2 0 0 1-2-2V6m3 0V4a2 2 0 0 1 2-2h4a2 2 0 0 1 2 2v2"></path></svg>
          删除记录
        </button>

        ${isSuccess ? `
          <button class="btn-action danger" onclick="deleteTaskRecord('${task.id}', true)">
            <svg viewBox="0 0 24 24" width="14" height="14" fill="none" stroke="currentColor" stroke-width="2"><line x1="18" y1="6" x2="6" y2="18"></line><line x1="6" y1="6" x2="18" y2="18"></line></svg>
            删除记录+文件
          </button>
        ` : ''}
      </div>
    </div>`;
}

// --------------------------------------------------------------------------
// Actions
// --------------------------------------------------------------------------
async function pauseTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/pause`, { method: "POST" });
    if (res.ok) showToast("已暂停下载", "success");
  } catch (e) {
    showToast("操作失败", "error");
  }
}

async function resumeTask(taskId) {
  try {
    const res = await fetch(`/api/tasks/${taskId}/resume`, { method: "POST" });
    if (res.ok) showToast("已恢复下载", "success");
  } catch (e) {
    showToast("操作失败", "error");
  }
}

async function cancelTask(taskId) {
  if (!confirm("确定要取消此下载任务吗？")) return;
  try {
    const res = await fetch(`/api/tasks/${taskId}/cancel`, { method: "POST" });
    if (res.ok) showToast("已取消任务", "success");
  } catch (e) {
    showToast("操作失败", "error");
  }
}

async function deleteTaskRecord(taskId, deleteFile) {
  const msg = deleteFile ? "确定要删除此记录以及磁盘上的媒体文件吗？" : "确定要删除此历史记录吗？";
  if (!confirm(msg)) return;

  try {
    const res = await fetch(`/api/tasks/${taskId}?delete_file=${deleteFile}`, { method: "DELETE" });
    if (res.ok) {
      tasksMap.delete(taskId);
      renderAll();
      showToast("已删除记录", "success");
    }
  } catch (e) {
    showToast("删除操作失败", "error");
  }
}

function retryTask(url, title) {
  switchTab("tab-add");
  document.getElementById("m3u8-url").value = url;
  document.getElementById("video-title").value = title || "";
  showToast("参数已填入表单，可点击下载", "success");
}

// --------------------------------------------------------------------------
// Utilities
// --------------------------------------------------------------------------
function formatBytes(bytes) {
  if (!bytes || bytes === 0) return "0 B";
  const k = 1024;
  const sizes = ["B", "KB", "MB", "GB", "TB"];
  const i = Math.floor(Math.log(bytes) / Math.log(k));
  return parseFloat((bytes / Math.pow(k, i)).toFixed(2)) + " " + sizes[i];
}

function formatSpeed(bytesPerSec) {
  if (!bytesPerSec || bytesPerSec === 0) return "0 KB/s";
  return formatBytes(bytesPerSec) + "/s";
}

function formatEta(seconds) {
  if (!seconds || seconds <= 0) return "--:--";
  const mins = Math.floor(seconds / 60);
  const secs = seconds % 60;
  return `${mins.toString().padStart(2, '0')}:${secs.toString().padStart(2, '0')}`;
}

function parseTaskTime(dateStr) {
  if (!dateStr) return 0;
  let iso = String(dateStr).trim().replace(" ", "T");
  if (iso.includes(".")) {
    iso = iso.split(".")[0];
  }
  const t = Date.parse(iso);
  return isNaN(t) ? 0 : t;
}

function getTaskSortTime(t) {
  return parseTaskTime(t.completed_at) || parseTaskTime(t.created_at);
}

function formatDate(isoStr) {
  if (!isoStr) return "-";
  try {
    const t = parseTaskTime(isoStr);
    if (!t) return isoStr;
    const date = new Date(t);
    return date.toLocaleString("zh-CN", { hour12: false });
  } catch (e) {
    return isoStr;
  }
}

function escapeHtml(str) {
  if (!str) return "";
  return str.replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;").replace(/"/g, "&quot;").replace(/'/g, "&#039;");
}

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.textContent = message;
  container.appendChild(toast);

  setTimeout(() => {
    toast.style.opacity = "0";
    toast.style.transform = "translateX(40px)";
    toast.style.transition = "all 0.3s ease";
    setTimeout(() => toast.remove(), 300);
  }, 3000);
}
