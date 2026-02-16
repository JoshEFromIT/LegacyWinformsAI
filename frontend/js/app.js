/**
 * RDP Recorder — Frontend Application
 *
 * Manages session lifecycle, screenshot upload, and results display
 * with Mermaid diagram rendering.
 *
 * Uses local Ollama LLM for AI vision analysis (no cloud APIs required).
 */

const API = '/api';

// --- State ---
let activeSessionId = null;

// --- DOM References ---
const sessionPanel = document.getElementById('session-panel');
const recordingPanel = document.getElementById('recording-panel');
const resultsPanel = document.getElementById('results-panel');
const loadingOverlay = document.getElementById('loading-overlay');
const loadingText = document.getElementById('loading-text');

// --- Initialize Mermaid ---
let mermaidReady = false;
try {
    mermaid.initialize({
        startOnLoad: false,
        theme: 'default',
        securityLevel: 'loose',
        flowchart: { useMaxWidth: true, htmlLabels: true },
        sequence: { useMaxWidth: true },
    });
    mermaidReady = true;
} catch (err) {
    console.error('Mermaid failed to initialize:', err);
}

// ============================================
// Session Management
// ============================================

document.getElementById('btn-create-session').addEventListener('click', async () => {
    const displayName = document.getElementById('display-name').value.trim();
    const host = document.getElementById('rdp-host').value.trim();
    const port = parseInt(document.getElementById('rdp-port').value) || 3389;
    const interval = parseFloat(document.getElementById('capture-interval').value) || 2;

    const body = {
        display_name: displayName || 'Untitled Session',
        host: host,
        port: port,
        capture_interval_seconds: interval,
    };

    try {
        const resp = await fetch(`${API}/sessions`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify(body),
        });
        const session = await resp.json();
        openSession(session.session_id);
    } catch (err) {
        alert('Failed to create session: ' + err.message);
    }
});

async function loadSessions() {
    try {
        const resp = await fetch(`${API}/sessions`);
        const sessions = await resp.json();
        renderSessionList(sessions);
    } catch (err) {
        console.error('Failed to load sessions:', err);
    }
}

function renderSessionList(sessions) {
    const list = document.getElementById('session-list');
    if (!sessions.length) {
        list.innerHTML = '<p style="color:var(--text-muted);font-size:0.85rem;">No sessions yet. Create one above.</p>';
        return;
    }

    list.innerHTML = sessions.map(s => {
        const name = s.config?.display_name || s.session_id;
        const captures = s.captures?.length || 0;
        const status = s.status;
        const badgeClass = `badge badge-${status}`;
        const date = new Date(s.created_at).toLocaleString();

        return `
            <div class="session-item" onclick="openSession('${s.session_id}')">
                <div class="session-item-info">
                    <div class="session-item-name">${escapeHtml(name)}</div>
                    <div class="session-item-meta">${date} &middot; ${captures} captures</div>
                </div>
                <div class="session-item-actions">
                    <span class="${badgeClass}">${status}</span>
                    <button class="btn btn-secondary btn-sm" onclick="event.stopPropagation(); deleteSession('${s.session_id}')">Delete</button>
                </div>
            </div>
        `;
    }).join('');
}

async function openSession(sessionId) {
    activeSessionId = sessionId;
    sessionPanel.style.display = 'none';
    resultsPanel.style.display = 'none';
    recordingPanel.style.display = 'block';

    await refreshSessionState();
}

async function refreshSessionState() {
    if (!activeSessionId) return;

    try {
        const resp = await fetch(`${API}/sessions/${activeSessionId}`);
        const session = await resp.json();

        const name = session.config?.display_name || session.session_id;
        document.getElementById('active-session-title').textContent = name;

        const badge = document.getElementById('status-badge');
        badge.textContent = session.status;
        badge.className = `badge badge-${session.status}`;

        document.getElementById('capture-count').textContent =
            `${session.captures?.length || 0} captures`;

        // Button state is driven by browser screen capture, not server status
        const isCapturing = screenStream !== null;
        document.getElementById('btn-start-rec').disabled = isCapturing;
        document.getElementById('btn-stop-rec').disabled = !isCapturing;

        renderFilmstrip(session);

        if (session.result) {
            document.getElementById('btn-analyze').textContent = 'Re-Analyze';
        }
    } catch (err) {
        console.error('Failed to refresh session:', err);
    }
}

function renderFilmstrip(session) {
    const strip = document.getElementById('filmstrip');
    if (!session.captures?.length) {
        strip.innerHTML = '<p style="color:var(--text-muted);font-size:0.82rem;">No captures yet</p>';
        return;
    }

    strip.innerHTML = session.captures.map((cap, i) => `
        <div class="filmstrip-item">
            <img src="${API}/sessions/${session.session_id}/captures/${cap.capture_id}/image"
                 alt="Capture ${i+1}" loading="lazy">
            <span class="frame-number">#${i+1}</span>
        </div>
    `).join('');
}

async function deleteSession(sessionId) {
    if (!confirm('Delete this session and all its data?')) return;
    try {
        await fetch(`${API}/sessions/${sessionId}`, { method: 'DELETE' });
        loadSessions();
    } catch (err) {
        alert('Failed to delete: ' + err.message);
    }
}

// ============================================
// Browser-Based Screen Capture (getDisplayMedia)
// ============================================

let screenStream = null;       // MediaStream from getDisplayMedia
let captureTimer = null;       // setInterval ID for periodic frame grabs
let captureFrameCount = 0;

document.getElementById('btn-start-rec').addEventListener('click', async () => {
    if (!activeSessionId) return;

    try {
        // Prompt user to pick a screen/window/tab to share
        screenStream = await navigator.mediaDevices.getDisplayMedia({
            video: { cursor: 'always' },
            audio: false,
        });
    } catch (err) {
        // User cancelled the picker or browser doesn't support it
        if (err.name === 'NotAllowedError') {
            alert('Screen sharing was cancelled. Click "Start Screen Capture" and select your RDP window or screen.');
        } else {
            alert('Screen capture not supported in this browser: ' + err.message);
        }
        return;
    }

    // Wire up the video element so we can grab frames from it
    const video = document.getElementById('screen-video');
    video.srcObject = screenStream;
    await video.play();

    // When user clicks "Stop sharing" in the browser chrome bar
    screenStream.getVideoTracks()[0].addEventListener('ended', () => {
        stopScreenCapture();
    });

    // Read the capture interval from the session config
    const intervalInput = document.getElementById('capture-interval');
    const interval = (parseFloat(intervalInput.value) || 2) * 1000;

    captureFrameCount = 0;
    showCaptureStatus('Capturing screen...');

    // Update button states
    document.getElementById('btn-start-rec').disabled = true;
    document.getElementById('btn-stop-rec').disabled = false;

    // Periodic frame grabber: snapshot the video to canvas, upload as PNG
    captureTimer = setInterval(() => grabAndUploadFrame(video), interval);

    // Grab the first frame immediately
    grabAndUploadFrame(video);
});

document.getElementById('btn-stop-rec').addEventListener('click', () => {
    stopScreenCapture();
});

async function grabAndUploadFrame(video) {
    if (!activeSessionId || !video.videoWidth) return;

    try {
        const canvas = document.createElement('canvas');
        canvas.width = video.videoWidth;
        canvas.height = video.videoHeight;
        const ctx = canvas.getContext('2d');
        ctx.drawImage(video, 0, 0);

        const blob = await new Promise(resolve => canvas.toBlob(resolve, 'image/png'));
        const formData = new FormData();
        formData.append('file', blob, `capture_${Date.now()}.png`);

        await fetch(`${API}/sessions/${activeSessionId}/frames`, {
            method: 'POST',
            body: formData,
        });

        captureFrameCount++;
        showCaptureStatus(`Capturing screen... (${captureFrameCount} frames)`);
        refreshSessionState();
    } catch (err) {
        console.error('Frame capture/upload failed:', err);
    }
}

function stopScreenCapture() {
    // Stop the interval timer
    if (captureTimer) {
        clearInterval(captureTimer);
        captureTimer = null;
    }

    // Stop all media tracks (releases the screen share)
    if (screenStream) {
        screenStream.getTracks().forEach(t => t.stop());
        screenStream = null;
    }

    // Clear the video element
    const video = document.getElementById('screen-video');
    video.srcObject = null;

    // Update UI
    document.getElementById('btn-start-rec').disabled = false;
    document.getElementById('btn-stop-rec').disabled = true;
    hideCaptureStatus();
    refreshSessionState();
}

function showCaptureStatus(text) {
    const el = document.getElementById('capture-status');
    el.style.display = 'flex';
    document.getElementById('capture-status-text').textContent = text;
}

function hideCaptureStatus() {
    document.getElementById('capture-status').style.display = 'none';
}

document.getElementById('btn-analyze').addEventListener('click', () => {
    showLoading('Connecting to local AI (Ollama)...');
    showProgress(0, 0, 0);

    const evtSource = new EventSource(
        `${API}/sessions/${activeSessionId}/analyze/stream`
    );

    evtSource.addEventListener('progress', (e) => {
        const d = JSON.parse(e.data);
        updateLoadingText(`Analyzing screenshot ${d.completed} of ${d.total}...`);
        showProgress(d.completed, d.total, d.percent);
        updateProgressNarrative(d.narrative);
    });

    evtSource.addEventListener('complete', (e) => {
        evtSource.close();
        hideLoading();
        const session = JSON.parse(e.data);
        if (session.result) {
            showResults(session.result);
        } else {
            alert('Analysis completed but produced no result.');
        }
    });

    evtSource.addEventListener('error', (e) => {
        // SSE 'error' event can be a server-sent error or a connection error
        if (e.data) {
            const d = JSON.parse(e.data);
            evtSource.close();
            hideLoading();
            alert('Analysis failed: ' + (d.message || 'Unknown error'));
        } else {
            // Connection error — EventSource will auto-reconnect, but we
            // close it and show an error since our stream is one-shot.
            evtSource.close();
            hideLoading();
            alert('Lost connection to analysis stream. Check that the server is running.');
        }
    });
});

document.getElementById('btn-back').addEventListener('click', () => {
    stopScreenCapture();
    activeSessionId = null;
    recordingPanel.style.display = 'none';
    sessionPanel.style.display = 'block';
    loadSessions();
});

document.getElementById('btn-back-from-results').addEventListener('click', () => {
    resultsPanel.style.display = 'none';
    recordingPanel.style.display = 'block';
});


// ============================================
// File Upload (Drag & Drop + Click)
// ============================================

const uploadZone = document.getElementById('upload-zone');
const fileInput = document.getElementById('file-input');

uploadZone.addEventListener('click', () => fileInput.click());

uploadZone.addEventListener('dragover', (e) => {
    e.preventDefault();
    uploadZone.classList.add('dragover');
});

uploadZone.addEventListener('dragleave', () => {
    uploadZone.classList.remove('dragover');
});

uploadZone.addEventListener('drop', async (e) => {
    e.preventDefault();
    uploadZone.classList.remove('dragover');

    const files = Array.from(e.dataTransfer.files).filter(f => f.type.startsWith('image/'));
    if (files.length) {
        await uploadFiles(files);
    }
});

fileInput.addEventListener('change', async () => {
    const files = Array.from(fileInput.files);
    if (files.length) {
        await uploadFiles(files);
    }
    fileInput.value = '';
});

async function uploadFiles(files) {
    if (!activeSessionId) return;

    for (const file of files) {
        try {
            const formData = new FormData();
            formData.append('file', file);

            await fetch(`${API}/sessions/${activeSessionId}/frames`, {
                method: 'POST',
                body: formData,
            });
        } catch (err) {
            console.error('Upload failed for', file.name, err);
        }
    }

    refreshSessionState();
}

// ============================================
// Results Display
// ============================================

// Store diagram code for the live editor (editable copies + originals for reset)
let editorDiagramSources = { flowchart: '', sequence: '', state: '' };
let editorOriginalSources = { flowchart: '', sequence: '', state: '' };
let editorActiveDiagram = 'flowchart';
let editorDebounceTimer = null;

async function showResults(result) {
    recordingPanel.style.display = 'none';
    resultsPanel.style.display = 'block';

    // Store original sources for the live editor
    editorOriginalSources = {
        flowchart: result.mermaid_flowchart || '',
        sequence: result.mermaid_sequence || '',
        state: result.mermaid_state || '',
    };
    editorDiagramSources = { ...editorOriginalSources };

    // Narrative (render markdown-like content)
    document.getElementById('narrative-content').innerHTML = renderNarrative(result.narrative || '');

    // Render mermaid diagrams in read-only tabs
    await renderMermaidDiagram('mermaid-flowchart', result.mermaid_flowchart);
    await renderMermaidDiagram('mermaid-sequence', result.mermaid_sequence);
    await renderMermaidDiagram('mermaid-state', result.mermaid_state);

    // Initialize the live editor with the flowchart
    editorActiveDiagram = 'flowchart';
    editorLoadDiagram('flowchart');
}

async function renderMermaidDiagram(containerId, code) {
    const container = document.getElementById(containerId);
    if (!mermaidReady) {
        container.innerHTML = '<pre style="color:#ef5350;">Mermaid library failed to load. Check browser console (F12) for errors.\nIf on a corporate network, mermaid.min.js may be blocked.</pre>';
        return;
    }
    if (!code) {
        container.innerHTML = '<p style="color:#999;">No diagram data available.</p>';
        return;
    }

    try {
        const id = `mermaid-${containerId}-${Date.now()}`;
        const { svg } = await mermaid.render(id, code);
        container.innerHTML = svg;
    } catch (err) {
        console.error('Mermaid render error for', containerId, err);
        container.innerHTML = `<pre style="color:#ef5350;">Diagram render error:\n${escapeHtml(err.message)}\n\nRaw code:\n${escapeHtml(code)}</pre>`;
    }
}

function renderNarrative(text) {
    // Simple markdown-like rendering
    return text
        .replace(/^### (.+)$/gm, '<h3>$1</h3>')
        .replace(/^## (.+)$/gm, '<h2>$1</h2>')
        .replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>')
        .replace(/\*\((.+?)\)\*/g, '<em>($1)</em>')
        .replace(/\*(.+?)\*/g, '<em>$1</em>')
        .replace(/\n\n/g, '</p><p>')
        .replace(/\n/g, '<br>')
        .replace(/^/, '<p>')
        .replace(/$/, '</p>');
}

// ============================================
// Live Mermaid Editor
// ============================================

function editorLoadDiagram(diagramType) {
    editorActiveDiagram = diagramType;
    const textarea = document.getElementById('editor-textarea');
    textarea.value = editorDiagramSources[diagramType] || '';

    // Update selector buttons
    document.querySelectorAll('.editor-diagram-btn').forEach(btn => {
        btn.classList.toggle('active', btn.dataset.diagram === diagramType);
    });

    // Clear errors and render
    document.getElementById('editor-error').textContent = '';
    editorRenderPreview();
}

async function editorRenderPreview() {
    const code = document.getElementById('editor-textarea').value.trim();
    const preview = document.getElementById('editor-preview');
    const errorEl = document.getElementById('editor-error');

    if (!mermaidReady) {
        preview.innerHTML = '<p style="color:#ef5350;">Mermaid library not loaded.</p>';
        return;
    }

    if (!code) {
        preview.innerHTML = '<p style="color:#999;">Enter Mermaid code on the left to see a live preview.</p>';
        errorEl.textContent = '';
        return;
    }

    try {
        const id = `editor-preview-${Date.now()}`;
        const { svg } = await mermaid.render(id, code);
        preview.innerHTML = svg;
        errorEl.textContent = '';
    } catch (err) {
        errorEl.textContent = err.message || 'Syntax error in Mermaid code';
        // Keep the last successful render visible
    }
}

// Debounced input handler for the editor textarea
document.getElementById('editor-textarea').addEventListener('input', () => {
    clearTimeout(editorDebounceTimer);
    editorDebounceTimer = setTimeout(editorRenderPreview, 400);
});

// Support Tab key for indentation in the textarea
document.getElementById('editor-textarea').addEventListener('keydown', (e) => {
    if (e.key === 'Tab') {
        e.preventDefault();
        const ta = e.target;
        const start = ta.selectionStart;
        const end = ta.selectionEnd;
        ta.value = ta.value.substring(0, start) + '    ' + ta.value.substring(end);
        ta.selectionStart = ta.selectionEnd = start + 4;
        // Trigger debounced render
        clearTimeout(editorDebounceTimer);
        editorDebounceTimer = setTimeout(editorRenderPreview, 400);
    }
});

// Diagram selector buttons
document.querySelectorAll('.editor-diagram-btn').forEach(btn => {
    btn.addEventListener('click', () => {
        // Save current edits back to sources before switching
        editorDiagramSources[editorActiveDiagram] = document.getElementById('editor-textarea').value;
        editorLoadDiagram(btn.dataset.diagram);
    });
});

function editorResetCode() {
    // Re-fetch original result for the active diagram would need a stored original.
    // We keep the original in editorDiagramSources, but edits overwrite it.
    // So we store originals separately.
    if (!editorOriginalSources[editorActiveDiagram]) return;
    editorDiagramSources[editorActiveDiagram] = editorOriginalSources[editorActiveDiagram];
    document.getElementById('editor-textarea').value = editorOriginalSources[editorActiveDiagram];
    editorRenderPreview();
}

function editorCopyCode() {
    const code = document.getElementById('editor-textarea').value;
    navigator.clipboard.writeText(code).then(() => {
        showEditorToast('Code copied');
    });
}

function editorCopySvg() {
    const svg = document.getElementById('editor-preview').innerHTML;
    if (!svg || svg.includes('<p')) return;
    navigator.clipboard.writeText(svg).then(() => {
        showEditorToast('SVG copied');
    });
}

function editorDownloadSvg() {
    const svg = document.getElementById('editor-preview').innerHTML;
    if (!svg || svg.includes('<p')) return;
    const blob = new Blob([svg], { type: 'image/svg+xml' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${editorActiveDiagram}-diagram.svg`;
    a.click();
    URL.revokeObjectURL(url);
}

function editorDownloadPng() {
    const svgEl = document.querySelector('#editor-preview svg');
    if (!svgEl) return;

    const svgData = new XMLSerializer().serializeToString(svgEl);
    const canvas = document.createElement('canvas');
    const ctx = canvas.getContext('2d');
    const img = new Image();

    img.onload = () => {
        // Use 2x for crisp export
        const scale = 2;
        canvas.width = img.width * scale;
        canvas.height = img.height * scale;
        ctx.fillStyle = '#ffffff';
        ctx.fillRect(0, 0, canvas.width, canvas.height);
        ctx.drawImage(img, 0, 0, canvas.width, canvas.height);

        canvas.toBlob((blob) => {
            const url = URL.createObjectURL(blob);
            const a = document.createElement('a');
            a.href = url;
            a.download = `${editorActiveDiagram}-diagram.png`;
            a.click();
            URL.revokeObjectURL(url);
        }, 'image/png');
    };

    img.src = 'data:image/svg+xml;base64,' + btoa(unescape(encodeURIComponent(svgData)));
}

function showEditorToast(message) {
    const errorEl = document.getElementById('editor-error');
    const prev = errorEl.textContent;
    errorEl.style.color = 'var(--accent-green)';
    errorEl.textContent = message;
    setTimeout(() => {
        errorEl.textContent = prev;
        errorEl.style.color = '';
    }, 1500);
}

// --- Tabs ---
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

        tab.classList.add('active');
        const pane = document.getElementById(`tab-${tab.dataset.tab}`);
        if (pane) pane.classList.add('active');

        // When switching to editor tab, trigger a render (in case code was loaded while hidden)
        if (tab.dataset.tab === 'editor') {
            editorRenderPreview();
        }
    });
});

// ============================================
// Utility Functions
// ============================================

function showLoading(text) {
    loadingText.textContent = text || 'Processing...';
    loadingOverlay.style.display = 'flex';
    // Reset progress UI
    document.getElementById('progress-bar-wrap').style.display = 'none';
    document.getElementById('progress-bar').style.width = '0%';
    document.getElementById('progress-fraction').textContent = '';
    document.getElementById('progress-percent').textContent = '';
    document.getElementById('progress-narrative').textContent = '';
}

function hideLoading() {
    loadingOverlay.style.display = 'none';
}

function updateLoadingText(text) {
    loadingText.textContent = text;
}

function showProgress(completed, total, percent) {
    const wrap = document.getElementById('progress-bar-wrap');
    wrap.style.display = 'block';
    document.getElementById('progress-bar').style.width = percent + '%';
    document.getElementById('progress-fraction').textContent = `${completed} / ${total}`;
    document.getElementById('progress-percent').textContent = percent + '%';
}

function updateProgressNarrative(text) {
    document.getElementById('progress-narrative').textContent = text || '';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function copyToClipboard(text) {
    navigator.clipboard.writeText(text);
}

// ============================================
// Ollama Status Check
// ============================================

async function checkOllamaStatus() {
    const statusEl = document.getElementById('ollama-status');
    try {
        const resp = await fetch(`${API}/health/ollama`);
        const health = await resp.json();

        // Build GGUF info note if applicable
        let ggufNote = '';
        if (health.gguf_configured && health.gguf_registered) {
            ggufNote = ' (GGUF loaded)';
        } else if (health.gguf_configured && !health.gguf_registered) {
            ggufNote = ' (GGUF detected, pending registration)';
        } else if (health.available_gguf_files && health.available_gguf_files.length > 0) {
            ggufNote = ` (${health.available_gguf_files.length} .gguf file${health.available_gguf_files.length > 1 ? 's' : ''} in models/)`;
        }

        if (health.ollama_reachable && health.model_ready) {
            statusEl.innerHTML = `<span class="ollama-connected">Ollama connected — ${escapeHtml(health.configured_model)}${ggufNote}</span>`;
            statusEl.className = 'ollama-status connected';
        } else if (health.ollama_reachable && !health.model_ready) {
            let hint = `model "${escapeHtml(health.configured_model)}" not found.`;
            if (health.gguf_configured) {
                hint += ` <a href="#" onclick="registerGgufModel(); return false;" style="color:var(--accent-blue);">Click to register GGUF</a>`;
            } else {
                hint += ` Run: ollama pull ${escapeHtml(health.configured_model)}`;
            }
            statusEl.innerHTML = `<span class="ollama-warning">Ollama connected — ${hint}${ggufNote}</span>`;
            statusEl.className = 'ollama-status warning';
        } else {
            statusEl.innerHTML = `<span class="ollama-disconnected">Ollama not reachable at ${escapeHtml(health.ollama_url)}${ggufNote}</span>`;
            statusEl.className = 'ollama-status disconnected';
        }
    } catch (err) {
        statusEl.innerHTML = '<span class="ollama-disconnected">Cannot check Ollama status</span>';
        statusEl.className = 'ollama-status disconnected';
    }
}

async function registerGgufModel() {
    const statusEl = document.getElementById('ollama-status');
    statusEl.innerHTML = '<span class="ollama-warning">Registering GGUF model with Ollama...</span>';
    statusEl.className = 'ollama-status warning';
    try {
        const resp = await fetch(`${API}/models/register-gguf`, { method: 'POST' });
        const result = await resp.json();
        if (resp.ok) {
            statusEl.innerHTML = `<span class="ollama-connected">GGUF registered as "${escapeHtml(result.model_name)}"</span>`;
            statusEl.className = 'ollama-status connected';
            setTimeout(checkOllamaStatus, 2000);
        } else {
            statusEl.innerHTML = `<span class="ollama-disconnected">Registration failed: ${escapeHtml(result.detail || 'Unknown error')}</span>`;
            statusEl.className = 'ollama-status disconnected';
        }
    } catch (err) {
        statusEl.innerHTML = `<span class="ollama-disconnected">Registration error: ${escapeHtml(err.message)}</span>`;
        statusEl.className = 'ollama-status disconnected';
    }
}

// --- Initial Load ---
loadSessions();
checkOllamaStatus();
// Re-check Ollama status periodically
setInterval(checkOllamaStatus, 30000);
