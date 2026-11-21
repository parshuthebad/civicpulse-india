/* CivicPulse v4.0 — Government of India Portal Interactive Controller */
(() => {
  "use strict";

  const state = {
    activeTab: "fact",
    lastFact: null,
    lastVisual: null,
    lastAudio: null,
    lastFeed: null,
    lastLive: null,
    lastComplaintReceipt: null,
    visualFile: null,
    audioFile: null,
    liveStream: null,
    liveWs: null,
    liveTimer: null,
    cocoModel: null,
    detectRaf: null,
    detectedObjects: [],
  };

  function showToast(msg, type = "info") {
    const container = document.getElementById("toastContainer");
    const colors = {
      info: "bg-[#1D1D1F] text-white",
      success: "bg-emerald-600 text-white",
      error: "bg-rose-600 text-white",
    };
    const el = document.createElement("div");
    el.className = `pointer-events-auto px-4 py-2.5 rounded-2xl shadow-lg text-xs font-medium ${colors[type] || colors.info}`;
    el.textContent = msg;
    container.appendChild(el);
    setTimeout(() => el.remove(), 3500);
  }

  function formatDateTime(iso) {
    try {
      return new Date(iso).toLocaleString(undefined, {
        year: "numeric", month: "short", day: "numeric",
        hour: "2-digit", minute: "2-digit", second: "2-digit",
      });
    } catch {
      return iso;
    }
  }

  function escapeHtml(str) {
    return String(str ?? "")
      .replaceAll("&", "&amp;")
      .replaceAll("<", "&lt;")
      .replaceAll(">", "&gt;")
      .replaceAll('"', "&quot;");
  }

  function verdictBadgeClass(verdict) {
    const v = String(verdict || "").toLowerCase();
    if (v.includes("authentic") || v.includes("verified")) return "bg-emerald-50 text-emerald-700 border-emerald-200";
    if (v.includes("fabricated") || v.includes("manipulated") || v.includes("clone")) return "bg-rose-50 text-rose-700 border-rose-200";
    if (v.includes("mislead") || v.includes("review") || v.includes("warn")) return "bg-amber-50 text-amber-700 border-amber-200";
    return "bg-blue-50 text-blue-700 border-blue-200";
  }

  function renderGaugeSVG(score, label, isRisk = true) {
    const val = Math.max(0, Math.min(100, Number(score) || 0));
    const r = 46;
    const c = 2 * Math.PI * r;
    const offset = c - (val / 100) * c;
    const color = isRisk
      ? (val >= 60 ? "#E11D48" : val >= 35 ? "#D97706" : "#16A34A")
      : (val >= 75 ? "#16A34A" : val >= 50 ? "#0071E3" : "#D97706");
    return `
      <div class="relative w-32 h-32 mx-auto flex items-center justify-center">
        <svg class="w-32 h-32 -rotate-90" viewBox="0 0 120 120">
          <circle cx="60" cy="60" r="${r}" stroke="#E5E5EA" stroke-width="10" fill="none" />
          <circle cx="60" cy="60" r="${r}" stroke="${color}" stroke-width="10" stroke-linecap="round"
                  stroke-dasharray="${c}" stroke-dashoffset="${offset}" fill="none" />
        </svg>
        <div class="absolute text-center">
          <div class="text-2xl font-bold text-[#1D1D1F]">${val}%</div>
          <div class="text-[10px] uppercase tracking-wider text-[#6E6E73]">${escapeHtml(label)}</div>
        </div>
      </div>`;
  }

  function downloadJSON(data, prefix) {
    if (!data) return showToast("Run an audit first to download results.", "error");
    const blob = new Blob([JSON.stringify(data, null, 2)], { type: "application/json" });
    const a = document.createElement("a");
    a.href = URL.createObjectURL(blob);
    a.download = `CivicPulse_${prefix}_${new Date().toISOString().slice(0, 19).replaceAll(":", "-")}.json`;
    document.body.appendChild(a);
    a.click();
    a.remove();
    showToast("Downloaded official JSON dossier.", "success");
  }

  function downloadPrintableReport(title, data) {
    if (!data) return showToast("Run an audit first.", "error");
    const html = `<!DOCTYPE html><html><head><meta charset="utf-8"><title>${escapeHtml(title)}</title>
      <style>body{font-family:-apple-system,Segoe UI,sans-serif;max-width:820px;margin:32px auto;color:#1d1d1f;line-height:1.5}
      .hdr{border-bottom:3px solid #0B1F3A;padding-bottom:12px;margin-bottom:20px}
      pre{background:#f5f5f7;padding:16px;border-radius:12px;overflow:auto;font-size:12px}</style></head>
      <body><div class="hdr"><h2>Government of India • CivicPulse Official Forensic Dossier</h2>
      <p><b>Report:</b> ${escapeHtml(title)} | <b>Generated:</b> ${new Date().toLocaleString()} | <b>Helpline:</b> 1930</p></div>
      <pre>${escapeHtml(JSON.stringify(data, null, 2))}</pre>
      <script>window.print();</script></body></html>`;
    const blob = new Blob([html], { type: "text/html" });
    window.open(URL.createObjectURL(blob), "_blank");
  }

  // === Tab Navigation ===
  function showTab(tabName) {
    state.activeTab = tabName;
    document.querySelectorAll(".tab-panel").forEach((p) => p.classList.add("hidden"));
    const target = document.getElementById(`tab-${tabName}`);
    if (target) target.classList.remove("hidden");
    document.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.classList.toggle("active", btn.dataset.tab === tabName);
    });
    loadHistory(tabName);
  }

  // === Official Complaint Modal ===
  function openComplaintModal(suggestedCategory = "", evidenceSummary = "") {
    document.getElementById("complaintForm").classList.remove("hidden");
    document.getElementById("complaintSuccessBox").classList.add("hidden");
    if (suggestedCategory) {
      const sel = document.getElementById("cmpCategory");
      for (const opt of sel.options) {
        if (opt.value === suggestedCategory) sel.value = suggestedCategory;
      }
    }
    let autoEv = evidenceSummary;
    if (!autoEv) {
      if (state.activeTab === "visual" && state.lastVisual) {
        autoEv = `Visual: ${state.lastVisual.filename} | Verdict: ${state.lastVisual.visual_forensics.verdict} | SHA256: ${state.lastVisual.provenance.sha256_certificate.slice(0, 16)}`;
      } else if (state.activeTab === "audio" && state.lastAudio) {
        autoEv = `Audio: ${state.lastAudio.filename} | Verdict: ${state.lastAudio.audio_forensics.verdict} | SHA256: ${state.lastAudio.sha256_certificate.slice(0, 16)}`;
      } else if (state.activeTab === "fact" && state.lastFact) {
        autoEv = `Claim: "${state.lastFact.fact_check.claim.slice(0, 60)}" | Verdict: ${state.lastFact.fact_check.verdict}`;
      } else if (state.activeTab === "live" && state.lastLive) {
        autoEv = `Live Camera | Objects: ${state.detectedObjects.join(", ") || "None"} | Risk: ${state.lastLive.synthetic_risk_score}%`;
      } else {
        autoEv = `Submitted directly from section: ${state.activeTab}`;
      }
    }
    document.getElementById("cmpEvidence").value = autoEv;
    document.getElementById("complaintModal").classList.remove("hidden");
  }

  function closeComplaintModal() {
    document.getElementById("complaintModal").classList.add("hidden");
    // Ensure user stays on the exact same active section
    showTab(state.activeTab);
  }

  async function submitComplaintForm(e) {
    e.preventDefault();
    const btn = document.getElementById("btnSubmitComplaint");
    btn.disabled = true;
    btn.textContent = "Submitting...";
    try {
      const payload = {
        full_name: document.getElementById("cmpName").value.trim(),
        mobile: document.getElementById("cmpMobile").value.trim(),
        email: document.getElementById("cmpEmail").value.trim(),
        age: parseInt(document.getElementById("cmpAge").value, 10),
        place: document.getElementById("cmpPlace").value.trim(),
        category: document.getElementById("cmpCategory").value,
        description: document.getElementById("cmpDesc").value.trim(),
        source_section: state.activeTab,
        evidence_ref: document.getElementById("cmpEvidence").value,
      };
      const res = await fetch("/api/v1/complaints", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Complaint submission failed");
      state.lastComplaintReceipt = data.complaint;
      document.getElementById("cmpRefDisplay").textContent = data.complaint.reference_no;
      document.getElementById("complaintForm").classList.add("hidden");
      document.getElementById("complaintSuccessBox").classList.remove("hidden");
      document.getElementById("complaintForm").reset();
      showToast(`Complaint ${data.complaint.reference_no} registered!`, "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Submit Complaint & Return";
    }
  }

  async function openComplaintsList() {
    const modal = document.getElementById("complaintsListModal");
    const body = document.getElementById("complaintsListBody");
    modal.classList.remove("hidden");
    body.innerHTML = `<p class="text-xs text-[#6E6E73]">Loading complaints...</p>`;
    try {
      const res = await fetch("/api/v1/complaints");
      const data = await res.json();
      const list = data.complaints || [];
      if (!list.length) {
        body.innerHTML = `<div class="p-4 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs text-[#6E6E73]">No complaints filed yet.</div>`;
        return;
      }
      body.innerHTML = list.map((c) => `
        <div class="p-4 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] space-y-1.5">
          <div class="flex flex-wrap items-center justify-between gap-2">
            <span class="font-mono font-bold text-xs text-[#0071E3]">${escapeHtml(c.reference_no)}</span>
            <span class="text-[11px] text-[#6E6E73]">${formatDateTime(c.created_at)}</span>
          </div>
          <div class="text-xs font-semibold text-[#1D1D1F]">${escapeHtml(c.category)} — ${escapeHtml(c.full_name)} (Age ${c.age}, ${escapeHtml(c.place)})</div>
          <div class="text-xs text-[#6E6E73]">Mobile: ${escapeHtml(c.mobile)} • Email: ${escapeHtml(c.email)}</div>
          <p class="text-xs text-[#1D1D1F]">${escapeHtml(c.description)}</p>
          <div class="flex justify-between items-center pt-1">
            <span class="text-[11px] font-mono text-[#6E6E73] truncate max-w-md">${escapeHtml(c.evidence_ref)}</span>
            <button type="button" data-del-cmp="${c.id}" class="del-cmp-btn text-xs text-rose-600 hover:underline font-medium">Delete</button>
          </div>
        </div>
      `).join("");
    } catch (err) {
      body.innerHTML = `<p class="text-xs text-rose-600">${escapeHtml(err.message)}</p>`;
    }
  }

  // === History CRUD ===
  async function loadHistory(section) {
    const container = document.getElementById(`history-${section}`);
    if (!container) return;
    try {
      const res = await fetch(`/api/v1/history/${section}`);
      const data = await res.json();
      const items = data.items || [];
      if (!items.length) {
        container.innerHTML = `<div class="p-4 rounded-xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs text-[#6E6E73]">No saved history in this section yet. Run an audit above and it will appear here automatically.</div>`;
        return;
      }
      container.innerHTML = items.map((item) => `
        <div class="flex flex-wrap items-center justify-between gap-3 p-3.5 rounded-2xl bg-[#FAFAFC] hover:bg-[#F2F2F7] border border-[#E5E5EA] transition">
          <div class="min-w-0 flex-1">
            <div class="flex flex-wrap items-center gap-2">
              <span class="px-2.5 py-0.5 rounded-full text-[11px] font-semibold border ${verdictBadgeClass(item.verdict)}">${escapeHtml(item.verdict)}</span>
              <span class="text-xs font-semibold text-[#1D1D1F]">${item.score}%</span>
              <span class="text-[11px] text-[#6E6E73]">${formatDateTime(item.created_at)}</span>
            </div>
            <p class="text-sm text-[#1D1D1F] truncate mt-1 font-medium">${escapeHtml(item.input_label)}</p>
          </div>
          <div class="flex items-center gap-2 shrink-0">
            <button type="button" data-action="view" data-id="${item.id}" data-section="${section}" class="hist-btn px-3 py-1.5 rounded-full bg-white border border-[#D2D2D7] hover:border-[#0071E3] text-xs font-medium">View</button>
            <a href="/api/v1/history/item/${item.id}/download" class="px-3 py-1.5 rounded-full bg-white border border-[#D2D2D7] hover:border-[#0071E3] text-xs font-medium text-[#0071E3]">Download</a>
            <button type="button" data-action="delete" data-id="${item.id}" data-section="${section}" class="hist-btn px-3 py-1.5 rounded-full bg-white border border-rose-200 hover:bg-rose-50 text-xs font-medium text-rose-600">Delete</button>
          </div>
        </div>
      `).join("");
    } catch (err) {
      container.innerHTML = `<p class="text-xs text-rose-600">Failed to load history: ${escapeHtml(err.message)}</p>`;
    }
  }

  async function loadStatus() {
    try {
      const res = await fetch("/api/v1/status");
      const data = await res.json();
      const _mb = document.getElementById("modeBadge"); if (_mb) _mb.textContent = data.engine_mode;
      const _ab = document.getElementById("apiBar"); if (_ab) _ab.innerHTML = Object.entries(data.connected_apis).map(([k, v]) => `
        <span class="px-2.5 py-1 rounded-full border font-medium ${v ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-[#F5F5F7] border-[#E5E5EA] text-[#86868B]"}">
          ${v ? "●" : "○"} ${escapeHtml(k.replaceAll("_", " "))}
        </span>`).join("");
    } catch {}
  }

  // === SECTION 1: FACT-CHECK ===
  function renderFactResult(data) {
    state.lastFact = data;
    document.getElementById("btnCopyFact").classList.remove("hidden");
    document.getElementById("btnDownloadFact").classList.remove("hidden");
    document.getElementById("btnPrintFact").classList.remove("hidden");

    const f = data.fact_check;
    const o = f.origin_trace;
    const el = document.getElementById("factResult");
    el.classList.remove("hidden");

    const complaintBanner = f.suggest_complaint ? `
      <div class="p-4 rounded-2xl bg-rose-50 border border-rose-200 flex flex-wrap items-center justify-between gap-3">
        <div class="text-xs text-rose-800"><b>Public Safety Advisory:</b> This claim shows signs of misinformation or fraud. Want to report it to the Cyber Cell?</div>
        <button type="button" class="open-cmp-inline px-4 py-1.5 rounded-full bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold" data-cat="Viral Misinformation / Election Disinformation">File Official Complaint</button>
      </div>` : "";

    const entitiesHtml = (f.key_entities || []).length
      ? `<div class="flex flex-wrap gap-1.5">${f.key_entities.map((e) => `<span class="px-2.5 py-0.5 rounded-full bg-blue-50 text-[#0071E3] text-[11px] font-medium">#${escapeHtml(e)}</span>`).join("")}</div>`
      : "";

    const diagPills = Object.entries(f.provider_diagnostics || {}).map(([k, v]) => `
      <span class="px-2.5 py-1 rounded-full text-[11px] border ${v === "live_ok" ? "bg-emerald-50 border-emerald-200 text-emerald-700" : "bg-[#F5F5F7] border-[#E5E5EA] text-[#6E6E73]"}">
        ${escapeHtml(k)}: <b>${escapeHtml(v)}</b>
      </span>`).join("");

    const sourcesHtml = (f.sources || []).length
      ? f.sources.map((s) => `
          <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] space-y-1">
            <div class="flex items-center justify-between gap-2">
              <span class="text-[11px] font-semibold text-[#0071E3] uppercase">${escapeHtml(s.source_api)}</span>
              ${s.url ? `<a href="${escapeHtml(s.url)}" target="_blank" class="text-xs text-[#0071E3] hover:underline font-medium">Open Source ↗</a>` : ""}
            </div>
            <div class="text-sm font-semibold text-[#1D1D1F]">${escapeHtml(s.title)}</div>
            <p class="text-xs text-[#6E6E73]">${escapeHtml(s.snippet)}</p>
          </div>`).join("")
      : `<p class="text-xs text-[#6E6E73]">No external citations matched this exact phrase.</p>`;

    const cascadeCard = o ? `
      <div class="apple-card p-6 lg:col-span-5 space-y-4">
        <h3 class="text-base font-semibold">Origin &amp; Timeline Signals</h3>
        <div class="grid grid-cols-2 gap-3">
          <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA]">
            <div class="text-[11px] text-[#6E6E73]">Virality Velocity</div>
            <div class="text-sm font-semibold mt-0.5">${escapeHtml(o.virality_velocity)}</div>
          </div>
          <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA]">
            <div class="text-[11px] text-[#6E6E73]">Bot Amplification Prob.</div>
            <div class="text-sm font-semibold mt-0.5">${o.bot_amplification_probability}%</div>
          </div>
        </div>
        <div class="space-y-3 pt-2">
          ${(o.propagation_timeline || []).map((t) => `
            <div class="flex gap-3 items-start">
              <span class="px-2 py-1 rounded-lg bg-blue-50 text-[#0071E3] font-mono text-[11px] font-semibold shrink-0">${escapeHtml(t.step)}</span>
              <div class="p-3 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] flex-1">
                <div class="text-xs font-semibold text-[#1D1D1F]">${escapeHtml(t.platform)}</div>
                <div class="text-xs text-[#6E6E73] mt-0.5">${escapeHtml(t.event)}</div>
              </div>
            </div>`).join("")}
        </div>
      </div>` : "";

    el.innerHTML = `
      <div class="apple-card p-6 ${o ? "lg:col-span-7" : "lg:col-span-12"} space-y-4">
        ${complaintBanner}
        <div class="flex flex-wrap items-center justify-between gap-4">
          <div>
            <span class="text-xs font-semibold uppercase tracking-wider text-[#6E6E73]">${escapeHtml(f.engine_mode)} • ${escapeHtml(f.category || "General")}</span>
            <div class="mt-1.5 flex items-center gap-2.5">
              <span class="px-3.5 py-1 rounded-full text-sm font-semibold border ${verdictBadgeClass(f.verdict)}">${escapeHtml(f.verdict)}</span>
              <span class="text-xs text-[#6E6E73]">${f.sources_checked || 0} live sources checked</span>
            </div>
          </div>
          ${renderGaugeSVG(f.confidence, "Confidence", false)}
        </div>
        ${entitiesHtml}
        <div class="p-4 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA]">
          <div class="text-xs font-semibold text-[#6E6E73] uppercase mb-1">Forensic Reasoning</div>
          <p class="text-sm text-[#1D1D1F] leading-relaxed">${escapeHtml(f.reasoning)}</p>
        </div>
        <div class="flex flex-wrap gap-1.5">${diagPills}</div>
        <div class="space-y-2.5 max-h-80 overflow-y-auto pr-1">${sourcesHtml}</div>
      </div>

${cascadeCard}`;
  }

  async function runFactCheck() {
    const claim = document.getElementById("claimInput").value.trim();
    const category = document.getElementById("claimCategory").value;
    if (!claim) return showToast("Please enter a claim to verify.", "error");
    const btn = document.getElementById("btnRunFactCheck");
    btn.disabled = true;
    btn.textContent = "Verifying across live APIs...";
    try {
      const res = await fetch("/api/v1/audit/claim", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ claim, category }),
      });
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Fact-check failed");
      renderFactResult(data);
      loadHistory("fact");
      showToast("Live fact-check complete & saved.", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Verify Claim Live";
    }
  }

  // === SECTION 2: VISUAL & VIDEO FORENSICS ===
  function setVisualFile(file) {
    state.visualFile = file;
    const empty = document.getElementById("visualEmptyState");
    const box = document.getElementById("visualPreviewBox");
    const img = document.getElementById("visualPreviewImg");
    if (!file) {
      empty.classList.remove("hidden");
      box.classList.add("hidden");
      document.getElementById("visualFile").value = "";
      return;
    }
    empty.classList.add("hidden");
    box.classList.remove("hidden");
    document.getElementById("visualFileName").textContent = file.name;
    document.getElementById("visualFileMeta").textContent = `${(file.size / 1024).toFixed(1)} KB • ${file.type || "media"}`;
    if (file.type.startsWith("image/")) {
      img.src = URL.createObjectURL(file);
      img.classList.remove("hidden");
    } else {
      img.classList.add("hidden");
    }
  }

  function renderVisualResult(data) {
    state.lastVisual = data;
    document.getElementById("btnDownloadVisual").classList.remove("hidden");
    document.getElementById("btnPrintVisual").classList.remove("hidden");

    const v = data.visual_forensics;
    const p = data.provenance;
    const safety = v.content_safety || {};
    const el = document.getElementById("visualResult");
    el.classList.remove("hidden");

    const safetyBanner = safety.suggest_complaint ? `
      <div class="lg:col-span-12 p-4 rounded-2xl bg-rose-50 border border-rose-200 flex flex-wrap items-center justify-between gap-3">
        <div class="text-xs text-rose-800 space-y-0.5">
          <div class="font-bold uppercase">Content Safety &amp; Deepfake Alert</div>
          <div>${escapeHtml((safety.safety_alerts || ["Flagged for potential manipulation or sensitive content."]).join(" "))}</div>
        </div>
        <button type="button" class="open-cmp-inline px-5 py-2 rounded-full bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold shadow-sm" data-cat="${escapeHtml(safety.suggested_category || "Deepfake Image / Video Manipulation")}">Report / File Cyber Complaint</button>
      </div>` : "";

    const factorsHtml = (v.counterfactual_factors || []).map((f) => {
      const badge = f.status === "FLAG" ? "bg-rose-50 text-rose-700 border-rose-200" : f.status === "WARN" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-emerald-50 text-emerald-700 border-emerald-200";
      return `<div class="p-3 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] flex items-start justify-between gap-3">
        <div><div class="text-xs font-semibold">${escapeHtml(f.signal)}</div><p class="text-xs text-[#6E6E73] mt-0.5">${escapeHtml(f.detail)}</p></div>
        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${badge}">${escapeHtml(f.status)}</span>
      </div>`;
    }).join("");

    const cloudHtml = (v.cloud_ensemble || []).map((c) => `
      <div class="p-3 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs">
        <div class="flex justify-between font-semibold"><span>${escapeHtml(c.provider)}</span><span class="text-[#0071E3]">${escapeHtml(c.status)}</span></div>
        <pre class="text-[11px] text-[#6E6E73] whitespace-pre-wrap mt-1">${escapeHtml(JSON.stringify(c.data || c.verdict || c.detail || c.reason, null, 2))}</pre>
      </div>`).join("");

    el.innerHTML = `
      ${safetyBanner}
      <div class="apple-card p-6 lg:col-span-4 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-base font-semibold">Forensic Verdict</h3>
          <span class="px-3 py-1 rounded-full text-xs font-semibold border ${verdictBadgeClass(v.verdict)}">${escapeHtml(v.verdict)}</span>
        </div>
        ${renderGaugeSVG(v.synthetic_risk_score, "AI Risk", true)}
        <p class="text-xs text-center text-[#6E6E73]">95% CI: ${v.confidence_interval[0]}%–${v.confidence_interval[1]}% • ${escapeHtml(v.dimensions)}</p>
        <div class="space-y-2">${factorsHtml}</div>
      </div>

      <div class="apple-card p-6 lg:col-span-4 space-y-4">
        <h3 class="text-base font-semibold">Explainable AI (XAI) Evidence</h3>
        ${v.visualizations?.fft_spectrum_b64 ? `
        <div>
          <div class="text-xs font-medium text-[#6E6E73] mb-1.5">2D-FFT Frequency-Domain Spectrum</div>
          <img src="${v.visualizations.fft_spectrum_b64}" class="w-full rounded-2xl border border-black/10" alt="FFT Spectrum" />
        </div>
        <div>
          <div class="text-xs font-medium text-[#6E6E73] mb-1.5">ELA Inpainting / Splicing Map</div>
          <img src="${v.visualizations.ela_saliency_b64}" class="w-full rounded-2xl border border-black/10" alt="ELA Map" />
        </div>` : `<div class="p-4 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs text-[#6E6E73]">Document structural inspection completed (no image heatmaps for PDF/DOCX). Probabilistic evidence, not legal proof.</div>`}
      </div>

      <div class="apple-card p-6 lg:col-span-4 space-y-4">
        <h3 class="text-base font-semibold">Cloud Ensemble &amp; C2PA Provenance</h3>
        <div class="space-y-2">${cloudHtml}</div>
        <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] space-y-1.5 text-xs">
          <div><b>C2PA:</b> ${escapeHtml(p.c2pa_status)}</div>
          <div><b>EXIF Fields:</b> ${p.exif_fields_found} | <b>Hex Tags:</b> ${escapeHtml((p.hex_signatures_detected || []).join(", ") || "None")}</div>
          <div><b>SHA-256:</b> <span class="font-mono text-[11px] break-all text-[#6E6E73]">${escapeHtml(p.sha256_certificate)}</span></div>
          ${(p.metadata_anomalies || []).map((a) => `<div class="text-amber-700">• ${escapeHtml(a)}</div>`).join("")}
        </div>
      </div>`;
  }

  async function runVisualAudit(useSample = false) {
    if (!useSample && !state.visualFile) return showToast("Drop or select an image/MP4 file first.", "error");
    const btn = document.getElementById("btnRunVisual");
    btn.disabled = true;
    btn.textContent = "Auditing media...";
    try {
      let res;
      if (useSample) {
        res = await fetch("/api/v1/audit/media/sample", { method: "POST" });
      } else {
        const form = new FormData();
        form.append("file", state.visualFile);
        res = await fetch("/api/v1/audit/media", { method: "POST", body: form });
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Visual audit failed");
      renderVisualResult(data);
      loadHistory("visual");
      showToast("Visual forensic audit complete & saved.", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Run Forensic Audit";
    }
  }

  // === SECTION 3: AUDIO FORENSICS + WAVEFORM ===
  async function drawAudioWaveform(file) {
    const canvas = document.getElementById("audioWaveCanvas");
    const ctx = canvas.getContext("2d");
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    try {
      const arrayBuf = await file.arrayBuffer();
      const audioCtx = new (window.AudioContext || window.webkitAudioContext)();
      const decoded = await audioCtx.decodeAudioData(arrayBuf);
      const data = decoded.getChannelData(0);
      const step = Math.ceil(data.length / canvas.width);
      const amp = canvas.height / 2;
      ctx.fillStyle = "#0071E3";
      for (let i = 0; i < canvas.width; i += 3) {
        let min = 1.0, max = -1.0;
        for (let j = 0; j < step; j++) {
          const val = data[i * step + j] || 0;
          if (val < min) min = val;
          if (val > max) max = val;
        }
        const h = Math.max(2, (max - min) * amp);
        ctx.fillRect(i, amp - h / 2, 2, h);
      }
      audioCtx.close();
    } catch {}
  }

  function setAudioFile(file) {
    state.audioFile = file;
    const empty = document.getElementById("audioEmptyState");
    const box = document.getElementById("audioPreviewBox");
    const player = document.getElementById("audioPreviewPlayer");
    if (!file) {
      empty.classList.remove("hidden");
      box.classList.add("hidden");
      document.getElementById("audioFile").value = "";
      player.removeAttribute("src");
      return;
    }
    empty.classList.add("hidden");
    box.classList.remove("hidden");
    document.getElementById("audioFileName").textContent = `${file.name} (${(file.size / 1024).toFixed(1)} KB)`;
    player.src = URL.createObjectURL(file);
    drawAudioWaveform(file);
  }

  function renderAudioResult(data) {
    state.lastAudio = data;
    document.getElementById("btnDownloadAudio").classList.remove("hidden");
    document.getElementById("btnPrintAudio").classList.remove("hidden");

    const a = data.audio_forensics;
    const el = document.getElementById("audioResult");
    el.classList.remove("hidden");

    const complaintBanner = a.suggest_complaint ? `
      <div class="lg:col-span-12 p-4 rounded-2xl bg-rose-50 border border-rose-200 flex flex-wrap items-center justify-between gap-3">
        <div class="text-xs text-rose-800"><b>Voice-Clone Fraud Alert:</b> High synthetic voice probability detected. If this is an impersonation or digital arrest scam call, file a complaint immediately.</div>
        <button type="button" class="open-cmp-inline px-5 py-2 rounded-full bg-rose-600 hover:bg-rose-700 text-white text-xs font-semibold" data-cat="AI Voice-Clone / Digital Arrest Scam">Report Voice-Clone Scam</button>
      </div>` : "";

    const factorsHtml = (a.counterfactual_factors || []).map((f) => {
      const badge = f.status === "FLAG" ? "bg-rose-50 text-rose-700 border-rose-200" : f.status === "WARN" ? "bg-amber-50 text-amber-700 border-amber-200" : "bg-emerald-50 text-emerald-700 border-emerald-200";
      return `<div class="p-3 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] flex items-start justify-between gap-3">
        <div><div class="text-xs font-semibold">${escapeHtml(f.signal)}</div><p class="text-xs text-[#6E6E73] mt-0.5">${escapeHtml(f.detail)}</p></div>
        <span class="px-2 py-0.5 rounded-full text-[10px] font-bold border ${badge}">${escapeHtml(f.status)}</span>
      </div>`;
    }).join("");

    const cloudHtml = (a.cloud_ensemble || []).map((c) => `
      <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs">
        <div class="flex justify-between font-semibold"><span>${escapeHtml(c.provider)}</span><span class="text-[#0071E3]">${escapeHtml(c.status)}</span></div>
        <pre class="text-[11px] text-[#6E6E73] whitespace-pre-wrap mt-1">${escapeHtml(JSON.stringify(c.data || c.detail || c.reason, null, 2))}</pre>
      </div>`).join("");

    el.innerHTML = `
      ${complaintBanner}
      <div class="apple-card p-6 lg:col-span-5 space-y-4">
        <div class="flex items-center justify-between">
          <h3 class="text-base font-semibold">Voice-Clone Verdict</h3>
          <span class="px-3 py-1 rounded-full text-xs font-semibold border ${verdictBadgeClass(a.verdict)}">${escapeHtml(a.verdict)}</span>
        </div>
        ${renderGaugeSVG(a.voice_clone_risk_score, "Clone Risk", true)}
        <p class="text-xs text-center text-[#6E6E73]">Duration: ${a.duration_seconds ?? "N/A"}s • Sample Rate: ${a.sample_rate_hz ?? "Cloud"} Hz</p>
        <div class="space-y-2">${factorsHtml}</div>
      </div>
      <div class="apple-card p-6 lg:col-span-7 space-y-4">
        <h3 class="text-base font-semibold">Cloud Voice-Clone Ensemble</h3>
        <div class="space-y-3">${cloudHtml}</div>
        <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs">
          <b>SHA-256 Certificate:</b> <span class="font-mono break-all text-[#6E6E73]">${escapeHtml(data.sha256_certificate)}</span>
        </div>
      </div>`;
  }

  async function runAudioAudit(useSample = false) {
    if (!useSample && !state.audioFile) return showToast("Drop or select an audio file first.", "error");
    const btn = document.getElementById("btnRunAudio");
    btn.disabled = true;
    btn.textContent = "Auditing voice track...";
    try {
      let res;
      if (useSample) {
        res = await fetch("/api/v1/audit/audio/sample", { method: "POST" });
      } else {
        const form = new FormData();
        form.append("file", state.audioFile);
        res = await fetch("/api/v1/audit/audio", { method: "POST", body: form });
      }
      const data = await res.json();
      if (!res.ok) throw new Error(data.detail || "Audio audit failed");
      renderAudioResult(data);
      loadHistory("audio");
      showToast("Voice-clone audit complete & saved.", "success");
    } catch (err) {
      showToast(err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Audit Voice Track";
    }
  }

  // === SECTION 4: LIVE CIVIC PULSE FEED ===
  function renderFeedResult(d) {
    state.lastFeed = d;
    document.getElementById("btnDownloadFeed").classList.remove("hidden");
    const el = document.getElementById("feedResults");

    const fcHtml = (d.google_factchecks?.claims || []).map((c) => `
      <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs space-y-1">
        <div class="flex justify-between gap-2"><span class="font-semibold text-amber-700">${escapeHtml(c.rating)}</span><span class="text-[#6E6E73]">${escapeHtml(c.publisher)}</span></div>
        <p class="text-[#1D1D1F] font-medium">${escapeHtml(c.text || c.title)}</p>
        ${c.url ? `<a href="${escapeHtml(c.url)}" target="_blank" class="text-[#0071E3] hover:underline">Read ClaimReview ↗</a>` : ""}
      </div>`).join("") || `<p class="text-xs text-[#6E6E73]">No matching ClaimReviews returned for this topic.</p>`;

    const parHtml = (d.parallel_search?.results || []).map((r) => `
      <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs space-y-1">
        <a href="${escapeHtml(r.url)}" target="_blank" class="font-semibold text-[#0071E3] hover:underline">${escapeHtml(r.title)}</a>
        <p class="text-[#6E6E73]">${escapeHtml(r.snippet)}</p>
      </div>`).join("") || `<p class="text-xs text-[#6E6E73]">Parallel AI: ${escapeHtml(d.parallel_search?.status)}</p>`;

    const wikiHtml = (d.wikipedia?.results || []).map((w) => `
      <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs space-y-1">
        <a href="${escapeHtml(w.url)}" target="_blank" class="font-semibold text-emerald-700 hover:underline">${escapeHtml(w.title)}</a>
        <p class="text-[#6E6E73]">${escapeHtml(w.snippet)}</p>
      </div>`).join("") || `<p class="text-xs text-[#6E6E73]">No Wikipedia entries found.</p>`;

    const newsHtml = (d.newsdata?.articles || []).map((a) => `
      <div class="p-3.5 rounded-2xl bg-[#FAFAFC] border border-[#E5E5EA] text-xs space-y-1">
        <a href="${escapeHtml(a.url)}" target="_blank" class="font-semibold text-indigo-700 hover:underline">${escapeHtml(a.title)}</a>
        <p class="text-[#6E6E73]">${escapeHtml(a.snippet)}</p>
      </div>`).join("") || `<p class="text-xs text-[#6E6E73]">NewsData.io: ${escapeHtml(d.newsdata?.reason || d.newsdata?.status)}</p>`;

    el.innerHTML = `
      <div class="apple-card p-6 space-y-3"><h3 class="font-semibold text-sm">Google Fact Check Tools</h3>${fcHtml}</div>
      <div class="apple-card p-6 space-y-3"><h3 class="font-semibold text-sm">Parallel AI Web Intelligence</h3>${parHtml}</div>
      <div class="apple-card p-6 space-y-3"><h3 class="font-semibold text-sm">Wikipedia Reference Context</h3>${wikiHtml}</div>
      <div class="apple-card p-6 space-y-3"><h3 class="font-semibold text-sm">Breaking News (NewsData.io)</h3>${newsHtml}</div>`;
  }

  async function runLiveFeed(save = true) {
    const topic = document.getElementById("feedTopic").value.trim() || "India election AI deepfake";
    const btn = document.getElementById("btnRunFeed");
    btn.disabled = true;
    btn.textContent = "Fetching live data...";
    try {
      const res = await fetch(`/api/v1/live-feed?topic=${encodeURIComponent(topic)}&save=${save}`);
      const d = await res.json();
      renderFeedResult(d);
      if (save) {
        loadHistory("feed");
        showToast("Live Civic Pulse briefing updated & saved.", "success");
      }
    } catch (err) {
      showToast("Feed fetch failed: " + err.message, "error");
    } finally {
      btn.disabled = false;
      btn.textContent = "Fetch & Save Live Feed";
    }
  }

  // === SECTION 5: LIVE CAMERA AUDIT (REAL-TIME PERSON & OBJECT NAMES + SAFETY) ===
  function renderLiveMetrics(m) {
    document.getElementById("btnSaveLiveSnap").classList.remove("hidden");
    document.getElementById("btnDownloadLive").classList.remove("hidden");
    document.getElementById("liveMetrics").innerHTML = `
      <div class="flex items-center justify-between">
        <span class="font-semibold text-base text-[#1D1D1F]">Live Forensic Telemetry</span>
        <span class="px-3 py-1 rounded-full text-xs font-semibold border ${verdictBadgeClass(m.verdict)}">${escapeHtml(m.verdict)}</span>
      </div>
      ${renderGaugeSVG(m.synthetic_risk_score, "Stream Risk", true)}
      <div class="grid grid-cols-2 gap-3 text-xs">
        <div class="p-3 rounded-xl bg-white border border-[#E5E5EA]">PRNU Silicon Noise: <b>${m.prnu_noise}</b></div>
        <div class="p-3 rounded-xl bg-white border border-[#E5E5EA]">Lighting Delta: <b>${m.lighting_delta}</b></div>
      </div>
      <p class="text-xs text-[#6E6E73]">${escapeHtml(m.xai_summary)}</p>`;

    if (m.sensitive_warning || m.synthetic_risk_score >= 60) {
      const banner = document.getElementById("liveSafetyBanner");
      banner.classList.remove("hidden");
      document.getElementById("liveSafetyText").innerHTML = m.sensitive_warning
        ? `<b>Sensitive Content Warning:</b> Elevated exposure detected on live feed (${m.skin_exposure_pct}%). If you are witnessing non-consensual or harmful live media, file an official complaint.`
        : `<b>Deepfake Stream Alert:</b> High synthetic manipulation risk (${m.synthetic_risk_score}%) detected on live camera.`;
    }
  }

  async function runObjectDetectionLoop() {
    const video = document.getElementById("liveVideo");
    const overlay = document.getElementById("liveOverlayCanvas");
    if (!state.liveStream || !state.cocoModel || video.readyState < 2) {
      if (state.liveStream) state.detectRaf = requestAnimationFrame(runObjectDetectionLoop);
      return;
    }

    overlay.width = video.videoWidth || 640;
    overlay.height = video.videoHeight || 480;
    const ctx = overlay.getContext("2d");
    ctx.clearRect(0, 0, overlay.width, overlay.height);

    try {
      const predictions = await state.cocoModel.detect(video);
      const summaryMap = {};
      let screenInjectionDetected = false;

      predictions.forEach((pred) => {
        if (pred.score < 0.45) return;
        const [x, y, w, h] = pred.bbox;
        const label = `${pred.class} (${Math.round(pred.score * 100)}%)`;
        summaryMap[pred.class] = Math.max(summaryMap[pred.class] || 0, Math.round(pred.score * 100));

        const isScreenDevice = ["cell phone", "tv", "laptop"].includes(pred.class);
        if (isScreenDevice) screenInjectionDetected = true;

        ctx.strokeStyle = isScreenDevice ? "#E11D48" : pred.class === "person" ? "#16A34A" : "#0071E3";
        ctx.lineWidth = 3;
        ctx.strokeRect(x, y, w, h);

        ctx.fillStyle = ctx.strokeStyle;
        const textW = ctx.measureText(label).width + 14;
        ctx.fillRect(x, Math.max(0, y - 24), textW, 24);
        ctx.fillStyle = "#FFFFFF";
        ctx.font = "600 13px -apple-system, sans-serif";
        ctx.fillText(label, x + 7, Math.max(16, y - 7));
      });

      const entries = Object.entries(summaryMap);
      state.detectedObjects = entries.map(([name, pct]) => `${name} (${pct}%)`);
      const listEl = document.getElementById("liveObjectsList");
      listEl.innerHTML = entries.length
        ? entries.map(([name, pct]) => {
            const cls = name === "person" ? "bg-emerald-50 text-emerald-700 border-emerald-200" : ["cell phone", "tv", "laptop"].includes(name) ? "bg-rose-50 text-rose-700 border-rose-200" : "bg-blue-50 text-[#0071E3] border-blue-200";
            return `<span class="px-3 py-1 rounded-full font-semibold border ${cls}">${escapeHtml(name)} • ${pct}%</span>`;
          }).join("")
        : `<span class="text-[#6E6E73]">Scanning frame for persons &amp; objects...</span>`;

      if (screenInjectionDetected) {
        const banner = document.getElementById("liveSafetyBanner");
        banner.classList.remove("hidden");
        document.getElementById("liveSafetyText").innerHTML = `<b>Screen-Recapture Warning:</b> A secondary screen (phone/laptop/TV) was detected in front of the camera — a common deepfake injection tactic.`;
      }
    } catch {}

    if (state.liveStream) {
      state.detectRaf = requestAnimationFrame(runObjectDetectionLoop);
    }
  }

  async function startLiveCam() {
    const statusBadge = document.getElementById("aiModelStatus");
    try {
      state.liveStream = await navigator.mediaDevices.getUserMedia({ video: { width: 640, height: 480 } });
      const video = document.getElementById("liveVideo");
      video.srcObject = state.liveStream;
      await video.play();

      // Load real-time COCO-SSD person & object detector
      if (!state.cocoModel && window.cocoSsd) {
        statusBadge.textContent = "Vision AI: Loading COCO-SSD...";
        state.cocoModel = await window.cocoSsd.load();
      }
      if (state.cocoModel) {
        statusBadge.textContent = "Vision AI: Active (Persons & 80+ Objects)";
        statusBadge.className = "text-xs px-3 py-1.5 rounded-full bg-emerald-50 text-emerald-700 border border-emerald-200 font-semibold";
        runObjectDetectionLoop();
      }

      const proto = location.protocol === "https:" ? "wss" : "ws";
      state.liveWs = new WebSocket(`${proto}://${location.host}/ws/live-audit`);
      state.liveWs.onmessage = (evt) => {
        const m = JSON.parse(evt.data);
        state.lastLive = m;
        renderLiveMetrics(m);
      };
      const canvas = document.getElementById("liveCanvas");
      const ctx = canvas.getContext("2d");
      state.liveTimer = setInterval(() => {
        if (state.liveWs && state.liveWs.readyState === 1) {
          ctx.drawImage(video, 0, 0, canvas.width, canvas.height);
          state.liveWs.send(canvas.toDataURL("image/jpeg", 0.8));
        }
      }, 2000);
      showToast("Live Camera Audit & Object Recognition active.", "success");
    } catch (err) {
      showToast("Camera access denied or unavailable. Open in Chrome/Edge.", "error");
    }
  }

  function stopLiveCam() {
    cancelAnimationFrame(state.detectRaf);
    clearInterval(state.liveTimer);
    if (state.liveWs) state.liveWs.close();
    if (state.liveStream) state.liveStream.getTracks().forEach((t) => t.stop());
    state.liveStream = null;
    const overlay = document.getElementById("liveOverlayCanvas");
    overlay.getContext("2d").clearRect(0, 0, overlay.width, overlay.height);
    document.getElementById("aiModelStatus").textContent = "Vision AI: Standby";
    showToast("Live camera stopped.", "info");
  }

  async function saveLiveSnapshot() {
    if (!state.lastLive) return showToast("Start the camera first to capture telemetry.", "error");
    try {
      const res = await fetch("/api/v1/audit/live-snapshot", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          verdict: state.lastLive.verdict,
          synthetic_risk_score: state.lastLive.synthetic_risk_score,
          prnu_noise: state.lastLive.prnu_noise,
          lighting_delta: state.lastLive.lighting_delta,
          detected_objects: state.detectedObjects,
          xai_summary: state.lastLive.xai_summary,
        }),
      });
      if (!res.ok) throw new Error("Failed to save snapshot");
      loadHistory("live");
      showToast("Live snapshot saved to history.", "success");
    } catch (err) {
      showToast(err.message, "error");
    }
  }

  // === Bind All Event Listeners ===
  document.addEventListener("DOMContentLoaded", () => {
    document.querySelectorAll(".seg-btn").forEach((btn) => {
      btn.addEventListener("click", () => showTab(btn.dataset.tab));
    });

    document.querySelectorAll(".btn-clear-history").forEach((btn) => {
      btn.addEventListener("click", async () => {
        const sec = btn.dataset.clearSection;
        await fetch(`/api/v1/history/section/${sec}`, { method: "DELETE" });
        loadHistory(sec);
        showToast(`Cleared ${sec} history.`, "info");
      });
    });

    // Global delegated clicks (history view/delete, inline complaint triggers, complaint delete)
    document.body.addEventListener("click", async (e) => {
      const cmpInline = e.target.closest(".open-cmp-inline");
      if (cmpInline) {
        openComplaintModal(cmpInline.dataset.cat || "");
        return;
      }
      const delCmp = e.target.closest(".del-cmp-btn");
      if (delCmp) {
        await fetch(`/api/v1/complaints/${delCmp.dataset.delCmp}`, { method: "DELETE" });
        showToast("Complaint removed.", "info");
        openComplaintsList();
        return;
      }
      const histBtn = e.target.closest(".hist-btn");
      if (!histBtn) return;
      const { action, id, section } = histBtn.dataset;
      if (action === "delete") {
        await fetch(`/api/v1/history/item/${id}`, { method: "DELETE" });
        showToast("Record deleted from history.", "info");
        loadHistory(section);
      } else if (action === "view") {
        const res = await fetch(`/api/v1/history/item/${id}`);
        const record = await res.json();
        const p = record.payload;
        if (section === "fact") renderFactResult(p);
        if (section === "visual") renderVisualResult(p);
        if (section === "audio") renderAudioResult(p);
        if (section === "feed") renderFeedResult(p);
        if (section === "live") {
          state.lastLive = p.live_snapshot;
          renderLiveMetrics(p.live_snapshot);
        }
        showToast("Loaded saved record from history.", "success");
      }
    });

    // Complaint Modal Controls
    document.getElementById("btnHeaderReport").addEventListener("click", () => openComplaintModal());
    document.getElementById("btnFooterReport").addEventListener("click", () => openComplaintModal());
    document.getElementById("btnLiveComplaint").addEventListener("click", () => openComplaintModal("Harmful / Impersonation Live Stream"));
    document.getElementById("btnCloseComplaintModal").addEventListener("click", closeComplaintModal);
    document.getElementById("btnCancelComplaint").addEventListener("click", closeComplaintModal);
    document.getElementById("btnReturnSection").addEventListener("click", closeComplaintModal);
    document.getElementById("complaintForm").addEventListener("submit", submitComplaintForm);
    document.getElementById("btnDownloadReceipt").addEventListener("click", () => downloadJSON(state.lastComplaintReceipt, "ComplaintReceipt"));

    document.getElementById("btnOpenComplaintsList").addEventListener("click", openComplaintsList);
    document.getElementById("btnCloseComplaintsList").addEventListener("click", () => document.getElementById("complaintsListModal").classList.add("hidden"));

    // Fact-Check Controls
    document.getElementById("btnRunFactCheck").addEventListener("click", runFactCheck);
    document.getElementById("btnCopyFact").addEventListener("click", () => {
      if (!state.lastFact) return;
      const f = state.lastFact.fact_check;
      navigator.clipboard.writeText(`CivicPulse Verdict: ${f.verdict} (${f.confidence}%)
Claim: ${f.claim}
Reasoning: ${f.reasoning}`);
      showToast("Verdict copied to clipboard.", "success");
    });
    document.getElementById("btnDownloadFact").addEventListener("click", () => downloadJSON(state.lastFact, "FactCheck"));
    document.getElementById("btnPrintFact").addEventListener("click", () => downloadPrintableReport("Fact-Check & Origin Report", state.lastFact));
    document.getElementById("factSample1").addEventListener("click", () => {
      document.getElementById("claimInput").value = "The Reserve Bank of India announced that 500 rupee notes will be discontinued next month.";
    });
    document.getElementById("factSample2").addEventListener("click", () => {
      document.getElementById("claimInput").value = "Police can place Indian citizens under digital arrest via WhatsApp video call and demand immediate UPI transfer.";
    });

    // Visual Drag-and-Drop + Controls
    const vZone = document.getElementById("visualDropZone");
    const vInput = document.getElementById("visualFile");
    vZone.addEventListener("click", (e) => { if (e.target.id !== "btnClearVisualFile") vInput.click(); });
    vInput.addEventListener("change", (e) => setVisualFile(e.target.files[0]));
    vZone.addEventListener("dragover", (e) => { e.preventDefault(); vZone.classList.add("dragover"); });
    vZone.addEventListener("dragleave", () => vZone.classList.remove("dragover"));
    vZone.addEventListener("drop", (e) => { e.preventDefault(); vZone.classList.remove("dragover"); if (e.dataTransfer.files[0]) setVisualFile(e.dataTransfer.files[0]); });
    document.getElementById("btnClearVisualFile").addEventListener("click", (e) => { e.stopPropagation(); setVisualFile(null); });
    document.getElementById("btnRunVisual").addEventListener("click", () => runVisualAudit(false));
    document.getElementById("btnVisualSample").addEventListener("click", () => runVisualAudit(true));
    document.getElementById("btnDownloadVisual").addEventListener("click", () => downloadJSON(state.lastVisual, "VisualForensics"));
    document.getElementById("btnPrintVisual").addEventListener("click", () => downloadPrintableReport("Visual Deepfake Forensic Dossier", state.lastVisual));

    // Audio Drag-and-Drop + Controls
    const aZone = document.getElementById("audioDropZone");
    const aInput = document.getElementById("audioFile");
    aZone.addEventListener("click", (e) => { if (e.target.id !== "btnClearAudioFile" && e.target.tagName !== "AUDIO") aInput.click(); });
    aInput.addEventListener("change", (e) => setAudioFile(e.target.files[0]));
    aZone.addEventListener("dragover", (e) => { e.preventDefault(); aZone.classList.add("dragover"); });
    aZone.addEventListener("dragleave", () => aZone.classList.remove("dragover"));
    aZone.addEventListener("drop", (e) => { e.preventDefault(); aZone.classList.remove("dragover"); if (e.dataTransfer.files[0]) setAudioFile(e.dataTransfer.files[0]); });
    document.getElementById("btnClearAudioFile").addEventListener("click", (e) => { e.stopPropagation(); setAudioFile(null); });
    document.getElementById("btnRunAudio").addEventListener("click", () => runAudioAudit(false));
    document.getElementById("btnAudioSample").addEventListener("click", () => runAudioAudit(true));
    document.getElementById("btnDownloadAudio").addEventListener("click", () => downloadJSON(state.lastAudio, "AudioForensics"));
    document.getElementById("btnPrintAudio").addEventListener("click", () => downloadPrintableReport("Audio Voice-Clone Forensic Dossier", state.lastAudio));

    // Feed Controls + Topic Chips
    document.querySelectorAll(".topic-chip").forEach((chip) => {
      chip.addEventListener("click", () => {
        document.getElementById("feedTopic").value = chip.dataset.topic;
        runLiveFeed(true);
      });
    });
    document.getElementById("btnRunFeed").addEventListener("click", () => runLiveFeed(true));
    document.getElementById("btnDownloadFeed").addEventListener("click", () => downloadJSON(state.lastFeed, "LiveCivicFeed"));

    // Live Camera Controls
    document.getElementById("btnStartCam").addEventListener("click", startLiveCam);
    document.getElementById("btnStopCam").addEventListener("click", stopLiveCam);
    document.getElementById("btnSaveLiveSnap").addEventListener("click", saveLiveSnapshot);
    document.getElementById("btnDownloadLive").addEventListener("click", () => downloadJSON({ ...state.lastLive, detected_objects: state.detectedObjects }, "LiveCameraAudit"));

    loadStatus();
    loadHistory("fact");
  });
})();
