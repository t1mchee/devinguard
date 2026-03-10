(function() {
"use strict";

// ---- State ----
var state = {
    investigations: [],
    escalations: [],
    events: [],
    pipe: { alert: 0, triage: 0, dispatch: 0, investigating: 0, resolved: 0 },
    sseConnected: false,
    guideMode: false,
    guideHistory: [],
    sessionPollers: {},   // session_id -> interval
    evalData: null,
    activeTab: "pipeline"
};
var API = "/api/dashboard";
var ICONS = {
    alert_received: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    dedup_hit: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M21 12a9 9 0 0 0-9-9 9.75 9.75 0 0 0-6.74 2.74L3 8"/><path d="M3 3v5h5"/><path d="M3 12a9 9 0 0 0 9 9 9.75 9.75 0 0 0 6.74-2.74L21 16"/><path d="M16 16h5v5"/></svg>',
    triage_complete: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
    dispatched: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>',
    session_update: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>',
    session_complete: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>',
    pr_opened: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M4 3h.01"/><path d="M22 8h.01"/><path d="M15 2h.01"/><path d="M22 20h.01"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6-1.76 1.44L14 10"/><path d="m22 13-.82-.33c-.86-.34-1.82.2-1.98 1.11c-.11.7-.72 1.22-1.43 1.22H17"/><path d="m11 2 .33.82c.34.86-.2 1.82-1.11 1.98C9.52 4.9 9 5.52 9 6.23V7"/></svg>',
    escalated: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>'
};
var TOAST_ICONS = {
    alert_received: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
    triage_complete: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
    dispatched: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>',
    pr_opened: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5.8 11.3 2 22l10.7-3.79"/><path d="M4 3h.01"/><path d="M22 8h.01"/><path d="M15 2h.01"/><path d="M22 20h.01"/><path d="m22 2-2.24.75a2.9 2.9 0 0 0-1.96 3.12c.1.86-.57 1.63-1.45 1.63h-.38c-.86 0-1.6.6-1.76 1.44L14 10"/><path d="m22 13-.82-.33c-.86-.34-1.82.2-1.98 1.11c-.11.7-.72 1.22-1.43 1.22H17"/><path d="m11 2 .33.82c.34.86-.2 1.82-1.11 1.98C9.52 4.9 9 5.52 9 6.23V7"/></svg>',
    escalated: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
    session_complete: '<svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>'
};

// ---- Tab switching ----
window.switchTab = function(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".nav-tab").forEach(function(t) {
        t.classList.toggle("active", t.dataset.tab === tab);
    });
    document.getElementById("tab-pipeline").style.display = tab === "pipeline" ? "block" : "none";
    document.getElementById("tab-escalations").style.display = tab === "escalations" ? "block" : "none";
    document.getElementById("tab-escalations").classList.toggle("visible", tab === "escalations");
    document.getElementById("tab-eval").style.display = tab === "eval" ? "block" : "none";
    document.getElementById("tab-eval").classList.toggle("visible", tab === "eval");
    if (tab === "escalations") fetchEscalations();
    if (tab === "eval" && !state.evalData) loadEvalData();
};

// ---- SSE Connection ----
function connectSSE() {
    var es = new EventSource(API + "/events/stream");
    es.onopen = function() {
        state.sseConnected = true;
        document.getElementById("conn-dot").classList.remove("disconnected");
        document.getElementById("conn-text").textContent = "Live";
    };
    es.onmessage = function(msg) {
        try {
            var evt = JSON.parse(msg.data);
            state.events.unshift(evt);
            if (state.events.length > 200) state.events.length = 200;
            renderFeedItem(evt, true);
            updatePipeCounts(evt);
            showToast(evt);
            var triggers = ["dispatched","session_complete","pr_opened","triage_complete","escalated","alert_received"];
            if (triggers.indexOf(evt.event_type) !== -1) fetchInvestigations();
            // Trigger annotations for pipeline events
            if (evt.event_type === "alert_received") queueAnnotation("alert_created");
            if (evt.event_type === "triage_complete") {
                var cls = (evt.metadata && evt.metadata.classification) || (evt.detail && evt.detail.indexOf("CODE_LEVEL") !== -1 ? "CODE_LEVEL" : "");
                if (cls === "CODE_LEVEL") queueAnnotation("triage_code");
                else queueAnnotation("triage_infra");
            }
            if (evt.event_type === "dispatched") queueAnnotation("dispatched");
            if (evt.event_type === "pr_opened") queueAnnotation("pr_opened");
            if (evt.event_type === "escalated") queueAnnotation("escalation_action");
            // Show investigating annotation when session poller starts producing data
            if (evt.event_type === "session_update") queueAnnotation("investigating");
            // Start session poller for dispatched events
            if (evt.event_type === "dispatched" && evt.metadata && evt.metadata.session_id) {
                startSessionPoller(evt.metadata.session_id, evt.investigation_id);
            }
            // Celebration for PR opened
            if (evt.event_type === "pr_opened") celebrate();
        } catch (e) {}
    };
    es.onerror = function() {
        state.sseConnected = false;
        document.getElementById("conn-dot").classList.add("disconnected");
        document.getElementById("conn-text").textContent = "Reconnecting\u2026";
        es.close();
        setTimeout(connectSSE, 3000);
    };
}

// ---- Data fetching ----
function fetchJSON(url) { return fetch(url).then(function(r) { return r.json(); }); }

function fetchInvestigations() {
    fetchJSON(API + "/live-investigations").then(function(invs) {
        state.investigations = invs;
        renderCards();
        updateStats();
    }).catch(function() {});
}

function fetchRecentEvents() {
    fetchJSON(API + "/events?limit=50").then(function(evts) {
        state.events = evts;
        renderAllFeed();
        rebuildPipeCounts();
    }).catch(function() {});
}

// ---- Demo triggers ----
window.fireDemoScenario = function(scenario) {
    var btn = document.getElementById("btn-" + scenario);
    if (btn) { btn.disabled = true; btn.textContent = "Firing\u2026"; }
    fetch(API + "/demo/trigger?scenario=" + scenario, { method: "POST" })
        .then(function(r) { return r.json(); })
        .then(function() {
            if (btn) {
                btn.textContent = "Sent!";
                setTimeout(function() {
                    btn.disabled = false;
                    var labels = { typeerror: '<span class="btn-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m8 2 1.88 1.88"/><path d="M14.12 3.88 16 2"/><path d="M9 7.13v-1a3.003 3.003 0 1 1 6 0v1"/><path d="M12 20c-3.3 0-6-2.7-6-6v-3a4 4 0 0 1 4-4h4a4 4 0 0 1 4 4v3c0 3.3-2.7 6-6 6"/><path d="M12 20v-9"/><path d="M6.53 9C4.6 8.8 3 7.1 3 5"/><path d="M6 13H2"/><path d="M3 21c0-2.1 1.7-3.9 3.8-4"/><path d="M20.97 5c0 2.1-1.6 3.8-3.5 4"/><path d="M22 13h-4"/><path d="M17.2 17c2.1.1 3.8 1.9 3.8 4"/></svg></span> TypeError', oomkilled: '<span class="btn-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect width="20" height="8" x="2" y="2" rx="2" ry="2"/><rect width="20" height="8" x="2" y="14" rx="2" ry="2"/><line x1="6" x2="6.01" y1="6" y2="6"/><line x1="6" x2="6.01" y1="18" y2="18"/></svg></span> OOMKilled', latency: '<span class="btn-icon"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg></span> Latency Spike' };
                    btn.innerHTML = labels[scenario] || scenario;
                }, 2000);
            }
        })
        .catch(function() {
            if (btn) { btn.disabled = false; btn.textContent = "Error"; }
        });
};

// ---- Scan Repository ----
var SCAN_BTN_HTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg> Scan &amp; Triage';
var SCAN_SPINNER_HTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" class="spin"><path d="M21 12a9 9 0 1 1-6.219-8.56"/></svg> Scanning\u2026';

window.scanRepository = function() {
    var input = document.getElementById("scan-repo-url");
    var branchInput = document.getElementById("scan-branch");
    var btn = document.getElementById("btn-scan");
    var statusEl = document.getElementById("scan-status");
    var repoUrl = input ? input.value.trim() : "";
    var branch = branchInput ? branchInput.value.trim() : "main";
    if (!repoUrl) { if (statusEl) statusEl.textContent = "Please enter a repository URL"; return; }

    if (btn) { btn.disabled = true; btn.innerHTML = SCAN_SPINNER_HTML; }
    if (statusEl) statusEl.innerHTML = '<span style="color:var(--accent-blue)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>Scanning source code, issues, and commits on <strong>' + esc(branch) + '</strong> branch\u2026</span>';
    queueAnnotation('scan_initiated');

    fetch(API + "/scan-repo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ repo_url: repoUrl, branch: branch, max_issues: 10, scan_code: true })
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) {
            if (statusEl) statusEl.innerHTML = '<span style="color:var(--accent-red)">' + esc(data.error) + '</span>';
        } else {
            var parts = [];
            if (data.code_findings_found) parts.push(data.code_findings_found + ' code bugs');
            if (data.issues_found) parts.push(data.issues_found + ' issues');
            if (data.error_commits_found) parts.push(data.error_commits_found + ' suspicious commits');
            var msg = 'Found ' + parts.join(', ') + '. Created <strong>' + data.alerts_created + ' alerts</strong> flowing through the pipeline.';
            if (statusEl) statusEl.innerHTML = '<span style="color:var(--accent-green)"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" style="vertical-align:-1px;margin-right:4px"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>' + msg + '</span>';
        }
        if (btn) { btn.disabled = false; btn.innerHTML = SCAN_BTN_HTML; }
    })
    .catch(function(err) {
        if (statusEl) statusEl.innerHTML = '<span style="color:var(--accent-red)">Scan failed: ' + esc(err.message) + '</span>';
        if (btn) { btn.disabled = false; btn.innerHTML = SCAN_BTN_HTML; }
    });
};

// ---- Session polling (Feature #2: Live Devin progress) ----
function startSessionPoller(sessionId, investigationId) {
    if (state.sessionPollers[sessionId]) return;
    var rawId = sessionId;
    if (rawId.indexOf("devin-") === 0) rawId = rawId.substring(6);
    var interval = setInterval(function() {
        fetchJSON(API + "/session-status/" + rawId).then(function(data) {
            if (data.error) return;
            // Update investigation card with session steps
            updateSessionProgress(investigationId, sessionId, data);
            // If finished, stop polling and maybe celebrate
            if (data.status_enum === "finished" || data.status_enum === "stopped") {
                clearInterval(interval);
                delete state.sessionPollers[sessionId];
                fetchInvestigations(); // refresh cards
                if (data.pull_requests && data.pull_requests.length > 0) {
                    celebrate();
                }
            }
        }).catch(function() {});
    }, 5000);
    state.sessionPollers[sessionId] = interval;
}

function updateSessionProgress(investigationId, sessionId, data) {
    var el = document.getElementById("steps-" + investigationId);
    if (!el || !data.steps) return;
    var html = "";
    for (var i = 0; i < data.steps.length; i++) {
        var step = data.steps[i];
        var dotCls = step.status === "done" ? "done" : (step.status === "active" ? "active" : "");
        var lblCls = step.status === "done" ? "done" : "";
        html += '<div class="res-step">' +
            '<div class="res-dot ' + dotCls + '"></div>' +
            '<span class="res-label ' + lblCls + '">' + esc(step.label) + '</span>' +
            '</div>';
    }
    el.innerHTML = html;
}

// ---- Toast notifications (Feature #4) ----
function showToast(evt) {
    var icon = TOAST_ICONS[evt.event_type];
    if (!icon) return; // only toast for important events
    var container = document.getElementById("toast-container");
    var toast = document.createElement("div");
    toast.className = "toast";
    toast.innerHTML = '<span class="toast-icon">' + icon + '</span>' +
        '<div class="toast-body"><div class="toast-title">' + esc(evt.title) + '</div>' +
        '<div class="toast-msg">' + esc(evt.detail || "") + '</div></div>' +
        '<div class="toast-bar"></div>';
    container.appendChild(toast);
    setTimeout(function() {
        toast.classList.add("toast-exit");
        setTimeout(function() { toast.remove(); }, 300);
    }, 4000);
}

// ---- Celebration animation (Feature #3) ----
function celebrate() {
    var container = document.createElement("div");
    container.className = "confetti-container";
    document.body.appendChild(container);
    var colors = ["#22c55e", "#3b82f6", "#f59e0b", "#a78bfa", "#ef4444", "#06b6d4"];
    for (var i = 0; i < 60; i++) {
        var piece = document.createElement("div");
        piece.className = "confetti-piece";
        piece.style.left = Math.random() * 100 + "%";
        piece.style.background = colors[Math.floor(Math.random() * colors.length)];
        piece.style.animationDelay = Math.random() * 0.8 + "s";
        piece.style.animationDuration = 1.5 + Math.random() * 1.5 + "s";
        piece.style.width = 4 + Math.random() * 6 + "px";
        piece.style.height = 4 + Math.random() * 6 + "px";
        container.appendChild(piece);
    }
    setTimeout(function() { container.remove(); }, 4000);
}

// ---- Pipeline counts ----
function updatePipeCounts(evt) {
    var c = state.pipe;
    switch (evt.event_type) {
        case "alert_received": c.alert++; break;
        case "triage_complete": c.triage++; break;
        case "dispatched": c.dispatch++; c.investigating++; break;
        case "session_complete": c.investigating = Math.max(0, c.investigating - 1); break;
        case "pr_opened": c.investigating = Math.max(0, c.investigating - 1); c.resolved++; break;
    }
    renderPipeline();
}

function rebuildPipeCounts() {
    var c = { alert: 0, triage: 0, dispatch: 0, investigating: 0, resolved: 0 };
    var sorted = state.events.slice().reverse();
    for (var i = 0; i < sorted.length; i++) {
        switch (sorted[i].event_type) {
            case "alert_received": c.alert++; break;
            case "triage_complete": c.triage++; break;
            case "dispatched": c.dispatch++; break;
            case "pr_opened": c.resolved++; break;
        }
    }
    var completed = sorted.filter(function(e) { return e.event_type === "session_complete"; }).length;
    c.investigating = Math.max(0, c.dispatch - c.resolved - completed);
    state.pipe = c;
    renderPipeline();
}

function renderPipeline() {
    var c = state.pipe;
    setText("p-alert-n", c.alert);
    setText("p-triage-n", c.triage);
    setText("p-dispatch-n", c.dispatch);
    setText("p-invest-n", c.investigating);
    setText("p-resolved-n", c.resolved);
    setStage("p-alert", c.alert > 0 ? (c.triage > 0 ? "complete" : "active") : "");
    setStage("p-triage", c.triage > 0 ? (c.dispatch > 0 ? "complete" : "active") : "");
    setStage("p-dispatch", c.dispatch > 0 ? (c.investigating > 0 || c.resolved > 0 ? "complete" : "active") : "");
    setStage("p-invest", c.investigating > 0 ? "active" : (c.resolved > 0 ? "complete" : ""));
    setStage("p-resolved", c.resolved > 0 ? "complete" : "");
    toggleLit("a1", c.triage > 0);
    toggleLit("a2", c.dispatch > 0);
    toggleLit("a3", c.investigating > 0 || c.resolved > 0);
    toggleLit("a4", c.resolved > 0);
}

function setStage(id, s) {
    var el = document.getElementById(id);
    if (!el) return;
    el.classList.remove("active", "complete");
    if (s) el.classList.add(s);
}
function toggleLit(id, on) {
    var el = document.getElementById(id);
    if (el) el.classList.toggle("lit", on);
}
function setText(id, v) {
    var el = document.getElementById(id);
    if (el) el.textContent = v;
}

// ---- Stats ----
function updateStats() {
    var invs = state.investigations;
    var total = invs.length;
    var active = invs.filter(function(i) { return !i.resolved_at && i.session_id; }).length;
    var prs = invs.filter(function(i) { return i.session_outcome === "fix_pr"; }).length;
    var acus = invs.reduce(function(s, i) { return s + (i.acus_consumed || 0); }, 0);
    setText("stat-alerts", state.pipe.alert || total);
    setText("stat-alerts-sub", total > 0 ? total + " investigation" + (total !== 1 ? "s" : "") + " created" : "Waiting for alerts");
    setText("stat-active", active);
    setText("stat-active-sub", active > 0 ? "Devin investigating " + active + " issue" + (active !== 1 ? "s" : "") : "None in progress");
    setText("stat-prs", prs);
    setText("stat-prs-sub", prs > 0 ? prs + " fix" + (prs !== 1 ? "es" : "") + " submitted" : "No fixes yet");
    setText("stat-acus", acus.toFixed(1));
    setText("stat-acus-sub", "$" + (acus * 0.54).toFixed(2) + " estimated");
}

// ---- Investigation cards ----
function renderCards() {
    var grid = document.getElementById("cards-grid");
    var invs = state.investigations;
    if (!invs.length) {
        grid.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M19.07 4.93A10 10 0 0 0 6.99 3.34"/><path d="M4 6h.01"/><path d="M2.29 9.62A10 10 0 1 0 21.31 8.35"/><path d="M16.24 7.76A6 6 0 1 0 8.23 16.67"/><path d="M12 18h.01"/><circle cx="12" cy="12" r="2"/><path d="m13.41 10.59 5.66-5.66"/></svg></div><div class="empty-msg">No investigations yet</div><div class="empty-hint">Click a demo button above to start the pipeline</div></div>';
        return;
    }
    var html = "";
    for (var i = 0; i < invs.length; i++) {
        var inv = invs[i];
        var status = getStatus(inv);
        var label = STATUS_LABELS[status] || status;
        var cardCls = CARD_CLASSES[status] || "";
        var badgeCls = BADGE_CLASSES[status] || "";
        var pipeDots = getPipeDots(inv);
        var elapsed = getElapsed(inv);

        // Mini pipeline dots
        var dotsHtml = "";
        for (var d = 0; d < pipeDots.length; d++) {
            dotsHtml += '<div class="mini-dot ' + pipeDots[d] + '"></div>';
        }

        // Compact classification line
        var classLine = "";
        if (inv.triage_classification) {
            classLine = '<span class="conf">' + esc(inv.triage_classification) + '</span>';
            if (inv.triage_confidence) classLine += ' <span class="conf-pct">' + (inv.triage_confidence * 100).toFixed(0) + '%</span>';
        }

        // Actions
        var actHtml = "";
        if (inv.session_url) actHtml += '<a href="' + esc(inv.session_url) + '" target="_blank">Session</a>';
        if (inv.pr_url) actHtml += '<a href="' + esc(inv.pr_url) + '" target="_blank">PR</a>';

        html += '<div class="inv-card ' + cardCls + '">' +
            '<div class="inv-card-top"><span class="inv-id">' + esc(inv.service_name || "Unknown") + '</span>' +
            '<span class="badge ' + badgeCls + '"><span class="bdot"></span>' + label + '</span></div>' +
            '<div class="inv-error">' + getErrorSummary(inv) + '</div>' +
            '<div class="inv-card-row">' +
            '<div class="mini-pipe">' + dotsHtml + '</div>' +
            (classLine ? '<div class="inv-class-inline">' + classLine + '</div>' : '') +
            '</div>' +
            '<div class="inv-card-footer">' +
            (elapsed ? '<span class="inv-timer"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ' + elapsed + '</span>' : '') +
            (inv.acus_consumed ? '<span class="inv-acu"><svg width="11" height="11" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M13 2 3 14h9l-1 8 10-12h-9l1-8z"/></svg> ' + inv.acus_consumed.toFixed(1) + '</span>' : '') +
            '<span class="inv-actions-inline">' + actHtml + '</span>' +
            '</div></div>';
    }
    grid.innerHTML = html;

    // Re-start session pollers for active investigations
    for (var j = 0; j < invs.length; j++) {
        if (invs[j].session_id && !invs[j].resolved_at) {
            startSessionPoller(invs[j].session_id, invs[j].investigation_id);
        }
    }
}

// ---- Resolution timeline builder (Feature #5) ----
function buildTimeline(inv) {
    var steps = [];
    steps.push({ label: "Alert received", status: "done", ts: fmtTime(inv.created_at) });
    if (inv.triage_classification) {
        steps.push({ label: "Triage: " + inv.triage_classification, status: "done" });
    }
    if (inv.session_id) {
        steps.push({ label: "Dispatched to Devin", status: "done" });
        if (inv.resolved_at) {
            if (inv.session_outcome === "fix_pr") {
                steps.push({ label: "Fix PR opened", status: "done", ts: fmtTime(inv.resolved_at) });
            } else {
                steps.push({ label: "Investigation complete", status: "done" });
            }
        } else {
            steps.push({ label: "Investigating\u2026", status: "active" });
        }
    } else if (inv.triage_classification && inv.triage_classification !== "CODE_LEVEL") {
        steps.push({ label: "Escalated to human", status: "done" });
    }
    var html = "";
    for (var i = 0; i < steps.length; i++) {
        var s = steps[i];
        var dotCls = s.status === "done" ? "done" : (s.status === "active" ? "active" : "");
        var lblCls = s.status === "done" ? "done" : "";
        html += '<div class="res-step">' +
            '<div class="res-dot ' + dotCls + '"></div>' +
            '<span class="res-label ' + lblCls + '">' + esc(s.label) + '</span>' +
            (s.ts ? '<span class="res-ts">' + s.ts + '</span>' : '') +
            '</div>';
    }
    return html;
}

function fmtTime(dt) {
    if (!dt) return "";
    try { return new Date(dt).toLocaleTimeString(); } catch (e) { return ""; }
}

var STATUS_LABELS = {
    triaging: "Triaging", investigating: "Investigating", dispatched: "Dispatched",
    fix_pr: "Fix PR Opened", hypothesis: "Hypothesis", inconclusive: "Inconclusive", escalated: "Escalated"
};
var CARD_CLASSES = { investigating: "card-active", dispatched: "card-active", fix_pr: "card-complete", escalated: "card-escalated" };
var BADGE_CLASSES = {
    triaging: "badge-triaging", investigating: "badge-investigating", dispatched: "badge-investigating",
    fix_pr: "badge-fix-pr", hypothesis: "badge-error", inconclusive: "badge-error", escalated: "badge-escalated"
};

function getStatus(inv) {
    if (inv.session_outcome === "fix_pr") return "fix_pr";
    if (inv.session_outcome === "hypothesis") return "hypothesis";
    if (inv.session_outcome === "inconclusive") return "inconclusive";
    if (inv.triage_classification && inv.triage_classification !== "CODE_LEVEL") return "escalated";
    if (inv.session_id && !inv.resolved_at) return "investigating";
    if (inv.session_id) return "dispatched";
    return "triaging";
}

function getPipeDots(inv) {
    var s = ["done"];
    s.push(inv.triage_classification ? "done" : "active");
    if (inv.session_id) {
        s.push("done");
        if (inv.resolved_at) { s.push("done"); s.push(inv.session_outcome === "fix_pr" ? "done" : "warn"); }
        else { s.push("active"); s.push(""); }
    } else if (inv.triage_classification && inv.triage_classification !== "CODE_LEVEL") {
        s.push("warn"); s.push(""); s.push("");
    } else { s.push(""); s.push(""); s.push(""); }
    return s;
}

function getErrorSummary(inv) {
    for (var i = 0; i < state.events.length; i++) {
        var e = state.events[i];
        if (e.event_type === "alert_received" && e.service_name === inv.service_name) {
            return esc(e.detail.substring(0, 80));
        }
    }
    return esc((inv.dedup_key || "").substring(0, 60) || "Processing\u2026");
}

function getElapsed(inv) {
    if (!inv.created_at) return "";
    var start = new Date(inv.created_at).getTime();
    var end = inv.resolved_at ? new Date(inv.resolved_at).getTime() : Date.now();
    var sec = Math.floor((end - start) / 1000);
    if (sec < 60) return sec + "s";
    return Math.floor(sec / 60) + "m " + (sec % 60) + "s";
}

// ---- Activity feed ----
function renderFeedItem(evt, prepend) {
    var list = document.getElementById("feed-list");
    var empty = document.getElementById("feed-empty");
    if (empty) empty.remove();
    var el = document.createElement("div");
    el.className = "feed-item";
    var ts = new Date(evt.timestamp * 1000);
    var icon = ICONS[evt.event_type] || "\u25cf";
    el.innerHTML = '<div class="feed-time">' + ts.toLocaleTimeString() + '</div>' +
        '<div class="feed-title"><span class="feed-icon">' + icon + '</span>' + esc(evt.title) + '</div>' +
        '<div class="feed-detail">' + esc(evt.detail || "") + '</div>';
    if (prepend) list.prepend(el); else list.appendChild(el);
    setText("feed-count", state.events.length + " events");
}

function renderAllFeed() {
    var list = document.getElementById("feed-list");
    list.innerHTML = "";
    if (!state.events.length) {
        list.innerHTML = '<div class="empty-state" id="feed-empty" style="padding:32px;"><div class="empty-icon"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M5 22h14"/><path d="M5 2h14"/><path d="M17 22v-4.172a2 2 0 0 0-.586-1.414L12 12l-4.414 4.414A2 2 0 0 0 7 17.828V22"/><path d="M7 2v4.172a2 2 0 0 0 .586 1.414L12 12l4.414-4.414A2 2 0 0 0 17 6.172V2"/></svg></div><div class="empty-msg">Waiting for events...</div></div>';
        return;
    }
    for (var i = 0; i < state.events.length; i++) renderFeedItem(state.events[i], false);
}

// ---- Escalations panel ----
function fetchEscalations() {
    fetchJSON(API + "/escalations").then(function(data) {
        if (Array.isArray(data)) {
            state.escalations = data;
            renderEscalations();
            updateEscalationCount();
        }
    }).catch(function() {});
}

function updateEscalationCount() {
    var pending = state.escalations.filter(function(e) {
        return e.escalation_status === "pending_review";
    }).length;
    var badge = document.getElementById("esc-tab-count");
    if (badge) badge.textContent = pending > 0 ? pending : "";
}

function renderEscalations() {
    var list = document.getElementById("esc-list");
    if (!list) return;
    var items = state.escalations;
    if (!items.length) {
        list.innerHTML = '<div class="empty-state"><div class="empty-icon"><svg width="32" height="32" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg></div><div class="empty-msg">No escalations yet</div><div class="empty-hint">Infrastructure and non-code alerts will appear here for human review</div></div>';
        return;
    }
    var html = "";
    for (var i = 0; i < items.length; i++) {
        var e = items[i];
        var statusCls = "esc-pending";
        var badgeCls = "esc-status-pending";
        var badgeLabel = "Pending Review";
        if (e.escalation_status === "acknowledged") { statusCls = "esc-acknowledged"; badgeCls = "esc-status-acknowledged"; badgeLabel = "Acknowledged"; }
        else if (e.escalation_status === "dismissed") { statusCls = "esc-dismissed"; badgeCls = "esc-status-dismissed"; badgeLabel = "Dismissed"; }
        else if (e.escalation_status === "reassigned") { statusCls = "esc-reassigned"; badgeCls = "esc-status-reassigned"; badgeLabel = "Reassigned to Devin"; }

        var elapsed = "";
        if (e.created_at) {
            var sec = Math.floor((Date.now() - new Date(e.created_at).getTime()) / 1000);
            elapsed = sec < 60 ? sec + "s ago" : Math.floor(sec / 60) + "m ago";
        }

        var actionsHtml = "";
        if (e.escalation_status === "pending_review") {
            actionsHtml = '<div class="esc-actions">' +
                '<button class="esc-action-btn esc-ack" onclick="escalationAction(\'' + esc(e.investigation_id) + '\', \'acknowledge\')">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg> Acknowledge</button>' +
                '<button class="esc-action-btn esc-reassign" onclick="escalationAction(\'' + esc(e.investigation_id) + '\', \'reassign_to_devin\')">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg> Reassign to Devin</button>' +
                '<button class="esc-action-btn esc-dismiss" onclick="escalationAction(\'' + esc(e.investigation_id) + '\', \'dismiss\')">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg> Dismiss</button>' +
                '</div>';
        } else if (e.escalation_status === "acknowledged") {
            actionsHtml = '<div class="esc-actions">' +
                '<button class="esc-action-btn esc-reassign" onclick="escalationAction(\'' + esc(e.investigation_id) + '\', \'reassign_to_devin\')">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg> Reassign to Devin</button>' +
                '<button class="esc-action-btn esc-dismiss" onclick="escalationAction(\'' + esc(e.investigation_id) + '\', \'dismiss\')">' +
                '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg> Dismiss</button>' +
                '</div>';
        }

        html += '<div class="esc-card ' + statusCls + '">' +
            '<div class="esc-card-header">' +
            '<span class="esc-service">' + esc(e.service_name || "Unknown") + '</span>' +
            '<span class="esc-status-badge ' + badgeCls + '">' + badgeLabel + '</span>' +
            '</div>' +
            '<div class="esc-classification"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg> ' + esc(e.triage_classification || "UNKNOWN") + '</div>' +
            (e.triage_reasoning ? '<div class="esc-reasoning"><div class="esc-reasoning-label">Triage Reasoning</div>' + esc(e.triage_reasoning) + '</div>' : '') +
            '<div class="esc-meta">' +
            '<span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="10"/><polyline points="12 6 12 12 16 14"/></svg> ' + elapsed + '</span>' +
            '<span><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg> ' + esc(e.investigation_id) + '</span>' +
            (e.triage_confidence ? '<span>Confidence: ' + (e.triage_confidence * 100).toFixed(0) + '%</span>' : '') +
            '</div>' +
            actionsHtml +
            '</div>';
    }
    list.innerHTML = html;
}

window.escalationAction = function(investigationId, action) {
    var btns = document.querySelectorAll(".esc-action-btn");
    for (var i = 0; i < btns.length; i++) btns[i].disabled = true;

    fetch(API + "/escalations/" + investigationId + "/action", {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify({action: action}),
    })
    .then(function(r) { return r.json(); })
    .then(function(data) {
        if (data.error) {
            showToast("escalated", "Error", data.error);
        } else {
            var labels = {
                acknowledge: "Acknowledged",
                reassign_to_devin: "Reassigned to Devin",
                dismiss: "Dismissed"
            };
            showToast(
                action === "reassign_to_devin" ? "dispatched" : "escalated",
                labels[action] || action,
                "Investigation " + investigationId
            );
            // Refresh data
            setTimeout(function() { fetchEscalations(); fetchInvestigations(); }, 500);
        }
    })
    .catch(function() {
        showToast("escalated", "Error", "Failed to perform action");
    })
    .finally(function() {
        for (var i = 0; i < btns.length; i++) btns[i].disabled = false;
    });
};

// ---- Annotation popup system ----
var ANNO_SVG_ARROW = '<svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14"/><path d="m12 5 7 7-7 7"/></svg>';

var ANNOTATIONS = {
    scan_initiated: {
        step: "Step 1",
        title: "Repository Analysis",
        iconColor: "blue",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg>',
        sections: [
            { label: "What's Happening", text: 'DevinGuard clones the target repository and performs <strong>static analysis</strong> across three data sources to discover real bugs.' },
            { label: "Three Analysis Sources", type: "infographic", content: "scan_sources" },
            { label: "Technology", text: '<span class="anno-highlight">Git clone (depth=1) &rarr; AST pattern matching + GitHub Issues API + Commit history scan</span>' }
        ]
    },
    alert_created: {
        step: "Step 2",
        title: "Alert Ingested",
        iconColor: "amber",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 8A6 6 0 0 0 6 8c0 7-3 9-3 9h18s-3-2-3-9"/><path d="M13.73 21a2 2 0 0 1-3.46 0"/></svg>',
        sections: [
            { label: "What's Happening", text: 'Each code finding is normalized into a <strong>standard alert payload</strong> (PagerDuty format). In production, these come from Sentry, PagerDuty, or Datadog webhooks.' },
            { label: "Deduplication", text: 'Composite key: <strong>(service, error_class, stack_fingerprint)</strong> with a 5-minute TTL window prevents duplicate alerts from flooding the system.' },
            { label: "Alert Flow", type: "infographic", content: "alert_flow" }
        ]
    },
    triage_code: {
        step: "Step 3a",
        title: "Triage: CODE_LEVEL",
        iconColor: "green",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m16 18 2 2 4-4"/><path d="M21 12a9 9 0 1 1-9-9c2.52 0 4.93 1 6.74 2.74L21 8"/><path d="M21 3v5h-5"/></svg>',
        sections: [
            { label: "Classification", text: 'This alert was classified as a <strong>code-level bug</strong> suitable for autonomous investigation by Devin.' },
            { label: "How Triage Works", type: "infographic", content: "triage_tree" },
            { label: "Decision", type: "decision", variant: "to-devin", icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>', text: "Dispatch to Devin for autonomous investigation" }
        ]
    },
    triage_infra: {
        step: "Step 3b",
        title: "Triage: INFRASTRUCTURE",
        iconColor: "amber",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m21.73 18-8-14a2 2 0 0 0-3.48 0l-8 14A2 2 0 0 0 4 21h16a2 2 0 0 0 1.73-3"/><path d="M12 9v4"/><path d="M12 17h.01"/></svg>',
        sections: [
            { label: "Classification", text: 'This alert was classified as an <strong>infrastructure issue</strong> \u2014 not a code bug. OOMKilled errors, scaling issues, and config problems require <strong>human ops judgment</strong>.' },
            { label: "Why Not Devin?", text: 'Infrastructure issues cannot be fixed by code changes alone. They require capacity planning, config updates, or platform-level interventions that need human context.' },
            { label: "Decision", type: "decision", variant: "to-human", icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/></svg>', text: "Escalated to human review (see Escalations tab)" }
        ]
    },
    dispatched: {
        step: "Step 4",
        title: "Devin Session Created",
        iconColor: "blue",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg>',
        sections: [
            { label: "What Devin Receives", type: "metrics", items: [
                { val: "Bug", label: "Error context" },
                { val: "File", label: "Affected code" },
                { val: "Repo", label: "Repository" }
            ]},
            { label: "What Happens Next", text: 'Devin <strong>clones the repo</strong>, reproduces the bug, identifies the root cause, writes a fix, runs tests, and <strong>opens a PR</strong> \u2014 all autonomously.' },
            { label: "Monitoring", text: 'DevinGuard polls every <strong>10 seconds</strong> for progress. Loop detection watches for command repetition, file re-reads, and stalls. Auto-redirect after 2 loops, terminate after 3.' }
        ]
    },
    investigating: {
        step: "Step 5",
        title: "Investigation in Progress",
        iconColor: "purple",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><rect x="4" y="4" width="16" height="16" rx="2"/><rect x="9" y="9" width="6" height="6"/><path d="M15 2v2"/><path d="M15 20v2"/><path d="M2 15h2"/><path d="M2 9h2"/><path d="M20 15h2"/><path d="M20 9h2"/><path d="M9 2v2"/><path d="M9 20v2"/></svg>',
        sections: [
            { label: "What's Happening", text: 'Devin is <strong>autonomously investigating</strong> the bug. It reads the codebase, identifies the root cause, and builds a fix.' },
            { label: "Loop Detection", type: "infographic", content: "loop_detection" },
            { label: "Safety Net", text: 'If Devin gets stuck (repeating commands, re-reading files, or stalling), DevinGuard <strong>redirects</strong> with new context. After 3 failed redirects, the session is <strong>terminated</strong> to prevent wasted ACUs.' }
        ]
    },
    pr_opened: {
        step: "Step 6",
        title: "Fix PR Opened",
        iconColor: "green",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>',
        sections: [
            { label: "Pipeline Complete", type: "infographic", content: "pipeline_timeline" },
            { label: "What Was Fixed", text: 'Devin identified the <strong>root cause</strong>, wrote a fix, ensured tests pass, and opened a pull request with a detailed description.' },
            { label: "Next Steps in Production", text: '<strong>Auto-merge gate</strong> checks 11 preconditions (tests pass, no secrets leaked, single-file change, etc.). Complex changes go to <strong>human review</strong>. Metrics are logged for continuous improvement.' },
            { label: "Decision", type: "decision", variant: "complete", icon: '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg>', text: "Alert \u2192 Triage \u2192 Devin \u2192 Fix PR \u2014 fully autonomous" }
        ]
    },
    escalation_action: {
        step: "Human Review",
        title: "Escalation Actions",
        iconColor: "amber",
        icon: '<svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M16 21v-2a4 4 0 0 0-4-4H6a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M22 21v-2a4 4 0 0 0-3-3.87"/><path d="M16 3.13a4 4 0 0 1 0 7.75"/></svg>',
        sections: [
            { label: "What's Happening", text: 'An engineer is reviewing an escalated alert. The system provides <strong>triage reasoning</strong> and <strong>confidence scores</strong> to help the human decide.' },
            { label: "Available Actions", type: "infographic", content: "escalation_options" },
            { label: "Human-in-the-Loop", text: 'This shows the <strong>human-in-the-loop design</strong>: Devin handles code bugs autonomously, while infrastructure and ambiguous cases are escalated for human judgment. Humans can always override.' }
        ]
    }
};

// Infographic renderers
function renderInfographic(id) {
    switch (id) {
        case "scan_sources":
            return '<div class="anno-infographic"><div class="anno-flow">' +
                '<div class="anno-flow-node active"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="11" cy="11" r="8"/><path d="m21 21-4.3-4.3"/></svg> Code Patterns</div>' +
                '<span class="anno-flow-arrow">' + ANNO_SVG_ARROW + '</span>' +
                '<div class="anno-flow-node highlight"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M15 22v-4a4.8 4.8 0 0 0-1-3.5c3 0 6-2 6-5.5.08-1.25-.27-2.48-1-3.5.28-1.15.28-2.35 0-3.5 0 0-1 0-3 1.5-2.64-.5-5.36-.5-8 0C6 2 5 2 5 2c-.28 1.15-.28 2.35 0 3.5A5.403 5.403 0 0 0 4 9c0 3.5 3 5.5 6 5.5-.39.49-.68 1.05-.85 1.65S8.93 17.38 9 18v4"/><path d="M9 18c-4.51 2-5-2-7-2"/></svg> GitHub Issues</div>' +
                '<span class="anno-flow-arrow">' + ANNO_SVG_ARROW + '</span>' +
                '<div class="anno-flow-node warn"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="3"/><path d="m16 16 4 4"/></svg> Commit History</div>' +
                '</div>' +
                '<div class="anno-metrics" style="margin-top:10px;">' +
                '<div class="anno-metric"><div class="anno-metric-val" style="color:var(--accent-green)">8</div><div class="anno-metric-label">Vuln Patterns</div></div>' +
                '<div class="anno-metric"><div class="anno-metric-val" style="color:var(--accent-blue)">30</div><div class="anno-metric-label">Files Scanned</div></div>' +
                '<div class="anno-metric"><div class="anno-metric-val" style="color:var(--accent-amber)">50</div><div class="anno-metric-label">Commits Checked</div></div>' +
                '</div></div>';
        case "alert_flow":
            return '<div class="anno-infographic"><div class="anno-flow">' +
                '<div class="anno-flow-node">Finding</div>' +
                '<span class="anno-flow-arrow">' + ANNO_SVG_ARROW + '</span>' +
                '<div class="anno-flow-node highlight">Normalize</div>' +
                '<span class="anno-flow-arrow">' + ANNO_SVG_ARROW + '</span>' +
                '<div class="anno-flow-node active">Dedup Check</div>' +
                '<span class="anno-flow-arrow">' + ANNO_SVG_ARROW + '</span>' +
                '<div class="anno-flow-node warn">Alert Event</div>' +
                '</div></div>';
        case "triage_tree":
            return '<div class="anno-infographic">' +
                '<div class="anno-flow" style="flex-direction:column;gap:6px;align-items:stretch;">' +
                '<div style="display:flex;align-items:center;gap:6px;justify-content:center;">' +
                '<div class="anno-flow-node">Alert</div>' +
                '<span class="anno-flow-arrow">' + ANNO_SVG_ARROW + '</span>' +
                '<div class="anno-flow-node highlight">Rule Engine</div>' +
                '</div>' +
                '<div style="display:flex;gap:8px;justify-content:center;margin-top:4px;">' +
                '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;">' +
                '<div style="font-size:9px;color:var(--text-muted);font-weight:600;">MATCH</div>' +
                '<div class="anno-flow-node active">Classification</div>' +
                '</div>' +
                '<div style="display:flex;flex-direction:column;align-items:center;gap:4px;">' +
                '<div style="font-size:9px;color:var(--text-muted);font-weight:600;">NO MATCH</div>' +
                '<div class="anno-flow-node warn">GPT-4o-mini</div>' +
                '</div>' +
                '</div>' +
                '<div style="display:flex;gap:6px;justify-content:center;margin-top:4px;">' +
                '<div class="anno-flow-node active" style="font-size:9px;">CODE_LEVEL</div>' +
                '<div class="anno-flow-node warn" style="font-size:9px;">INFRASTRUCTURE</div>' +
                '<div class="anno-flow-node" style="font-size:9px;">OTHER</div>' +
                '</div>' +
                '</div></div>';
        case "loop_detection":
            return '<div class="anno-infographic">' +
                '<div class="anno-metrics">' +
                '<div class="anno-metric"><div class="anno-metric-val" style="color:var(--accent-blue)">10s</div><div class="anno-metric-label">Poll Interval</div></div>' +
                '<div class="anno-metric"><div class="anno-metric-val" style="color:var(--accent-amber)">2</div><div class="anno-metric-label">Redirects</div></div>' +
                '<div class="anno-metric"><div class="anno-metric-val" style="color:var(--accent-red)">3</div><div class="anno-metric-label">Max Loops</div></div>' +
                '</div>' +
                '<div style="display:flex;gap:4px;margin-top:10px;justify-content:center;flex-wrap:wrap;">' +
                '<div class="anno-flow-node" style="font-size:9px;">Cmd Repetition</div>' +
                '<div class="anno-flow-node" style="font-size:9px;">File Re-reads</div>' +
                '<div class="anno-flow-node" style="font-size:9px;">Output Stalls</div>' +
                '</div>' +
                '</div>';
        case "pipeline_timeline":
            return '<div class="anno-infographic">' +
                '<div class="anno-timeline-bar">' +
                '<div class="anno-tbar-seg" style="width:5%;background:var(--accent-amber);">0s</div>' +
                '<div class="anno-tbar-seg" style="width:5%;background:var(--accent-blue);">2s</div>' +
                '<div class="anno-tbar-seg" style="width:5%;background:var(--accent-purple);">3s</div>' +
                '<div class="anno-tbar-seg" style="width:70%;background:var(--accent-blue);opacity:0.7;">Investigation</div>' +
                '<div class="anno-tbar-seg" style="width:15%;background:var(--accent-green);">PR</div>' +
                '</div>' +
                '<div style="display:flex;justify-content:space-between;font-size:9px;color:var(--text-muted);margin-top:4px;padding:0 2px;">' +
                '<span>Alert</span><span>Triage</span><span>Dispatch</span><span>Devin Investigating</span><span>Fix PR</span>' +
                '</div>' +
                '</div>';
        case "escalation_options":
            return '<div class="anno-infographic" style="padding:12px 14px;">' +
                '<div style="display:flex;flex-direction:column;gap:8px;">' +
                '<div style="display:flex;align-items:center;gap:10px;"><div class="anno-flow-node highlight" style="min-width:120px;justify-content:center;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="M22 11.08V12a10 10 0 1 1-5.93-9.14"/><path d="m9 11 3 3L22 4"/></svg> Acknowledge</div><span style="font-size:11px;color:var(--text-secondary);">I\'ve seen this, tracking separately</span></div>' +
                '<div style="display:flex;align-items:center;gap:10px;"><div class="anno-flow-node active" style="min-width:120px;justify-content:center;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><path d="m22 2-7 20-4-9-9-4z"/><path d="M22 2 11 13"/></svg> Reassign</div><span style="font-size:11px;color:var(--text-secondary);">Override triage \u2014 let Devin investigate</span></div>' +
                '<div style="display:flex;align-items:center;gap:10px;"><div class="anno-flow-node" style="min-width:120px;justify-content:center;"><svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"><circle cx="12" cy="12" r="10"/><path d="m15 9-6 6"/><path d="m9 9 6 6"/></svg> Dismiss</div><span style="font-size:11px;color:var(--text-secondary);">False positive or already handled</span></div>' +
                '</div></div>';
        default:
            return '';
    }
}

// Annotation state
var annoState = {
    active: null,
    autoTimer: null,
    seen: {},
    queue: []
};

function buildAnnoHTML(key) {
    var a = ANNOTATIONS[key];
    if (!a) return '';
    var html = '<div class="anno-header">' +
        '<div class="anno-icon ' + a.iconColor + '">' + a.icon + '</div>' +
        '<div class="anno-title-wrap"><div class="anno-step">' + a.step + '</div><div class="anno-title">' + a.title + '</div></div>' +
        '<button class="anno-close" onclick="dismissAnnotation()"><svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M18 6 6 18"/><path d="m6 6 12 12"/></svg></button>' +
        '</div><div class="anno-body">';
    for (var i = 0; i < a.sections.length; i++) {
        var s = a.sections[i];
        html += '<div class="anno-section">';
        if (s.type === "infographic") {
            html += '<div class="anno-label">' + s.label + '</div>' + renderInfographic(s.content);
        } else if (s.type === "decision") {
            html += '<div class="anno-decision ' + s.variant + '">' + s.icon + ' ' + s.text + '</div>';
        } else if (s.type === "metrics") {
            html += '<div class="anno-label">' + s.label + '</div><div class="anno-metrics">';
            for (var m = 0; m < s.items.length; m++) {
                html += '<div class="anno-metric"><div class="anno-metric-val">' + s.items[m].val + '</div><div class="anno-metric-label">' + s.items[m].label + '</div></div>';
            }
            html += '</div>';
        } else {
            html += '<div class="anno-label">' + s.label + '</div><div class="anno-text">' + s.text + '</div>';
        }
        html += '</div>';
    }
    html += '</div>';
    // Progress dots
    var allKeys = Object.keys(ANNOTATIONS);
    html += '<div class="anno-progress">';
    for (var j = 0; j < allKeys.length; j++) {
        var cls = allKeys[j] === key ? "active" : (annoState.seen[allKeys[j]] ? "seen" : "");
        html += '<div class="anno-dot ' + cls + '" onclick="showAnnotation(\'' + allKeys[j] + '\')" title="' + ANNOTATIONS[allKeys[j]].title + '"></div>';
    }
    html += '</div>';
    return html;
}

window.showAnnotation = function(key) {
    if (!state.guideMode) return; // Only show when guide mode is ON
    var panel = document.getElementById("guide-panel-content");
    if (!panel) return;
    annoState.active = key;
    annoState.seen[key] = true;
    // Add to history (prepend) — don't duplicate
    if (state.guideHistory.indexOf(key) === -1) {
        state.guideHistory.unshift(key);
    } else {
        // Move to front
        state.guideHistory.splice(state.guideHistory.indexOf(key), 1);
        state.guideHistory.unshift(key);
    }
    renderGuidePanel();
    // Scroll to top of panel to show latest
    panel.scrollTop = 0;
};

window.dismissAnnotation = function() {
    annoState.active = null;
    // Process queue
    if (annoState.queue.length > 0) {
        var next = annoState.queue.shift();
        setTimeout(function() { showAnnotation(next); }, 300);
    }
};

// Queue annotation if one is already showing
function queueAnnotation(key) {
    if (annoState.active) {
        if (annoState.active !== key && annoState.queue.indexOf(key) === -1) {
            annoState.queue.push(key);
        }
        return;
    }
    showAnnotation(key);
}

// Info icon click handler for pipeline stages
window.showPipeInfo = function(stageKey, evt) {
    if (evt) evt.stopPropagation();
    var map = {
        "alert": "alert_created",
        "triage": "triage_code",
        "dispatch": "dispatched",
        "invest": "investigating",
        "resolved": "pr_opened"
    };
    var annoKey = map[stageKey];
    if (annoKey) showAnnotation(annoKey);
};


// ---- Guide Mode ----
window.toggleGuideMode = function() {
    state.guideMode = !state.guideMode;
    var btn = document.getElementById("guide-toggle");
    var sidebar = document.querySelector(".sidebar");
    var guidePanel = document.getElementById("guide-sidebar");
    var activityFeed = document.getElementById("activity-feed");
    if (state.guideMode) {
        if (btn) { btn.classList.add("active"); btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg> Guide On'; }
        if (guidePanel) guidePanel.style.display = "flex";
        if (activityFeed) activityFeed.style.display = "none";
        renderGuidePanel();
    } else {
        if (btn) { btn.classList.remove("active"); btn.innerHTML = '<svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg> Guide'; }
        if (guidePanel) guidePanel.style.display = "none";
        if (activityFeed) activityFeed.style.display = "flex";
    }
};

function renderGuidePanel() {
    var panel = document.getElementById("guide-panel-content");
    if (!panel) return;
    if (state.guideHistory.length === 0) {
        panel.innerHTML = '<div class="guide-empty"><div class="empty-icon"><svg width="28" height="28" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.5" stroke-linecap="round" stroke-linejoin="round"><path d="M2 3h6a4 4 0 0 1 4 4v14a3 3 0 0 0-3-3H2z"/><path d="M22 3h-6a4 4 0 0 0-4 4v14a3 3 0 0 1 3-3h7z"/></svg></div><div class="empty-msg">Annotations will appear here as the pipeline runs</div><div class="empty-hint">Scan a repo or fire a demo to start</div></div>';
        return;
    }
    var html = '';
    for (var i = 0; i < state.guideHistory.length; i++) {
        var key = state.guideHistory[i];
        var a = ANNOTATIONS[key];
        if (!a) continue;
        var isLatest = (i === 0);
        html += '<div class="guide-card' + (isLatest ? ' guide-latest' : '') + '">';
        html += '<div class="guide-card-header">';
        html += '<div class="anno-icon ' + a.iconColor + '" style="width:28px;height:28px;border-radius:6px;">' + a.icon.replace(/width="20"/g, 'width="14"').replace(/height="20"/g, 'height="14"') + '</div>';
        html += '<div style="flex:1;min-width:0;"><div class="guide-step">' + a.step + '</div><div class="guide-title">' + a.title + '</div></div>';
        html += '</div>';
        // Show sections inline (compact)
        html += '<div class="guide-body">';
        for (var s = 0; s < a.sections.length; s++) {
            var sec = a.sections[s];
            if (sec.type === "decision") {
                html += '<div class="anno-decision ' + sec.variant + '" style="font-size:11px;padding:6px 10px;margin-top:6px;">' + sec.icon + ' ' + sec.text + '</div>';
            } else if (sec.type === "metrics") {
                html += '<div class="guide-label">' + sec.label + '</div>';
                html += '<div class="anno-metrics" style="grid-template-columns:repeat(' + sec.items.length + ',1fr);gap:4px;margin-top:4px;">';
                for (var m = 0; m < sec.items.length; m++) {
                    html += '<div class="anno-metric" style="padding:4px 3px;"><div class="anno-metric-val" style="font-size:12px;">' + sec.items[m].val + '</div><div class="anno-metric-label">' + sec.items[m].label + '</div></div>';
                }
                html += '</div>';
            } else if (sec.type === "infographic") {
                // Skip infographics in sidebar to keep compact
            } else {
                html += '<div class="guide-label">' + sec.label + '</div>';
                html += '<div class="guide-text">' + sec.text + '</div>';
            }
        }
        html += '</div></div>';
    }
    panel.innerHTML = html;
    // Update step counter
    var countEl = document.getElementById("guide-count");
    if (countEl) countEl.textContent = state.guideHistory.length + " step" + (state.guideHistory.length !== 1 ? "s" : "");
}

// ---- Eval scorecard (Feature #6) ----
function loadEvalData() {
    fetchJSON(API + "/eval-scorecard").then(function(data) {
        if (data.error) {
            document.getElementById("eval-top-cards").innerHTML = '<div class="empty-state"><div class="empty-msg">' + esc(data.error) + '</div></div>';
            return;
        }
        state.evalData = data;
        renderEval(data);
    }).catch(function() {});
}

function renderEval(data) {
    var s = data.summary || {};
    // Top cards
    var topHtml = '';
    topHtml += evalCard("Decision Accuracy", (s.decision_accuracy * 100).toFixed(1) + "%", "When classifier makes a call", "v-green");
    topHtml += evalCard("Coverage", (s.coverage * 100).toFixed(0) + "%", s.non_ambiguous_count + " of " + s.total_evaluated + " classified", "v-blue");
    topHtml += evalCard("Dispatch Precision", (s.dispatch_precision * 100).toFixed(0) + "%", s.total_dispatched_to_devin + " dispatched to Devin", "v-amber");
    document.getElementById("eval-top-cards").innerHTML = topHtml;

    // Per-class table
    var pc = data.per_class || {};
    var tbody = document.querySelector("#eval-class-table tbody");
    var rows = "";
    var classes = ["CODE_LEVEL", "INFRASTRUCTURE"];
    for (var i = 0; i < classes.length; i++) {
        var cls = classes[i];
        var d = pc[cls];
        if (!d) continue;
        rows += '<tr><td><span class="conf">' + cls + '</span></td>' +
            '<td>' + pctBar(d.precision) + '</td>' +
            '<td>' + pctBar(d.recall) + '</td>' +
            '<td>' + (d.f1 * 100).toFixed(0) + '%</td>' +
            '<td>' + d.true_positives + '</td>' +
            '<td>' + d.false_positives + '</td></tr>';
    }
    tbody.innerHTML = rows;

    // Repo table
    var rb = data.repo_breakdown || {};
    var rtbody = document.querySelector("#eval-repo-table tbody");
    var rrows = "";
    var repos = Object.keys(rb);
    for (var j = 0; j < repos.length; j++) {
        var repo = repos[j];
        var rd = rb[repo];
        var acc = rd.total > 0 ? rd.correct / rd.total : 0;
        rrows += '<tr><td>' + esc(repo) + '</td><td>' + rd.total + '</td><td>' + rd.correct + '</td>' +
            '<td>' + (acc * 100).toFixed(0) + '%</td><td>' + pctBar(acc) + '</td></tr>';
    }
    rtbody.innerHTML = rrows;
}

function evalCard(label, value, sub, cls) {
    return '<div class="eval-card"><div class="el">' + label + '</div><div class="ev ' + (cls || '') + '">' + value + '</div><div class="es">' + sub + '</div></div>';
}

function pctBar(val) {
    var pct = Math.round(val * 100);
    return '<div class="eval-bar"><span>' + pct + '%</span><div class="eval-bar-track"><div class="eval-bar-fill" style="width:' + pct + '%"></div></div></div>';
}

// ---- Utilities ----
function esc(str) {
    if (!str) return "";
    var d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
}

function updateTimers() {
    var hasActive = state.investigations.some(function(i) { return !i.resolved_at && i.session_id; });
    if (hasActive) renderCards();
}

// ---- Init ----
function init() {
    fetchInvestigations();
    fetchRecentEvents();
    fetchEscalations();
    setTimeout(connectSSE, 500);
    setInterval(fetchInvestigations, 10000);
    setInterval(fetchEscalations, 10000);
    setInterval(updateTimers, 1000);
    // Hide non-active tabs by default
    document.getElementById("tab-escalations").style.display = "none";
    document.getElementById("tab-eval").style.display = "none";
}

init();
})();
