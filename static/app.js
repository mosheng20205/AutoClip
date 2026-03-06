const $ = (sel) => document.querySelector(sel);
const $$ = (sel) => document.querySelectorAll(sel);

let taskId = null;
let segments = [];

// ───── Upload ─────

const dropZone = $("#drop-zone");
const fileInput = $("#file-input");

dropZone.addEventListener("click", () => fileInput.click());
dropZone.addEventListener("dragover", (e) => { e.preventDefault(); dropZone.classList.add("border-blue-500"); });
dropZone.addEventListener("dragleave", () => dropZone.classList.remove("border-blue-500"));
dropZone.addEventListener("drop", (e) => {
    e.preventDefault();
    dropZone.classList.remove("border-blue-500");
    if (e.dataTransfer.files.length) uploadFile(e.dataTransfer.files[0]);
});
fileInput.addEventListener("change", () => { if (fileInput.files.length) uploadFile(fileInput.files[0]); });

async function uploadFile(file) {
    $("#drop-text").classList.add("hidden");
    $("#upload-progress").classList.remove("hidden");
    $("#upload-filename").textContent = file.name;
    $("#upload-status").textContent = "上传中...";
    $("#progress-bar").style.width = "0%";

    const form = new FormData();
    form.append("file", file);

    const xhr = new XMLHttpRequest();
    xhr.open("POST", "/api/upload");

    xhr.upload.onprogress = (e) => {
        if (e.lengthComputable) {
            const pct = Math.round((e.loaded / e.total) * 100);
            $("#progress-bar").style.width = pct + "%";
            $("#upload-status").textContent = `上传中... ${pct}%`;
        }
    };

    xhr.onload = () => {
        if (xhr.status === 200) {
            const data = JSON.parse(xhr.responseText);
            taskId = data.task_id;
            $("#upload-status").textContent = "上传完成！";
            $("#progress-bar").style.width = "100%";
            $("#sec-transcribe").classList.remove("hidden");
        } else {
            $("#upload-status").textContent = "上传失败: " + xhr.responseText;
            $("#upload-status").classList.add("text-red-400");
        }
    };
    xhr.onerror = () => {
        $("#upload-status").textContent = "网络错误，上传失败";
        $("#upload-status").classList.add("text-red-400");
    };
    xhr.send(form);
}

// ───── Transcribe ─────

$("#btn-transcribe").addEventListener("click", async () => {
    if (!taskId) return;

    $("#btn-transcribe").disabled = true;
    $("#transcribe-status").classList.remove("hidden");
    $("#transcribe-loading").classList.remove("hidden");
    $("#transcribe-error").classList.add("hidden");

    try {
        await fetch(`/api/transcribe/${taskId}`, { method: "POST" });
        pollStatus();
    } catch (e) {
        showTranscribeError("请求失败: " + e.message);
    }
});

async function pollStatus() {
    const poll = async () => {
        try {
            const resp = await fetch(`/api/status/${taskId}`);
            const data = await resp.json();

            if (data.status === "transcribed" && data.segments) {
                segments = data.segments;
                $("#transcribe-loading").classList.add("hidden");
                renderSegments();
                $("#sec-highlights").classList.remove("hidden");
                return;
            }
            if (data.status === "error") {
                showTranscribeError(data.error || "转录失败");
                return;
            }
            setTimeout(poll, 2000);
        } catch (e) {
            showTranscribeError("轮询失败: " + e.message);
        }
    };
    poll();
}

function showTranscribeError(msg) {
    $("#transcribe-loading").classList.add("hidden");
    $("#transcribe-error").classList.remove("hidden");
    $("#transcribe-error").textContent = msg;
    $("#btn-transcribe").disabled = false;
}

// ───── Segment List ─────

function renderSegments(highlightKeywords = []) {
    const container = $("#segment-list");
    container.innerHTML = "";

    segments.forEach((seg, i) => {
        const row = document.createElement("div");
        row.className = "seg-row";
        row.dataset.index = i;

        const cb = document.createElement("input");
        cb.type = "checkbox";
        cb.dataset.index = i;

        const timeSpan = document.createElement("span");
        timeSpan.className = "seg-time";
        timeSpan.textContent = `${fmtTime(seg.start)} - ${fmtTime(seg.end)}`;

        const textSpan = document.createElement("span");
        textSpan.className = "seg-text";

        if (highlightKeywords.length > 0) {
            textSpan.innerHTML = highlightText(seg.text, highlightKeywords);
        } else {
            textSpan.textContent = seg.text;
        }

        row.appendChild(cb);
        row.appendChild(timeSpan);
        row.appendChild(textSpan);

        row.addEventListener("click", (e) => {
            if (e.target === cb) return;
            cb.checked = !cb.checked;
            updateSelection();
        });
        cb.addEventListener("change", updateSelection);

        container.appendChild(row);
    });
    updateSelection();
}

function updateSelection() {
    const boxes = $$("#segment-list input[type='checkbox']");
    let count = 0;
    let duration = 0;

    boxes.forEach((cb) => {
        const row = cb.closest(".seg-row");
        const i = parseInt(cb.dataset.index);
        if (cb.checked) {
            count++;
            duration += segments[i].end - segments[i].start;
            row.classList.add("selected");
        } else {
            row.classList.remove("selected");
        }
    });

    $("#selected-count").textContent = count;
    $("#selected-duration").textContent = fmtTime(duration);
    $("#btn-clip").disabled = count === 0;
}

function getSelectedIndices() {
    const indices = [];
    $$("#segment-list input[type='checkbox']").forEach((cb) => {
        if (cb.checked) indices.push(parseInt(cb.dataset.index));
    });
    return indices;
}

function setSelectedIndices(indices) {
    const idxSet = new Set(indices);
    $$("#segment-list input[type='checkbox']").forEach((cb) => {
        cb.checked = idxSet.has(parseInt(cb.dataset.index));
    });
    updateSelection();
}

// ───── Keyword Search ─────

$("#btn-keyword").addEventListener("click", async () => {
    const raw = $("#keyword-input").value.trim();
    if (!raw || !taskId) return;

    const keywords = raw.split(/[,，]/).map(s => s.trim()).filter(Boolean);

    try {
        const resp = await fetch("/api/highlights/keyword", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_id: taskId, keywords }),
        });
        const data = await resp.json();
        renderSegments(keywords);
        setSelectedIndices(data.indices);
        highlightRows(data.indices);
    } catch (e) {
        alert("关键词搜索失败: " + e.message);
    }
});

// ───── LLM ─────

$("#btn-llm").addEventListener("click", async () => {
    if (!taskId) return;
    $("#btn-llm").disabled = true;
    $("#llm-loading").classList.remove("hidden");

    try {
        const resp = await fetch("/api/highlights/llm", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_id: taskId }),
        });
        const data = await resp.json();
        if (resp.ok) {
            renderSegments();
            setSelectedIndices(data.indices);
            highlightRows(data.indices);
        } else {
            alert("AI 分析失败: " + (data.detail || "未知错误"));
        }
    } catch (e) {
        alert("AI 分析失败: " + e.message);
    } finally {
        $("#btn-llm").disabled = false;
        $("#llm-loading").classList.add("hidden");
    }
});

// ───── Select All / Deselect ─────

$("#btn-select-all").addEventListener("click", () => {
    $$("#segment-list input[type='checkbox']").forEach(cb => cb.checked = true);
    updateSelection();
});
$("#btn-deselect").addEventListener("click", () => {
    $$("#segment-list input[type='checkbox']").forEach(cb => cb.checked = false);
    updateSelection();
});

// ───── Clip ─────

$("#btn-clip").addEventListener("click", async () => {
    const indices = getSelectedIndices();
    if (indices.length === 0) return;

    $("#sec-result").classList.remove("hidden");
    $("#clip-loading").classList.remove("hidden");
    $("#clip-done").classList.add("hidden");
    $("#btn-clip").disabled = true;

    try {
        const resp = await fetch("/api/clip", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ task_id: taskId, selected_indices: indices, merge: true }),
        });
        const data = await resp.json();
        if (resp.ok) {
            $("#clip-loading").classList.add("hidden");
            $("#clip-done").classList.remove("hidden");
            $("#download-link").href = data.download_url;
        } else {
            alert("剪辑失败: " + (data.detail || "未知错误"));
            $("#clip-loading").classList.add("hidden");
        }
    } catch (e) {
        alert("剪辑失败: " + e.message);
        $("#clip-loading").classList.add("hidden");
    } finally {
        $("#btn-clip").disabled = false;
    }
});

// ───── Helpers ─────

function fmtTime(sec) {
    const total = Math.round(sec);
    const m = Math.floor(total / 60);
    const s = total % 60;
    const h = Math.floor(m / 60);
    const mm = m % 60;
    if (h > 0) return `${h}:${String(mm).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
    return `${mm}:${String(s).padStart(2, "0")}`;
}

function highlightText(text, keywords) {
    if (!keywords.length) return escapeHtml(text);
    const escaped = keywords.map(k => k.replace(/[.*+?^${}()|[\]\\]/g, "\\$&"));
    const re = new RegExp(`(${escaped.join("|")})`, "gi");
    return escapeHtml(text).replace(re, "<mark>$1</mark>");
}

function escapeHtml(str) {
    const div = document.createElement("div");
    div.textContent = str;
    return div.innerHTML;
}

function highlightRows(indices) {
    const idxSet = new Set(indices);
    $$("#segment-list .seg-row").forEach((row) => {
        if (idxSet.has(parseInt(row.dataset.index))) {
            row.classList.add("highlighted");
        } else {
            row.classList.remove("highlighted");
        }
    });
}
