/**
 * RDP Recorder — Frontend Application
 *
 * Manages session lifecycle, screenshot upload, and results display
 * with Mermaid diagram rendering and Excalidraw MCP canvas integration.
 *
 * Uses local Ollama LLM for AI vision analysis (no cloud APIs required).
 */

const API = '/api';

// --- State ---
let activeSessionId = null;
let pollInterval = null;
let currentExcalidrawScenes = {};

// --- DOM References ---
const sessionPanel = document.getElementById('session-panel');
const recordingPanel = document.getElementById('recording-panel');
const resultsPanel = document.getElementById('results-panel');
const loadingOverlay = document.getElementById('loading-overlay');
const loadingText = document.getElementById('loading-text');

// --- Initialize Mermaid ---
mermaid.initialize({
    startOnLoad: false,
    theme: 'default',
    securityLevel: 'loose',
    flowchart: { useMaxWidth: true, htmlLabels: true },
    sequence: { useMaxWidth: true },
});

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

        const isRecording = session.status === 'recording';
        document.getElementById('btn-start-rec').disabled = isRecording;
        document.getElementById('btn-stop-rec').disabled = !isRecording;

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
// Recording Controls
// ============================================

document.getElementById('btn-start-rec').addEventListener('click', async () => {
    try {
        await fetch(`${API}/sessions/${activeSessionId}/start`, { method: 'POST' });
        startPolling();
        refreshSessionState();
    } catch (err) {
        alert('Failed to start recording: ' + err.message);
    }
});

document.getElementById('btn-stop-rec').addEventListener('click', async () => {
    try {
        await fetch(`${API}/sessions/${activeSessionId}/stop`, { method: 'POST' });
        stopPolling();
        refreshSessionState();
    } catch (err) {
        alert('Failed to stop recording: ' + err.message);
    }
});

document.getElementById('btn-analyze').addEventListener('click', async () => {
    showLoading('Analyzing screenshots with local AI (Ollama)... This may take a while depending on your hardware.');
    try {
        const resp = await fetch(`${API}/sessions/${activeSessionId}/analyze`, {
            method: 'POST',
        });
        const session = await resp.json();
        hideLoading();

        if (session.status === 'complete' && session.result) {
            showResults(session.result);
        } else if (session.status === 'error') {
            alert('Analysis failed: ' + (session.error_message || 'Unknown error'));
        }
    } catch (err) {
        hideLoading();
        alert('Analysis request failed: ' + err.message);
    }
});

document.getElementById('btn-back').addEventListener('click', () => {
    stopPolling();
    activeSessionId = null;
    recordingPanel.style.display = 'none';
    sessionPanel.style.display = 'block';
    loadSessions();
});

document.getElementById('btn-back-from-results').addEventListener('click', () => {
    resultsPanel.style.display = 'none';
    recordingPanel.style.display = 'block';
});

function startPolling() {
    stopPolling();
    pollInterval = setInterval(refreshSessionState, 3000);
}

function stopPolling() {
    if (pollInterval) {
        clearInterval(pollInterval);
        pollInterval = null;
    }
}

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

async function showResults(result) {
    recordingPanel.style.display = 'none';
    resultsPanel.style.display = 'block';

    // Raw mermaid text
    document.getElementById('raw-flowchart').textContent = result.mermaid_flowchart || '';
    document.getElementById('raw-sequence').textContent = result.mermaid_sequence || '';
    document.getElementById('raw-state').textContent = result.mermaid_state || '';

    // Narrative (render markdown-like content)
    document.getElementById('narrative-content').innerHTML = renderNarrative(result.narrative || '');

    // Render mermaid diagrams
    await renderMermaidDiagram('mermaid-flowchart', result.mermaid_flowchart);
    await renderMermaidDiagram('mermaid-sequence', result.mermaid_sequence);
    await renderMermaidDiagram('mermaid-state', result.mermaid_state);

    // Store Excalidraw scenes for the Excalidraw tab
    currentExcalidrawScenes = {
        ai_designed: result.excalidraw_ai_designed || null,
        flowchart: result.excalidraw_flowchart || null,
        sequence: result.excalidraw_sequence || null,
        state: result.excalidraw_state || null,
    };
    renderExcalidrawPreview();
}

async function renderMermaidDiagram(containerId, code) {
    const container = document.getElementById(containerId);
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

// --- Tabs ---
document.querySelectorAll('.tab').forEach(tab => {
    tab.addEventListener('click', () => {
        document.querySelectorAll('.tab').forEach(t => t.classList.remove('active'));
        document.querySelectorAll('.tab-pane').forEach(p => p.classList.remove('active'));

        tab.classList.add('active');
        const pane = document.getElementById(`tab-${tab.dataset.tab}`);
        if (pane) pane.classList.add('active');
    });
});

// ============================================
// Utility Functions
// ============================================

function showLoading(text) {
    loadingText.textContent = text || 'Processing...';
    loadingOverlay.style.display = 'flex';
}

function hideLoading() {
    loadingOverlay.style.display = 'none';
}

function escapeHtml(str) {
    const div = document.createElement('div');
    div.textContent = str;
    return div.innerHTML;
}

function copyToClipboard(elementId) {
    const text = document.getElementById(elementId).textContent;
    navigator.clipboard.writeText(text).then(() => {
        const btn = event.target;
        const original = btn.textContent;
        btn.textContent = 'Copied!';
        setTimeout(() => { btn.textContent = original; }, 1500);
    });
}

// ============================================
// Excalidraw Integration
// ============================================

function renderExcalidrawPreview() {
    const preview = document.getElementById('excalidraw-preview');
    const select = document.getElementById('excalidraw-diagram-select');
    const diagramType = select.value;
    const scene = currentExcalidrawScenes[diagramType];

    const isAiDesigned = diagramType === 'ai_designed';

    if (!scene || !scene.elements || scene.elements.length === 0) {
        const hint = isAiDesigned
            ? 'The AI will design this diagram during analysis using the Ollama model.'
            : 'Ensure the Excalidraw MCP canvas server is running during analysis.';
        preview.innerHTML = `
            <div class="excalidraw-empty">
                <p>No Excalidraw diagram available for this type.</p>
                <p style="font-size:0.8rem;color:var(--text-muted);">${hint}</p>
            </div>`;
        return;
    }

    const elementCount = scene.elements.length;
    const types = {};
    scene.elements.forEach(el => {
        types[el.type] = (types[el.type] || 0) + 1;
    });
    const typesSummary = Object.entries(types)
        .map(([t, c]) => `${c} ${t}${c > 1 ? 's' : ''}`)
        .join(', ');

    const badgeLabel = isAiDesigned ? 'AI Designed' : 'Scene Ready';
    const badgeClass = isAiDesigned ? 'badge-analyzing' : 'badge-complete';
    const sourceNote = isAiDesigned
        ? '<span style="font-size:0.75rem;color:var(--accent-amber);">Designed directly by the AI — richer layout than Mermaid conversion</span>'
        : '';

    preview.innerHTML = `
        <div class="excalidraw-scene-info">
            <div class="excalidraw-scene-header">
                <span class="badge ${badgeClass}">${badgeLabel}</span>
                <span style="font-size:0.82rem;color:var(--text-secondary);">${elementCount} elements (${typesSummary})</span>
                ${sourceNote}
            </div>
            <div class="excalidraw-canvas-frame">
                <iframe id="excalidraw-iframe"
                    src="${getExcalidrawCanvasUrl()}"
                    style="width:100%;height:500px;border:none;border-radius:var(--radius);"
                    title="Excalidraw Canvas">
                </iframe>
            </div>
            <div class="excalidraw-actions" style="margin-top:0.8rem;">
                <button class="btn btn-primary btn-sm" onclick="loadSceneToCanvas()">Load Diagram to Canvas</button>
                <button class="btn btn-secondary btn-sm" onclick="downloadExcalidrawJson()">Download .excalidraw</button>
            </div>
        </div>`;
}

function getExcalidrawCanvasUrl() {
    // When running in Docker, the canvas is on port 3000
    // From the browser, we connect to the host-exposed port
    const loc = window.location;
    return `${loc.protocol}//${loc.hostname}:3000`;
}

async function loadSceneToCanvas() {
    const select = document.getElementById('excalidraw-diagram-select');
    const diagramType = select.value;
    const scene = currentExcalidrawScenes[diagramType];

    if (!scene || !scene.elements) {
        alert('No Excalidraw scene data available for this diagram type.');
        return;
    }

    try {
        const canvasUrl = getExcalidrawCanvasUrl();

        // Clear existing elements on the canvas
        await fetch(`${canvasUrl}/api/elements/clear`, { method: 'DELETE' });

        // Batch-create the elements
        const resp = await fetch(`${canvasUrl}/api/elements/batch`, {
            method: 'POST',
            headers: { 'Content-Type': 'application/json' },
            body: JSON.stringify({ elements: scene.elements }),
        });

        if (resp.ok) {
            // Scroll to content
            await fetch(`${canvasUrl}/api/viewport`, {
                method: 'POST',
                headers: { 'Content-Type': 'application/json' },
                body: JSON.stringify({ scrollToContent: true }),
            });

            // Reload the iframe
            const iframe = document.getElementById('excalidraw-iframe');
            if (iframe) iframe.src = iframe.src;
        } else {
            alert('Failed to load scene to canvas.');
        }
    } catch (err) {
        alert('Could not connect to Excalidraw canvas: ' + err.message);
    }
}

function openExcalidrawCanvas() {
    window.open(getExcalidrawCanvasUrl(), '_blank');
}

function downloadExcalidrawJson() {
    const select = document.getElementById('excalidraw-diagram-select');
    const diagramType = select.value;
    const scene = currentExcalidrawScenes[diagramType];

    if (!scene) {
        alert('No Excalidraw scene data available for this diagram type.');
        return;
    }

    const blob = new Blob([JSON.stringify(scene, null, 2)], { type: 'application/json' });
    const url = URL.createObjectURL(blob);
    const a = document.createElement('a');
    a.href = url;
    a.download = `${diagramType}-diagram.excalidraw`;
    document.body.appendChild(a);
    a.click();
    document.body.removeChild(a);
    URL.revokeObjectURL(url);
}

// Update Excalidraw preview when diagram type changes
document.getElementById('excalidraw-diagram-select')?.addEventListener('change', renderExcalidrawPreview);

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

// ============================================
// Excalidraw Status Check
// ============================================

async function checkExcalidrawStatus() {
    const statusEl = document.getElementById('excalidraw-status');
    try {
        const resp = await fetch(`${API}/health/excalidraw`);
        const health = await resp.json();

        if (health.excalidraw_reachable) {
            statusEl.innerHTML = `<span class="ollama-connected">Excalidraw MCP canvas connected</span>`;
            statusEl.className = 'ollama-status connected';
        } else {
            statusEl.innerHTML = `<span class="ollama-disconnected">Excalidraw canvas not reachable at ${escapeHtml(health.excalidraw_url)}</span>`;
            statusEl.className = 'ollama-status disconnected';
        }
    } catch (err) {
        statusEl.innerHTML = '<span class="ollama-disconnected">Cannot check Excalidraw status</span>';
        statusEl.className = 'ollama-status disconnected';
    }
}

// --- Initial Load ---
loadSessions();
checkOllamaStatus();
checkExcalidrawStatus();
// Re-check status periodically
setInterval(checkOllamaStatus, 30000);
setInterval(checkExcalidrawStatus, 30000);
