"use strict";
// kugiri web UI：新任务 → 进度 → 结果（播放 + 叠加字幕、逐条改字、重新对齐 / 断行、质检跳转、下载）。

const I18N = {
  ja: {
    tagline: "日本語字幕のタイミングと改行", new_job: "＋ 新しい字幕", dict: "ユーザー辞書",
    drop_main: "動画・音声ファイルをドロップ", drop_sub: "またはクリックして選択（mp4 / mov / mkv / wav / mp3 / m4a …）",
    script: "台本", optional: "任意 — なければ音声認識します", load_txt: "txt を読み込む",
    script_ph: "1 行 1 段落。空のままなら音声から文字起こしします。",
    speakers: "行頭の「名前：」を話者として扱う",
    preset: "プリセット", asr_model: "認識モデル", asr_hint: "台本がないときだけ使います", ruby: "ふりがな",
    start: "字幕を作る", uploading: "アップロード中 {p}%", recent: "最近の字幕",
    st_queued: "順番待ち", st_running: "処理中", st_done: "完了", st_error: "エラー", st_cancelled: "キャンセル済み",
    stage_load: "準備", stage_transcribe: "音声認識", stage_align: "タイミング合わせ", stage_reflow: "改行",
    queue_pos: "順番待ち（前に {n} 件）", elapsed: "{s} 秒経過", loading_models: "モデルを読み込み中…",
    reflow: "改行し直す", realign: "修正を反映して再合わせ", download: "ダウンロード", script_txt: "台本 txt",
    qc: "要確認の箇所", qc_none: "台本と音声がずれていそうな箇所はありません", qc_n: "{n} 箇所",
    tab_cues: "字幕", tab_script: "台本・認識結果", edits: "{n} 件修正（未反映）",
    script_help: "この台本で音声に合わせ直せます。認識結果を直してから使ったり、txt を読み込んだりできます。",
    download_txt: "txt をダウンロード", realign_script: "この台本で再合わせ",
    dict_help: "1 行 1 語、タブ区切り：表記 ⇥ 読み ⇥ 分割禁止（1 / 0、省略時 1）\n読みはふりがな・位置合わせに使われ、分割禁止の語は途中で改行されません。",
    dict_try_ph: "読みを確認：文を入力", close: "閉じる", save: "保存", saved: "保存しました（{n} 語）",
    reason_low_confidence: "自信度が低い", reason_squeezed: "詰まっている（台本が多い？）",
    reason_stretched: "間延び（音声が多い？）", reason_unaligned: "合わせられず", reason_asr_fallback: "認識をやり直し",
    pill_idle: "{d}待機中", pill_busy: "{d}処理中", pill_warm: "モデル読み込み中…", pill_err: "モデル読み込み失敗",
    downloading: "モデルをダウンロード中（初回のみ）{d} / {t} GB",
    dl_note: "初回だけ、モデルをダウンロードしています（{d} / {t} GB）。今すぐ字幕を作り始めることもできます。ダウンロードが終わってから処理されます。", pill_dl: "モデルをダウンロード中 {d} / {t} GB",
    asr_qwen3_1_7b: "Qwen3-ASR 1.7B（高精度）", asr_qwen3_0_6b: "Qwen3-ASR 0.6B（速い・省メモリ）",
    asr_omni: "omniASR（句読点なし・軽量）",
    ruby_none: "なし", ruby_all: "すべての漢字", ruby_user: "辞書の語だけ",
    ruby_hard: "難しい語だけ（常用漢字外・特別な読み）", ruby_grade: "小{n}向け（まだ習っていない漢字）", ruby_once: "初出だけ",
    preset_youtube: "YouTube 横", preset_vertical: "縦型ショート", preset_netflix: "Netflix",
    reflowed: "改行し直しました", need_file: "ファイルを選んでください",
    cancel: "キャンセル", cancelled: "キャンセルしました",
    theme_auto: "外観：システムに合わせる", theme_light: "外観：ライト", theme_dark: "外観：ダーク",
  },
  en: {
    tagline: "Japanese subtitle timing & line breaks", new_job: "+ New subtitles", dict: "User dictionary",
    drop_main: "Drop a video or audio file", drop_sub: "or click to choose (mp4 / mov / mkv / wav / mp3 / m4a …)",
    script: "Script", optional: "optional — transcribed from the audio if empty", load_txt: "Load .txt",
    script_ph: "One paragraph per line. Leave empty to transcribe the audio.",
    speakers: "Treat a leading “Name:” as the speaker",
    preset: "Preset", asr_model: "Speech recognition", asr_hint: "Only used without a script", ruby: "Furigana",
    start: "Make subtitles", uploading: "Uploading {p}%", recent: "Recent",
    st_queued: "Queued", st_running: "Running", st_done: "Done", st_error: "Error", st_cancelled: "Cancelled",
    stage_load: "Prepare", stage_transcribe: "Transcribe", stage_align: "Align", stage_reflow: "Line breaks",
    queue_pos: "Queued ({n} ahead)", elapsed: "{s} s", loading_models: "Loading models…",
    reflow: "Re-break lines", realign: "Re-align with edits", download: "Download", script_txt: "Script .txt",
    qc: "Check these", qc_none: "No places where script and audio seem to disagree", qc_n: "{n}",
    tab_cues: "Subtitles", tab_script: "Script / transcript", edits: "{n} edited (not applied)",
    script_help: "Re-align the audio to this script. Fix the transcript first, or load a .txt.",
    download_txt: "Download .txt", realign_script: "Re-align with this script",
    dict_help: "One word per line, tab-separated: surface ⇥ reading ⇥ no-split (1 / 0, default 1)\nReadings are used for furigana and alignment; no-split words are never broken.",
    dict_try_ph: "Check a reading: type a sentence", close: "Close", save: "Save", saved: "Saved ({n} words)",
    reason_low_confidence: "low confidence", reason_squeezed: "squeezed (extra script?)",
    reason_stretched: "stretched (extra audio?)", reason_unaligned: "not aligned", reason_asr_fallback: "re-transcribed",
    pill_idle: "{d}idle", pill_busy: "{d}working", pill_warm: "Loading models…", pill_err: "Model load failed",
    downloading: "Downloading a model (first run only) {d} / {t} GB",
    dl_note: "Downloading the models (first run only): {d} / {t} GB. You can start a job now; it runs when the download finishes.", pill_dl: "Downloading a model: {d} / {t} GB",
    asr_qwen3_1_7b: "Qwen3-ASR 1.7B (accurate)", asr_qwen3_0_6b: "Qwen3-ASR 0.6B (fast, less memory)",
    asr_omni: "omniASR (no punctuation, light)",
    ruby_none: "None", ruby_all: "All kanji", ruby_user: "Dictionary words",
    ruby_hard: "Hard words only (non-Jōyō kanji / readings)", ruby_grade: "Grade {n} kids (kanji not yet learned)",
    ruby_once: "First occurrence only",
    preset_youtube: "YouTube", preset_vertical: "Vertical", preset_netflix: "Netflix",
    reflowed: "Line breaks updated", need_file: "Choose a file",
    cancel: "Cancel", cancelled: "Cancelled",
    theme_auto: "Appearance: match system", theme_light: "Appearance: light", theme_dark: "Appearance: dark",
  },
};

let lang = localStorage.getItem("kugiri.lang") || (navigator.language.startsWith("ja") ? "ja" : "en");
const t = (k, vars = {}) => (I18N[lang][k] ?? k).replace(/\{(\w+)\}/g, (_, v) => vars[v] ?? "");
const $ = (s) => document.querySelector(s);
const $$ = (s) => [...document.querySelectorAll(s)];

const S = { config: null, file: null, preset: "youtube", job: null, cues: [], poll: null, busy: false };

// ------------------------------------------------------------------ 通用
async function api(path, opts = {}) {
  const r = await fetch(path, opts);
  const ct = r.headers.get("content-type") || "";
  const body = ct.includes("json") ? await r.json() : await r.text();
  if (!r.ok) throw new Error(body.error || body || r.statusText);
  return body;
}
function toast(msg, err = false) {
  const el = $("#toast");
  el.textContent = msg; el.className = "toast" + (err ? " err" : ""); el.hidden = false;
  clearTimeout(toast._t); toast._t = setTimeout(() => (el.hidden = true), err ? 6000 : 2500);
}
function fmtTime(s) {
  const m = Math.floor(s / 60), x = s - m * 60;
  return `${m}:${x.toFixed(2).padStart(5, "0")}`;
}
function esc(s) { return s.replace(/[&<>"]/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[c])); }
function show(view) {
  for (const v of ["new", "progress", "result"]) $(`#view-${v}`).hidden = v !== view;
  $("#btn-new").hidden = view === "new";
}
function applyI18n() {
  document.documentElement.lang = lang;
  $$("[data-t]").forEach((el) => {
    const span = el.querySelector(":scope > span:not([class])");
    (el.tagName === "LABEL" && span ? span : el).textContent = t(el.dataset.t);
  });
  $$("[data-tp]").forEach((el) => (el.placeholder = t(el.dataset.tp)));
  $$("[data-ta]").forEach((el) => el.setAttribute("aria-label", t(el.dataset.ta)));
  $("#btn-lang").textContent = lang === "ja" ? "EN" : "日本語";
  applyTheme();
  if (S.config) { fillSelects(); renderPresetSegs(); renderPill(); renderRecent(); }
  if (S.job && !$("#view-result").hidden) renderResult(false);
  if (S.job && !$("#view-progress").hidden) renderProgress(S.job);
}

// ------------------------------------------------------------------ 外观（auto / light / dark）
const THEMES = ["auto", "light", "dark"], THEME_ICON = { auto: "◐", light: "☀", dark: "☾" };
const darkQuery = matchMedia("(prefers-color-scheme: dark)");
let theme = localStorage.getItem("kugiri.theme") || "auto";
function applyTheme() {
  const dark = theme === "dark" || (theme === "auto" && darkQuery.matches);
  document.documentElement.dataset.theme = dark ? "dark" : "light";
  $("#btn-theme").textContent = THEME_ICON[theme];
  $("#btn-theme").title = t("theme_" + theme);
  $("#btn-theme").setAttribute("aria-label", t("theme_" + theme));
}
darkQuery.addEventListener("change", () => theme === "auto" && applyTheme());

// ------------------------------------------------------------------ 配置 / 选项
function fillSelects() {
  const keep = { asr: $("#asr-model").value, r1: $("#ruby").value, r2: $("#ruby2").value };
  $("#asr-model").innerHTML = S.config.asr_models.map((m) => `<option value="${m}">${t("asr_" + m.replace(/[.-]/g, "_"))}</option>`).join("");
  // 学年选项写成 "hard:N"，发请求时拆成 ruby=hard + ruby_grade=N
  const ruby = S.config.ruby_modes.flatMap((m) => [`<option value="${m}">${t("ruby_" + m)}</option>`,
    ...(m === "hard" ? S.config.ruby_grades.map((g) => `<option value="hard:${g}">${t("ruby_grade", { n: g })}</option>`) : [])]).join("");
  $("#ruby").innerHTML = ruby; $("#ruby2").innerHTML = ruby;
  if (keep.asr) $("#asr-model").value = keep.asr;
  if (keep.r1) $("#ruby").value = keep.r1;
  $("#ruby2").value = S.job?.options ? rubyValue(S.job.options) : keep.r2 || "none";
}
const rubyValue = (o) => (o.ruby === "hard" && o.ruby_grade ? `hard:${o.ruby_grade}` : o.ruby);
function rubyFields(v, once) {
  const [ruby, grade] = v.split(":");
  return { ruby, ruby_grade: grade ? Number(grade) : 0, ruby_once: once };
}
function renderPresetSegs() {
  const names = Object.keys(S.config.presets);
  const mk = (el, cur, onPick) => {
    el.innerHTML = names.map((n) => `<button type="button" data-p="${n}" class="${n === cur ? "on" : ""}">${t("preset_" + n)}</button>`).join("");
    el.querySelectorAll("button").forEach((b) => (b.onclick = () => onPick(b.dataset.p)));
  };
  mk($("#preset-seg"), S.preset, (p) => { S.preset = p; renderPresetSegs(); });
  mk($("#preset-seg2"), S.job?.options?.preset || S.preset, (p) => applyOptions({ preset: p }));
}
function renderPill() {
  const c = S.config, el = $("#model-pill"), d = (c.device || "").toUpperCase();
  const note = $("#dl-note");
  note.hidden = !c.download;
  if (c.download) {
    note.querySelector("span").textContent = t("dl_note", { d: gb(c.download.done), t: gb(c.download.total) });
    note.querySelector(".dl-bar > div").style.width = `${c.download.total ? Math.round(100 * c.download.done / c.download.total) : 0}%`;
  }
  el.title = c.download ? `${c.download.name}: ${dlText(c.download)}` : "";
  if (c.download) { el.textContent = t("pill_dl", { d: gb(c.download.done), t: gb(c.download.total) }); el.className = "pill busy"; }
  else if (c.warming) { el.textContent = t("pill_warm"); el.className = "pill busy"; }
  else if (c.warm_error) { el.textContent = t("pill_err"); el.className = "pill"; el.title = c.warm_error; }
  else if (c.busy) { el.textContent = t("pill_busy", { d: d ? d + " · " : "" }); el.className = "pill busy"; }
  else { el.textContent = t("pill_idle", { d: d ? d + " · " : "" }); el.className = "pill ok"; }
}
function gb(n) { return n ? (n / 1e9).toFixed(1) : "?"; }
function dlText(dl) {
  return t("downloading", { d: gb(dl.done), t: gb(dl.total) });
}
function renderRecent() {
  const jobs = S.config.jobs || [];
  $("#recent").innerHTML = jobs.length ? `<h4>${t("recent")}</h4>` + jobs.map((j) =>
    `<div class="recent-row" tabindex="0" role="button" data-id="${j.id}"><span>${esc(j.name || j.id)}</span><span class="st">${t("st_" + j.state)}</span></div>`).join("") : "";
  $$("#recent .recent-row").forEach((r) => (r.onclick = () => openJob(r.dataset.id)));
}
async function refreshConfig() {
  try { S.config = await api("/api/config"); renderPill(); if (!$("#view-new").hidden) renderRecent(); } catch (e) { /* 服务停了 */ }
}

// ------------------------------------------------------------------ 新任务
function pickFile(f) {
  if (!f) return;
  S.file = f;
  $("#drop").classList.add("has");
  $("#drop-file").textContent = `${f.name}（${(f.size / 1e6).toFixed(1)} MB）`;
  $("#btn-start").disabled = false;
}
function readTxt(input, target) {
  input.onchange = async () => {
    const f = input.files[0]; if (!f) return;
    target.value = (await f.text()).replace(/^﻿/, "");
    input.value = "";
  };
}
function startJob() {
  if (!S.file) return toast(t("need_file"), true);
  const fd = new FormData();
  fd.append("media", S.file);
  fd.append("script", $("#script").value);
  fd.append("preset", S.preset);
  fd.append("asr_model", $("#asr-model").value);
  for (const [k, v] of Object.entries(rubyFields($("#ruby").value, $("#ruby-once").checked))) fd.append(k, v === true ? "1" : v === false ? "0" : v);
  fd.append("speakers", $("#speakers").checked ? "1" : "");
  const xhr = new XMLHttpRequest();
  xhr.open("POST", "/api/jobs");
  $("#btn-start").disabled = true;
  xhr.upload.onprogress = (e) => { if (e.lengthComputable) $("#upload-msg").textContent = t("uploading", { p: Math.round(100 * e.loaded / e.total) }); };
  xhr.onload = () => {
    $("#btn-start").disabled = false; $("#upload-msg").textContent = "";
    let body; try { body = JSON.parse(xhr.responseText); } catch { body = { error: xhr.responseText }; }
    if (xhr.status !== 200) return toast(body.error || xhr.statusText, true);
    follow(body);
  };
  xhr.onerror = () => { $("#btn-start").disabled = false; toast("upload failed", true); };
  xhr.send(fd);
}

// ------------------------------------------------------------------ 进度
function follow(job) {
  S.job = job;
  location.hash = "job=" + job.id;
  clearTimeout(S.poll);
  if (job.state === "done") return enterResult(job);
  show("progress");
  renderProgress(job);
  const tick = async () => {
    try {
      const j = await api(`/api/jobs/${job.id}`);
      S.job = j;
      if (j.state === "done") return enterResult(j);
      renderProgress(j);
      if (j.state === "error" || j.state === "cancelled") return;
    } catch (e) { $("#prog-error").hidden = false; $("#prog-error").textContent = e.message; return; }
    S.poll = setTimeout(tick, 500);
  };
  S.poll = setTimeout(tick, 400);
}
function renderProgress(j) {
  $("#prog-name").textContent = j.name;
  const stages = j.has_script ? ["load", "align", "reflow"] : ["load", "transcribe", "align", "reflow"];
  const cur = stages.indexOf(j.stage);
  $("#steps").innerHTML = stages.map((s, k) =>
    `<li class="${j.state === "done" || k < cur ? "done" : k === cur && j.state === "running" ? "cur" : ""}">${t("stage_" + s)}</li>`).join("");
  $("#bar-fill").style.width = `${Math.round(100 * (j.progress || 0))}%`;
  let label = t("st_" + j.state);
  if (j.state === "queued") label = S.config?.warming && j.queue_position <= 1 ? (S.config.download ? dlText(S.config.download) : t("loading_models")) : t("queue_pos", { n: j.queue_position ?? 0 });
  else if (j.state === "running" && j.download) label = dlText(j.download);
  else if (j.state === "running" && j.stage) label = `${t("stage_" + j.stage)} ${Math.round(100 * j.stage_progress)}%`;
  $("#prog-label").textContent = label;
  $("#prog-time").textContent = j.elapsed_s ? t("elapsed", { s: Math.round(j.elapsed_s) }) : "";
  $("#prog-error").hidden = j.state !== "error" && j.state !== "cancelled";
  $("#prog-error").textContent = j.error === "cancelled" ? t("cancelled") : j.error || "";
  $("#btn-cancel").hidden = !(j.state === "queued" || j.state === "running");
}

// ------------------------------------------------------------------ 结果
function enterResult(j) {
  const sameMedia = S.job && $("#video").dataset.src === j.media;
  S.job = j;
  show("result");
  if (!sameMedia || !$("#video").src) {
    $("#video").src = j.media; $("#video").dataset.src = j.media;
  }
  renderResult(true);
  refreshConfig();
}
function loadCues(j) {
  S.cues = j.cues.map((c, i) => ({ ...c, i, value: c.lines.join("\n"), edited: false }));
}
function renderResult(reload) {
  const j = S.job;
  if (reload) loadCues(j);
  fillSelects(); renderPresetSegs();
  $("#ruby2").value = rubyValue(j.options);
  $("#ruby-once2").checked = !!j.options.ruby_once;
  // 质检
  const w = j.summary?.warnings || [];
  $("#qc-count").textContent = w.length ? t("qc_n", { n: w.length }) : "";
  $("#qc-list").innerHTML = w.length ? w.map((x, k) => {
    const why = x.reason.split(",").map((r) => t("reason_" + r.split(":")[0])).join(" / ");
    return `<div class="qc-item" tabindex="0" role="button" data-k="${k}"><span class="t">${fmtTime(x.start)}</span><span class="why">${why}</span><span class="txt">${esc(x.text || "")}</span></div>`;
  }).join("") : `<div class="qc-empty">✓ ${t("qc_none")}</div>`;
  $$("#qc-list .qc-item").forEach((el) => (el.onclick = () => seek(w[+el.dataset.k].start, true)));
  // 字幕列表
  const list = $("#tab-cues");
  list.innerHTML = S.cues.map((c) => {
    const flag = c.flags.includes("low_confidence") || c.flags.includes("unaligned");
    return `<div class="cue-row${flag ? " flag" : ""}${c.edited ? " edited" : ""}" data-i="${c.i}">
      <span class="no">${c.i + 1}</span>
      <span class="time" title="▶" tabindex="0" role="button">${fmtTime(c.start)}<br>${fmtTime(c.end)}</span>
      <div>${c.speaker ? `<div class="spk">${esc(c.speaker)}</div>` : ""}<textarea rows="${c.value.split("\n").length}" spellcheck="false">${esc(c.value)}</textarea></div>
    </div>`;
  }).join("");
  $$("#tab-cues .cue-row").forEach((row) => {
    const c = S.cues[+row.dataset.i], ta = row.querySelector("textarea");
    row.querySelector(".time").onclick = () => seek(c.start, true);
    ta.onfocus = () => seek(c.start, false);
    ta.oninput = () => {
      c.value = ta.value;
      ta.rows = Math.max(1, ta.value.split("\n").length);
      c.edited = ta.value.replace(/\n/g, "") !== c.text;
      row.classList.toggle("edited", c.edited);
      updateEditCount(); drawOverlay();
    };
  });
  $("#script2").value = j.script || "";
  updateEditCount();
  drawOverlay();
}
function updateEditCount() {
  const n = S.cues.filter((c) => c.edited).length;
  $("#edit-count").textContent = n ? t("edits", { n }) : "";
}
function seek(time, play) {
  const v = $("#video");
  v.currentTime = Math.max(0, time - 0.05);
  if (play) v.play().catch(() => {});
  drawOverlay();
}
function displayHtml(line) {
  // 服务端渲染好的一行 [[文字, 振假名或 null], …] → HTML
  return line.map(([txt, rt]) => (rt ? `<ruby>${esc(txt)}<rt>${esc(rt)}</rt></ruby>` : esc(txt))).join("");
}
let activeIdx = -1;
function drawOverlay() {
  const time = $("#video").currentTime;
  const c = S.cues.find((x) => x.start <= time && time < x.end);
  const el = $("#overlay");
  if (!c) { el.innerHTML = ""; } else {
    const html = c.edited ? c.value.split("\n").map(esc) : c.display.map(displayHtml);
    el.innerHTML = `<span class="cue">${html.join("<br>")}</span>`;
  }
  const idx = c ? c.i : -1;
  if (idx !== activeIdx) {
    $$("#tab-cues .cue-row.active").forEach((r) => r.classList.remove("active"));
    if (c) {
      const row = $(`#tab-cues .cue-row[data-i="${idx}"]`);
      if (row) {
        row.classList.add("active");
        if (!row.contains(document.activeElement) && !$("#video").paused) row.scrollIntoView({ block: "nearest" });
      }
    }
    activeIdx = idx;
  }
}
function loop() { drawOverlay(); if (!$("#video").paused) requestAnimationFrame(loop); }

function editedPayload() {
  return S.cues.map((c) => ({ i: c.i, start: c.start, end: c.end, text: c.value.replace(/\n/g, ""), speaker: c.speaker }));
}
function currentOptions(extra = {}) {
  return { preset: S.job.options.preset, ...rubyFields($("#ruby2").value, $("#ruby-once2").checked), asr_model: S.job.options.asr_model, speakers: S.job.options.speakers, ...extra };
}
async function applyOptions(extra = {}) {
  // 重新断行。返回是否成功；请求进行中时字幕列表只读（免得请求回来把正在打的字冲掉）
  while (S.busy) await new Promise((r) => setTimeout(r, 100));
  S.busy = true;
  $("#tab-cues").classList.add("locked");
  $$("#tab-cues textarea").forEach((ta) => (ta.readOnly = true));
  try {
    const j = await api(`/api/jobs/${S.job.id}/reflow`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ cues: editedPayload(), options: currentOptions(extra) }) });
    S.job = j; renderResult(true); toast(t("reflowed"));
    return true;
  } catch (e) {
    toast(e.message, true);
    $$("#tab-cues textarea").forEach((ta) => (ta.readOnly = false));
    return false;
  } finally { S.busy = false; $("#tab-cues").classList.remove("locked"); }
}
async function realign(body) {
  try {
    const j = await api(`/api/jobs/${S.job.id}/realign`, { method: "POST", headers: { "content-type": "application/json" },
      body: JSON.stringify({ ...body, options: currentOptions() }) });
    follow(j);
  } catch (e) { toast(e.message, true); }
}
async function download(fmt) {
  if (fmt !== "txt" && S.cues.some((c) => c.edited) && !(await applyOptions())) return;   // 先把修改应用上
  const a = document.createElement("a");
  a.href = `/api/jobs/${S.job.id}/download/${fmt}`; a.download = "";
  document.body.appendChild(a); a.click(); a.remove();
}

async function cancelJob() {
  if (!S.job) return;
  $("#btn-cancel").disabled = true;
  try { renderProgress(await api(`/api/jobs/${S.job.id}/cancel`, { method: "POST" })); }
  catch (e) { toast(e.message, true); }
  finally { $("#btn-cancel").disabled = false; }
}

async function openJob(id) {
  try { follow(await api(`/api/jobs/${id}`)); }
  catch (e) { toast(e.message, true); location.hash = ""; show("new"); }
}

// ------------------------------------------------------------------ 词典
async function openDict() {
  $("#dict-text").value = await api("/api/dict");
  $("#dict-msg").textContent = "";
  $("#dict-dlg").showModal();
}

// ------------------------------------------------------------------ 初始化
function bind() {
  const drop = $("#drop");
  $("#media").onchange = () => pickFile($("#media").files[0]);
  drop.ondragover = (e) => { e.preventDefault(); drop.classList.add("over"); };
  drop.ondragleave = () => drop.classList.remove("over");
  drop.ondrop = (e) => { e.preventDefault(); drop.classList.remove("over"); pickFile(e.dataTransfer.files[0]); };
  document.addEventListener("dragover", (e) => e.preventDefault());
  document.addEventListener("drop", (e) => { e.preventDefault(); if (!$("#view-new").hidden && e.dataTransfer.files[0]) pickFile(e.dataTransfer.files[0]); });
  readTxt($("#script-file"), $("#script"));
  readTxt($("#script-file2"), $("#script2"));
  $("#btn-start").onclick = startJob;
  $("#btn-cancel").onclick = cancelJob;
  // 键盘：选文件的 label（隐藏的 <input type=file>）和 role=button 的 div / span 用 Enter / Space 触发
  $$("[data-pick]").forEach((el) => (el.onkeydown = (e) => {
    if (e.key === "Enter" || e.key === " ") { e.preventDefault(); $(el.dataset.pick).click(); }
  }));
  document.addEventListener("keydown", (e) => {
    const el = e.target;
    if ((e.key === "Enter" || e.key === " ") && el.getAttribute?.("role") === "button" && !el.dataset.pick
        && !["BUTTON", "A", "INPUT", "TEXTAREA", "SELECT"].includes(el.tagName)) { e.preventDefault(); el.click(); }
  });
  // 浏览器的后退 / 前进、手动改 #job=…：跟着换页面
  window.addEventListener("hashchange", () => {
    const m = location.hash.match(/job=([0-9a-f]{12})/);
    if (m) { if (m[1] !== S.job?.id || $("#view-new").hidden === false) openJob(m[1]); }
    else if ($("#view-new").hidden) { clearTimeout(S.poll); $("#video").pause(); show("new"); refreshConfig(); }
  });
  $("#btn-new").onclick = () => { clearTimeout(S.poll); location.hash = ""; $("#video").pause(); show("new"); refreshConfig(); };
  $("#btn-lang").onclick = () => { lang = lang === "ja" ? "en" : "ja"; localStorage.setItem("kugiri.lang", lang); applyI18n(); };
  $("#btn-dict").onclick = openDict;
  $("#btn-theme").onclick = () => {
    theme = THEMES[(THEMES.indexOf(theme) + 1) % THEMES.length];
    localStorage.setItem("kugiri.theme", theme);
    applyTheme();
  };
  $("#dict-save").onclick = async (e) => {
    e.preventDefault();
    try {
      const r = await api("/api/dict", { method: "PUT", body: $("#dict-text").value });
      $("#dict-msg").textContent = t("saved", { n: r.entries });
    } catch (err) { $("#dict-msg").textContent = err.message; }
  };
  let tryT;
  $("#dict-try").oninput = () => {
    clearTimeout(tryT);
    tryT = setTimeout(async () => {
      const q = $("#dict-try").value.trim();
      $("#dict-try-out").textContent = q ? (await api("/api/reading?text=" + encodeURIComponent(q))).reading : "";
    }, 250);
  };
  $("#btn-reflow").onclick = () => applyOptions();
  $("#btn-realign").onclick = () => realign({ cues: editedPayload() });
  $("#btn-realign-script").onclick = () => realign({ script: $("#script2").value });
  $("#ruby2").onchange = () => applyOptions();
  $("#ruby-once2").onchange = () => applyOptions();
  $$("[data-fmt]").forEach((a) => (a.onclick = (e) => { e.preventDefault(); download(a.dataset.fmt); }));
  $$(".tab").forEach((b) => (b.onclick = () => {
    $$(".tab").forEach((x) => x.classList.toggle("on", x === b));
    $("#tab-cues").hidden = b.dataset.tab !== "cues";
    $("#tab-script").hidden = b.dataset.tab !== "script";
  }));
  const v = $("#video");
  v.addEventListener("play", () => requestAnimationFrame(loop));
  v.addEventListener("timeupdate", drawOverlay);
  v.addEventListener("seeked", drawOverlay);
  v.addEventListener("loadedmetadata", () => {
    $("#player").classList.toggle("audio", !v.videoWidth);
    $("#player").classList.toggle("vertical", v.videoHeight > v.videoWidth);   // 竖屏视频：字按画面宽放大
  });
}

(async function init() {
  bind();
  S.config = await api("/api/config");
  applyI18n();
  setInterval(refreshConfig, 3000);
  const m = location.hash.match(/job=([0-9a-f]{12})/);
  if (m) openJob(m[1]); else show("new");
})();
