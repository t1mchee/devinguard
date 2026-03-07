(function() {
"use strict";
var state = {
    investigations: [],
    events: [],
    pipelineCounts: { alert: 0, triage: 0, dispatch: 0, investigating: 0, resolved: 0 },
    sseConnected: false
};
var API = "/api/dashboard";
var FEED_ICONS = {
    alert_received: "\ud83d\udea8",
    dedup_hit: "\ud83d\udd01",
    triage_complete: "\ud83d\udd0d",
    dispatched: "\ud83d\ude80",
    session_update: "\ud83e\udde0",
    session_complete: "\u2705",
    pr_opened: "\ud83c\udf89",
    escalated: "\u26a0\ufe0f"
};

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
            updatePipelineCounts(evt);
            var rt = ["dispatched","session_complete","pr_opened","triage_complete","escalated","alert_received"];
            if (rt.indexOf(evt.event_type) !== -1) fetchInvestigations();
        } catch (e) {}
    };
    es.onerror = function() {
        state.sseConnected = false;
        document.getElementById("conn-dot").classList.add("disconnected");
        document.getElementById("conn-text").textContent = "Reconnecting...";
        es.close();
        setTimeout(connectSSE, 3000);
    };
}

function fetchJSON(url) {
    return fetch(url).then(function(r) { return r.json(); });
}

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
        renderAllFeedItems();
        rebuildPipelineCounts();
    }).catch(function() {});
}

function updatePipelineCounts(evt) {
    var c = state.pipelineCounts;
    switch (evt.event_type) {
        case "alert_received": c.alert++; break;
        case "triage_complete": c.triage++; break;
        case "dispatched": c.dispatch++; c.investigating++; break;
        case "session_complete": c.investigating = Math.max(0, c.investigating - 1); break;
        case "pr_opened": c.investigating = Math.max(0, c.investigating - 1); c.resolved++; break;
    }
    renderPipeline();
}

function rebuildPipelineCounts() {
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
    state.pipelineCounts = c;
    renderPipeline();
}

function renderPipeline() {
    var c = state.pipelineCounts;
    document.getElementById("pipe-alert-count").textContent = c.alert;
    document.getElementById("pipe-triage-count").textContent = c.triage;
    document.getElementById("pipe-dispatch-count").textContent = c.dispatch;
    document.getElementById("pipe-investigating-count").textContent = c.investigating;
    document.getElementById("pipe-resolved-count").textContent = c.resolved;
    setStageState("pipe-alert", c.alert > 0 ? (c.triage > 0 ? "complete" : "active") : "");
    setStageState("pipe-triage", c.triage > 0 ? (c.dispatch > 0 || c.triage > c.dispatch ? "complete" : "active") : "");
    setStageState("pipe-dispatch", c.dispatch > 0 ? (c.investigating > 0 || c.resolved > 0 ? "complete" : "active") : "");
    setStageState("pipe-investigating", c.investigating > 0 ? "active" : (c.resolved > 0 ? "complete" : ""));
    setStageState("pipe-resolved", c.resolved > 0 ? "complete" : "");
    document.getElementById("arrow-1").classList.toggle("lit", c.triage > 0);
    document.getElementById("arrow-2").classList.toggle("lit", c.dispatch > 0);
    document.getElementById("arrow-3").classList.toggle("lit", c.investigating > 0 || c.resolved > 0);
    document.getElementById("arrow-4").classList.toggle("lit", c.resolved > 0);
}

function setStageState(id, s) {
    var el = document.getElementById(id);
    el.classList.remove("active", "complete");
    if (s) el.classList.add(s);
}

function updateStats() {
    var invs = state.investigations;
    var total = invs.length;
    var active = invs.filter(function(inv) { return !inv.resolved_at && inv.session_id; }).length;
    var prs = invs.filter(function(inv) { return inv.session_outcome === "fix_pr"; }).length;
    var acus = invs.reduce(function(sum, inv) { return sum + (inv.acus_consumed || 0); }, 0);
    document.getElementById("stat-alerts").textContent = state.pipelineCounts.alert || total;
    document.getElementById("stat-alerts-sub").textContent = total > 0 ? total + " investigation" + (total !== 1 ? "s" : "") + " created" : "Waiting for alerts";
    document.getElementById("stat-active").textContent = active;
    document.getElementById("stat-active-sub").textContent = active > 0 ? "Devin investigating " + active + " issue" + (active !== 1 ? "s" : "") : "None in progress";
    document.getElementById("stat-prs").textContent = prs;
    document.getElementById("stat-prs-sub").textContent = prs > 0 ? prs + " fix" + (prs !== 1 ? "es" : "") + " submitted" : "No fixes yet";
    document.getElementById("stat-acus").textContent = acus.toFixed(1);
    document.getElementById("stat-acus-sub").textContent = "$" + (acus * 0.54).toFixed(2) + " estimated";
}

function renderCards() {
    var grid = document.getElementById("cards-grid");
    var invs = state.investigations;
    if (invs.length === 0) {
        grid.innerHTML = '<div class="empty-state"><div class="icon">&#x1F4E1;</div><div class="msg">No investigations yet</div><div class="hint">Fire a webhook to start the pipeline</div></div>';
        return;
    }
    var html = "";
    for (var idx = 0; idx < invs.length; idx++) {
        var inv = invs[idx];
        var status = getInvStatus(inv);
        var statusLabel = getStatusLabel(status);
        var cardClass = getCardClass(status);
        var pipeStages = getPipelineStages(inv);
        var elapsed = getElapsed(inv);
        var pipeDotsHtml = "";
        for (var p = 0; p < pipeStages.length; p++) {
            pipeDotsHtml += '<div class="inv-pip-dot ' + pipeStages[p] + '"></div>';
        }
        var triageHtml = "";
        if (inv.triage_classification) {
            triageHtml = '<div class="inv-card-triage">Classification: <span class="conf">' +
                esc(inv.triage_classification) + '</span>' +
                (inv.triage_confidence ? ' &mdash; ' + (inv.triage_confidence * 100).toFixed(0) + '% confidence' : '') +
                '</div>';
        }
        var actionsHtml = "";
        if (inv.session_url) actionsHtml += '<a href="' + esc(inv.session_url) + '" target="_blank">View Devin Session</a>';
        if (inv.pr_url) actionsHtml += '<a href="' + esc(inv.pr_url) + '" target="_blank">View Fix PR</a>';
        html += '<div class="inv-card ' + cardClass + '">' +
            '<div class="inv-card-header"><span class="inv-id">' + esc(inv.investigation_id) + '</span>' +
            '<span class="status-badge ' + status + '"><span class="dot"></span>' + statusLabel + '</span></div>' +
            '<div class="inv-card-service">' + esc(inv.service_name || "Unknown") + '</div>' +
            '<div class="inv-card-error">' + esc(inv.triage_classification || "Pending") + ": " + getErrorSummary(inv) + '</div>' +
            '<div class="inv-pipeline">' + pipeDotsHtml + '</div>' +
            triageHtml +
            '<div class="inv-card-meta">' +
            (elapsed ? '<span class="inv-card-timer">&#x23F1; ' + elapsed + '</span>' : '') +
            (inv.acus_consumed ? '<span>&#x26A1; ' + inv.acus_consumed.toFixed(1) + ' ACU</span>' : '') +
            (inv.alert_count > 1 ? '<span>&#x1F514; ' + inv.alert_count + ' alerts</span>' : '') +
            '</div>' +
            '<div class="inv-card-actions">' + actionsHtml + '</div>' +
            '</div>';
    }
    grid.innerHTML = html;
}

function getInvStatus(inv) {
    if (inv.session_outcome === "fix_pr") return "fix_pr";
    if (inv.session_outcome === "hypothesis") return "hypothesis";
    if (inv.session_outcome === "inconclusive") return "inconclusive";
    if (inv.triage_classification && inv.triage_classification !== "CODE_LEVEL") return "escalated";
    if (inv.session_id && !inv.resolved_at) return "investigating";
    if (inv.session_id) return "dispatched";
    return "triaging";
}

function getStatusLabel(s) {
    var labels = {
        triaging: "Triaging", dispatched: "Dispatched", investigating: "Investigating",
        fix_pr: "Fix PR Opened", hypothesis: "Hypothesis", inconclusive: "Inconclusive", escalated: "Escalated"
    };
    return labels[s] || s;
}

function getCardClass(s) {
    if (s === "investigating" || s === "dispatched") return "active";
    if (s === "fix_pr") return "completed";
    if (s === "escalated") return "escalated";
    return "";
}

function getPipelineStages(inv) {
    var stages = ["done"];
    stages.push(inv.triage_classification ? "done" : "active");
    if (inv.session_id) {
        stages.push("done");
        if (inv.resolved_at) {
            stages.push("done");
            stages.push(inv.session_outcome === "fix_pr" ? "done" : "warn");
        } else {
            stages.push("active");
            stages.push("");
        }
    } else if (inv.triage_classification && inv.triage_classification !== "CODE_LEVEL") {
        stages.push("warn");
        stages.push("");
        stages.push("");
    } else {
        stages.push("");
        stages.push("");
        stages.push("");
    }
    return stages;
}

function getErrorSummary(inv) {
    for (var i = 0; i < state.events.length; i++) {
        var e = state.events[i];
        if (e.event_type === "alert_received" && e.service_name === inv.service_name) {
            return esc(e.detail.substring(0, 80));
        }
    }
    return esc((inv.dedup_key || "").substring(0, 60) || "Processing...");
}

function getElapsed(inv) {
    if (!inv.created_at) return "";
    var start = new Date(inv.created_at).getTime();
    var end = inv.resolved_at ? new Date(inv.resolved_at).getTime() : Date.now();
    var sec = Math.floor((end - start) / 1000);
    if (sec < 60) return sec + "s";
    return Math.floor(sec / 60) + "m " + (sec % 60) + "s";
}

function renderFeedItem(evt, prepend) {
    var feedList = document.getElementById("feed-list");
    var feedEmpty = document.getElementById("feed-empty");
    if (feedEmpty) feedEmpty.remove();
    var el = document.createElement("div");
    el.className = "feed-item";
    var ts = new Date(evt.timestamp * 1000);
    var icon = FEED_ICONS[evt.event_type] || "\u25cf";
    el.innerHTML = '<div class="feed-time">' + ts.toLocaleTimeString() + '</div>' +
        '<div class="feed-title"><span class="feed-icon">' + icon + '</span>' + esc(evt.title) + '</div>' +
        '<div class="feed-detail">' + esc(evt.detail || "") + '</div>';
    if (prepend) {
        feedList.prepend(el);
    } else {
        feedList.appendChild(el);
    }
    document.getElementById("feed-count").textContent = state.events.length + " events";
}

function renderAllFeedItems() {
    var feedList = document.getElementById("feed-list");
    feedList.innerHTML = "";
    if (state.events.length === 0) {
        feedList.innerHTML = '<div class="empty-state" id="feed-empty" style="padding:32px;"><div class="icon">&#x23F3;</div><div class="msg" style="font-size:13px;">Waiting for events...</div></div>';
        return;
    }
    for (var i = 0; i < state.events.length; i++) {
        renderFeedItem(state.events[i], false);
    }
    document.getElementById("feed-count").textContent = state.events.length + " events";
}

function esc(str) {
    var d = document.createElement("div");
    d.textContent = str;
    return d.innerHTML;
}

function updateTimers() {
    var hasActive = state.investigations.some(function(inv) { return !inv.resolved_at && inv.session_id; });
    if (hasActive) renderCards();
}

function init() {
    fetchInvestigations();
    fetchRecentEvents();
    setTimeout(connectSSE, 500);
    setInterval(fetchInvestigations, 10000);
    setInterval(updateTimers, 1000);
}

init();
})();
