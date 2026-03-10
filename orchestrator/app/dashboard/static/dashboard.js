(function() {
"use strict";

// ---- State ----
var state = {
    investigations: [],
    events: [],
    pipe: { alert: 0, triage: 0, dispatch: 0, investigating: 0, resolved: 0 },
    sseConnected: false,
    sessionPollers: {},   // session_id -> interval
    evalData: null,
    activeTab: "pipeline"
};
var API = "/api/dashboard";
var ICONS = {
    alert_received: "\ud83d\udea8",
    dedup_hit: "\ud83d\udd01",
    triage_complete: "\ud83d\udd0e",
    dispatched: "\ud83d\ude80",
    session_update: "\ud83e\udde0",
    session_complete: "\u2705",
    pr_opened: "\ud83c\udf89",
    escalated: "\u26a0\ufe0f"
};
var TOAST_ICONS = {
    alert_received: "\ud83d\udea8",
    triage_complete: "\ud83d\udd0e",
    dispatched: "\ud83d\ude80",
    pr_opened: "\ud83c\udf89",
    escalated: "\u26a0\ufe0f",
    session_complete: "\u2705"
};

// ---- Tab switching ----
window.switchTab = function(tab) {
    state.activeTab = tab;
    document.querySelectorAll(".nav-tab").forEach(function(t) {
        t.classList.toggle("active", t.dataset.tab === tab);
    });
    document.getElementById("tab-pipeline").style.display = tab === "pipeline" ? "block" : "none";
    document.getElementById("tab-eval").style.display = tab === "eval" ? "block" : "none";
    document.getElementById("tab-eval").classList.toggle("visible", tab === "eval");
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
                    var labels = { typeerror: "\ud83d\udc1b TypeError", oomkilled: "\ud83d\udca5 OOMKilled", latency: "\u23f1\ufe0f Latency Spike" };
                    btn.innerHTML = labels[scenario] || scenario;
                }, 2000);
            }
        })
        .catch(function() {
            if (btn) { btn.disabled = false; btn.textContent = "Error"; }
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
        grid.innerHTML = '<div class="empty-state"><div class="empty-icon">&#x1F4E1;</div><div class="empty-msg">No investigations yet</div><div class="empty-hint">Click a demo button above to start the pipeline</div></div>';
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

        // Mini pipeline
        var dotsHtml = "";
        for (var d = 0; d < pipeDots.length; d++) {
            dotsHtml += '<div class="mini-dot ' + pipeDots[d] + '"></div>';
        }

        // Triage info
        var triageHtml = "";
        if (inv.triage_classification) {
            triageHtml = '<div class="inv-triage">Classification: <span class="conf">' +
                esc(inv.triage_classification) + '</span>' +
                (inv.triage_confidence ? ' \u2014 ' + (inv.triage_confidence * 100).toFixed(0) + '% confidence' : '') +
                '</div>';
        }

        // Resolution timeline (Feature #5)
        var timelineHtml = '<div class="res-timeline" id="steps-' + inv.investigation_id + '">';
        timelineHtml += buildTimeline(inv);
        timelineHtml += '</div>';

        // Actions
        var actHtml = "";
        if (inv.session_url) actHtml += '<a href="' + esc(inv.session_url) + '" target="_blank">View Session</a>';
        if (inv.pr_url) actHtml += '<a href="' + esc(inv.pr_url) + '" target="_blank">View PR</a>';

        html += '<div class="inv-card ' + cardCls + '">' +
            '<div class="inv-card-top"><span class="inv-id">' + esc(inv.investigation_id) + '</span>' +
            '<span class="badge ' + badgeCls + '"><span class="bdot"></span>' + label + '</span></div>' +
            '<div class="inv-service">' + esc(inv.service_name || "Unknown") + '</div>' +
            '<div class="inv-error">' + esc((inv.triage_classification || "") + ": ") + getErrorSummary(inv) + '</div>' +
            '<div class="mini-pipe">' + dotsHtml + '</div>' +
            triageHtml +
            timelineHtml +
            '<div class="inv-meta">' +
            (elapsed ? '<span class="inv-timer">&#x23F1; ' + elapsed + '</span>' : '') +
            (inv.acus_consumed ? '<span>&#x26A1; ' + inv.acus_consumed.toFixed(1) + ' ACU</span>' : '') +
            '</div>' +
            '<div class="inv-actions">' + actHtml + '</div>' +
            '</div>';
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
        list.innerHTML = '<div class="empty-state" id="feed-empty" style="padding:32px;"><div class="empty-icon">&#x23F3;</div><div class="empty-msg">Waiting for events...</div></div>';
        return;
    }
    for (var i = 0; i < state.events.length; i++) renderFeedItem(state.events[i], false);
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
    setTimeout(connectSSE, 500);
    setInterval(fetchInvestigations, 10000);
    setInterval(updateTimers, 1000);
    // Hide eval tab by default
    document.getElementById("tab-eval").style.display = "none";
}

init();
})();
