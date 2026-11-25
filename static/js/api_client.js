/**
 * バックエンドAPIクライアントモジュール (static/js/api_client.js)
 * FastAPI との通信（ヘルスチェック・設定永続化・アップロード・分離・文字起こし・保存・Temp管理）を統括する。
 */
(function (global) {
  let configSaveTimer = null;

  const PRESET_PROMPTS = {
    laughter_emotion: "あははは、ふふふ、ははは、えー、あのー、やだもう。",
    sigh_gasp_shout: "ふぅ…、はぁ…、ぐぬぬ…、あっ…、んっ…、きゃー！、うわぁ！、息遣い、ため息、叫び。",
    action_shouts: "えい！、やぁ！、とぅ！、うんしょ！、はっ！、よっ！、うおっ！、あっ！、せーの！",
    standard: "",
  };

  async function apiJson(url, options = {}) {
    const res = await fetch(url, options);
    const contentType = res.headers.get("content-type") || "";
    const payload = contentType.includes("application/json")
      ? await res.json()
      : { detail: await res.text() };

    if (!res.ok) {
      const msg = payload?.detail || `HTTPエラー (${res.status})`;
      throw new Error(msg);
    }
    return payload;
  }

  function applyConfigToUi(cfg) {
    if (!cfg) return;
    const outputDir = document.getElementById("outputDir");
    const prefixPattern = document.getElementById("prefixPattern");
    const wavTarget = document.getElementById("wavTarget");
    const modelSelect = document.getElementById("modelSelect");
    const strengthSlider = document.getElementById("strengthSlider");
    const strengthValue = document.getElementById("strengthValue");
    const langSelect = document.getElementById("langSelect");
    const timestampCheck = document.getElementById("timestampCheck");
    const disableVadCheck = document.getElementById("disableVadCheck");
    const promptPresetSelect = document.getElementById("promptPresetSelect");
    const customPromptInput = document.getElementById("customPromptInput");
    const sliderVolA = document.getElementById("sliderVolA");
    const valA = document.getElementById("volA");
    const sliderVolB = document.getElementById("sliderVolB");
    const valB = document.getElementById("volB");

    if (outputDir && cfg.output_dir) outputDir.value = cfg.output_dir;
    if (prefixPattern && cfg.filename_pattern) prefixPattern.value = cfg.filename_pattern;
    if (wavTarget && cfg.wav_target) wavTarget.value = cfg.wav_target;
    if (modelSelect && cfg.model_name) modelSelect.value = cfg.model_name;
    if (strengthSlider && cfg.strength !== undefined) {
      strengthSlider.value = String(cfg.strength);
      if (strengthValue) strengthValue.textContent = `${cfg.strength}%`;
    }
    if (sliderVolA && cfg.slider_vol_a !== undefined) {
      sliderVolA.value = String(cfg.slider_vol_a);
      if (valA) valA.textContent = `${cfg.slider_vol_a}%`;
    }
    if (sliderVolB && cfg.slider_vol_b !== undefined) {
      sliderVolB.value = String(cfg.slider_vol_b);
      if (valB) valB.textContent = `${cfg.slider_vol_b}%`;
    }
    if (langSelect && cfg.language) langSelect.value = cfg.language;
    if (timestampCheck && cfg.use_timestamps !== undefined) {
      timestampCheck.checked = Boolean(cfg.use_timestamps);
    }
    if (disableVadCheck && cfg.disable_vad !== undefined) {
      disableVadCheck.checked = Boolean(cfg.disable_vad);
    }
    if (promptPresetSelect && cfg.prompt_preset) {
      promptPresetSelect.value = cfg.prompt_preset;
    }
    if (customPromptInput && cfg.custom_prompt !== undefined) {
      customPromptInput.value = cfg.custom_prompt;
    }
    if (cfg.process_mode) {
      const radio = document.querySelector(`input[name="processMode"][value="${cfg.process_mode}"]`);
      if (radio) radio.checked = true;
    }
    if (global.AudioVideoSync && global.AudioVideoSync.setMuteStates) {
      global.AudioVideoSync.setMuteStates(Boolean(cfg.mute_a), Boolean(cfg.mute_b));
    }
    global.AppState.updatePathPreview();
  }

  function collectConfigValues() {
    const outputDir = document.getElementById("outputDir");
    const prefixPattern = document.getElementById("prefixPattern");
    const wavTarget = document.getElementById("wavTarget");
    const modelSelect = document.getElementById("modelSelect");
    const strengthSlider = document.getElementById("strengthSlider");
    const langSelect = document.getElementById("langSelect");
    const timestampCheck = document.getElementById("timestampCheck");
    const disableVadCheck = document.getElementById("disableVadCheck");
    const promptPresetSelect = document.getElementById("promptPresetSelect");
    const customPromptInput = document.getElementById("customPromptInput");
    const sliderVolA = document.getElementById("sliderVolA");
    const sliderVolB = document.getElementById("sliderVolB");
    const mixer =
      global.AudioVideoSync && global.AudioVideoSync.getExportParams
        ? global.AudioVideoSync.getExportParams()
        : {};

    const presetVal = promptPresetSelect ? promptPresetSelect.value : "standard";
    return {
      output_dir: outputDir ? outputDir.value.trim() : "outputs",
      filename_pattern: prefixPattern ? prefixPattern.value.trim() : "%date%\\%time%_%filename%",
      process_mode: global.AppState.getSelectedMode(),
      model_name: modelSelect ? modelSelect.value : "uvr_mdx_net_inst_hq_5",
      strength: strengthSlider ? Number(strengthSlider.value) : 85,
      wav_target: wavTarget ? wavTarget.value : "vocal",
      slider_vol_a: sliderVolA ? Number(sliderVolA.value) : 100,
      slider_vol_b: sliderVolB ? Number(sliderVolB.value) : 100,
      mute_a: Boolean(mixer.mute_a),
      mute_b: Boolean(mixer.mute_b),
      language: langSelect ? langSelect.value : "ja",
      use_timestamps: timestampCheck ? Boolean(timestampCheck.checked) : true,
      disable_vad: disableVadCheck ? Boolean(disableVadCheck.checked) : false,
      include_laughs: presetVal !== "standard",
      prompt_preset: presetVal,
      custom_prompt: customPromptInput ? customPromptInput.value.trim() : "",
    };
  }

  function scheduleConfigSave() {
    clearTimeout(configSaveTimer);
    configSaveTimer = setTimeout(async () => {
      try {
        await apiJson("/api/config", {
          method: "POST",
          headers: { "Content-Type": "application/json" },
          body: JSON.stringify({ values: collectConfigValues() }),
        });
      } catch (_) {
        // ignore background config save error
      }
    }, 500);
  }

  async function initHealth() {
    try {
      const health = await apiJson("/api/health");
      global.AppState.state.gpuLabel = health.cuda_available
        ? `CUDA (${health.gpu_name})`
        : "CPU Mode";
      global.AppState.state.ffmpegOk = Boolean(health.ffmpeg_available);
      applyConfigToUi(health.config);
      global.AppState.updateTempStatus(health.temp_status);
      global.AppState.renderHeaderStatus();
      global.AppState.refreshButtons();
    } catch (err) {
      global.AppState.state.gpuLabel = "接続エラー";
      global.AppState.renderHeaderStatus();
      global.AppState.showToast(`サーバー初期化エラー: ${err.message}`, true);
    }
  }

  async function uploadFile(file) {
    if (!file) return;
    const dropzone = document.getElementById("dropzone");
    if (dropzone) dropzone.classList.add("uploading");

    global.AudioVideoSync.stopOriginalPlayer();
    global.AudioVideoSync.stopSyncedPlay(true);
    global.AppState.clearExportResult();
    global.AppState.setBusy(true, `ファイルを解析中 (${file.name})...`);

    const formData = new FormData();
    formData.append("file", file);

    try {
      const res = await apiJson("/api/upload", {
        method: "POST",
        body: formData,
      });

      const st = global.AppState.state;
      st.sessionId = res.session_id;
      st.originalFilename = res.original_filename;
      st.baseName = res.original_filename.replace(/\.[^/.]+$/, "");
      st.hasVideo = Boolean(res.has_video);
      st.duration = Number(res.duration) || 0;
      st.separated = false;
      st.transcribed = false;
      st.plainText = "";
      st.timestampText = "";
      st.srtText = "";
      st.transcriptEdited = false;

      const area = document.getElementById("transcriptArea");
      if (area) area.value = "";

      const nameEl = document.getElementById("selectedFileName");
      const metaEl = document.getElementById("selectedFileMeta");
      if (nameEl) nameEl.textContent = res.original_filename;
      if (metaEl) {
        const durStr = global.AppState.formatDuration(res.duration);
        const videoTxt = res.has_video ? `映像 ${res.video_codec || "video"}` : "映像なし";
        metaEl.textContent = `長さ ${durStr} / ${res.file_size_mb} MB / 音声 ${res.audio_sr || "-"}Hz / ${videoTxt}`;
      }

      global.AudioVideoSync.loadOriginalMedia(
        res.original_audio_url,
        res.video_preview_url,
        res.duration
      );
      global.AppState.updatePathPreview();
      global.AppState.updateTempStatus(res.temp_status);
      global.AppState.showToast(`読み込み完了: ${res.original_filename}（「音声分離・ノイズ除去を実行」を押してください）`);
    } catch (err) {
      global.AppState.showToast(`ファイル読み込み失敗: ${err.message}`, true);
    } finally {
      if (dropzone) dropzone.classList.remove("uploading");
      global.AppState.setBusy(false);
    }
  }

  function formatElapsed(sec) {
    const s = Math.floor(sec || 0);
    const m = Math.floor(s / 60);
    const r = s % 60;
    return `経過時間: ${String(m).padStart(2, "0")}:${String(r).padStart(2, "0")}`;
  }

  function openProgressModal(title, icon = "⚡") {
    const overlay = document.getElementById("progressModalOverlay");
    const titleEl = document.getElementById("progressModalTitle");
    const iconEl = document.getElementById("progressModalIcon");
    const fillEl = document.getElementById("progressBarFill");
    const stageEl = document.getElementById("progressStageText");
    const pctEl = document.getElementById("progressPercentText");
    const elapsedEl = document.getElementById("progressElapsedText");

    if (titleEl) titleEl.textContent = title;
    if (iconEl) iconEl.textContent = icon;
    if (fillEl) fillEl.style.width = "0%";
    if (stageEl) stageEl.textContent = "準備中...";
    if (pctEl) pctEl.textContent = "0%";
    if (elapsedEl) elapsedEl.textContent = "経過時間: 00:00";

    if (overlay) {
      overlay.style.display = "flex";
      void overlay.offsetWidth;
      overlay.classList.add("active");
    }
  }

  function updateProgressModal(percent, stage, elapsedSec) {
    const fillEl = document.getElementById("progressBarFill");
    const stageEl = document.getElementById("progressStageText");
    const pctEl = document.getElementById("progressPercentText");
    const elapsedEl = document.getElementById("progressElapsedText");

    const pct = Math.max(0, Math.min(100, Math.round(percent || 0)));
    if (fillEl) fillEl.style.width = `${pct}%`;
    if (stageEl && stage) stageEl.textContent = stage;
    if (pctEl) pctEl.textContent = `${pct}%`;
    if (elapsedEl) elapsedEl.textContent = formatElapsed(elapsedSec);
  }

  function closeProgressModal() {
    const overlay = document.getElementById("progressModalOverlay");
    if (overlay) {
      overlay.classList.remove("active");
      setTimeout(() => {
        if (!overlay.classList.contains("active")) {
          overlay.style.display = "none";
        }
      }, 250);
    }
  }

  async function pollJob(jobId, title, icon = "⚡") {
    openProgressModal(title, icon);
    try {
      while (true) {
        const res = await apiJson(`/api/job/${jobId}`);
        updateProgressModal(res.percent, res.stage, res.elapsed_sec);

        if (res.status === "completed") {
          updateProgressModal(100, "完了", res.elapsed_sec);
          await new Promise((r) => setTimeout(r, 300));
          return res.result;
        }
        if (res.status === "failed") {
          throw new Error(res.error || "処理に失敗しました");
        }
        await new Promise((r) => setTimeout(r, 300));
      }
    } finally {
      closeProgressModal();
    }
  }

  async function runSeparate() {
    const st = global.AppState.state;
    if (!st.sessionId) {
      global.AppState.showToast("先に動画または音声ファイルを選択してください。", true);
      return;
    }

    const mode = global.AppState.getSelectedMode();
    const modelEl = document.getElementById("modelSelect");
    const strengthEl = document.getElementById("strengthSlider");

    global.AudioVideoSync.stopOriginalPlayer();
    global.AudioVideoSync.stopSyncedPlay(true);
    global.AppState.setBusy(true, "AI音声分離・ノイズ除去を実行中...");

    try {
      const startRes = await apiJson("/api/separate/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: st.sessionId,
          mode,
          model_name: modelEl ? modelEl.value : "uvr_mdx_net_inst_hq_5",
          strength: strengthEl ? Number(strengthEl.value) : 85,
        }),
      });

      const res = await pollJob(startRes.job_id, "🎙️ 音声分離・ノイズ除去を実行中...", "🎙️");

      st.separated = true;
      global.AudioVideoSync.loadSeparatedTracks(
        res.track_a_url,
        res.track_b_url,
        res.peaks_a,
        res.peaks_b,
        res.duration
      );
      global.AppState.updateTempStatus(res.temp_status);
      global.AppState.showToast(`音声分離が完了しました（推論: ${res.device_used}）`);
    } catch (err) {
      global.AppState.showToast(`音声分離エラー: ${err.message}`, true);
    } finally {
      global.AppState.setBusy(false);
    }
  }

  async function runTranscribe() {
    const st = global.AppState.state;
    if (!st.sessionId || !st.separated) {
      global.AppState.showToast("先に音声分離を実行してください。", true);
      return;
    }

    const langEl = document.getElementById("langSelect");
    const tsEl = document.getElementById("timestampCheck");
    const disableVadEl = document.getElementById("disableVadCheck");
    const presetEl = document.getElementById("promptPresetSelect");
    const customPromptEl = document.getElementById("customPromptInput");
    const area = document.getElementById("transcriptArea");

    global.AppState.setBusy(true, "トラックAから文字起こしを実行中...");
    try {
      const presetVal = presetEl ? presetEl.value : "standard";
      const startRes = await apiJson("/api/transcribe/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          session_id: st.sessionId,
          language: langEl ? langEl.value : "ja",
          use_timestamps: tsEl ? Boolean(tsEl.checked) : true,
          disable_vad: disableVadEl ? Boolean(disableVadEl.checked) : false,
          include_laughs: presetVal !== "standard",
          prompt_preset: presetVal,
          custom_prompt: customPromptEl ? customPromptEl.value.trim() : "",
        }),
      });

      const res = await pollJob(startRes.job_id, "📝 文字起こし推論を実行中...", "📝");

      st.transcribed = true;
      st.plainText = res.plain_text || "";
      st.timestampText = res.timestamp_text || "";
      st.srtText = res.srt_text || "";
      st.transcriptEdited = false;

      if (area) {
        area.value = res.text || "";
      }
      global.AppState.showToast(`文字起こし完了（${res.engine} / 言語: ${res.language}）`);
    } catch (err) {
      global.AppState.showToast(`文字起こしエラー: ${err.message}`, true);
    } finally {
      global.AppState.setBusy(false);
    }
  }

  function buildExportPayload() {
    const st = global.AppState.state;
    const outputDir = document.getElementById("outputDir");
    const prefixPattern = document.getElementById("prefixPattern");
    const wavTarget = document.getElementById("wavTarget");
    const mixer = global.AudioVideoSync.getExportParams();

    return {
      session_id: st.sessionId,
      output_dir: outputDir ? outputDir.value.trim() : "outputs",
      filename_pattern: prefixPattern ? prefixPattern.value.trim() : "%date%\\%time%_%filename%",
      wav_target: wavTarget ? wavTarget.value : "vocal",
      vol_a_pct: mixer.vol_a_pct,
      vol_b_pct: mixer.vol_b_pct,
      mute_a: mixer.mute_a,
      mute_b: mixer.mute_b,
      solo_a: mixer.solo_a,
      solo_b: mixer.solo_b,
    };
  }

  async function runExport(endpoint, label, overrideWavTarget = null) {
    const st = global.AppState.state;
    if (!st.sessionId || !st.separated) return;

    global.AppState.setBusy(true, `${label} を書き出し中...`);
    try {
      let payload;
      if (endpoint === "/api/export/transcript") {
        const outputDir = document.getElementById("outputDir");
        const prefixPattern = document.getElementById("prefixPattern");
        const area = document.getElementById("transcriptArea");
        payload = {
          session_id: st.sessionId,
          output_dir: outputDir ? outputDir.value.trim() : "outputs",
          filename_pattern: prefixPattern ? prefixPattern.value.trim() : "%date%\\%time%_%filename%",
          text_content: area ? area.value : "",
          srt_content: st.srtText || "",
        };
      } else {
        payload = buildExportPayload();
        if (overrideWavTarget) {
          payload.wav_target = overrideWavTarget;
        }
      }

      const res = await apiJson(endpoint, {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const paths = res.saved_paths || [];
      global.AppState.showExportResult(paths);
      global.AppState.showToast(`${label} を保存しました（${paths.length}件）`);
    } catch (err) {
      global.AppState.showToast(`${label} エラー: ${err.message}`, true);
    } finally {
      global.AppState.setBusy(false);
    }
  }

  async function runExportAll() {
    const st = global.AppState.state;
    if (!st.sessionId || !st.separated) return;

    const outputDir = document.getElementById("outputDir");
    const prefixPattern = document.getElementById("prefixPattern");
    const area = document.getElementById("transcriptArea");
    const mixer = global.AudioVideoSync.getExportParams();

    global.AppState.setBusy(true, "全ファイルを一括書き出し中...");
    try {
      const payload = {
        session_id: st.sessionId,
        output_dir: outputDir ? outputDir.value.trim() : "outputs",
        filename_pattern: prefixPattern ? prefixPattern.value.trim() : "%date%\\%time%_%filename%",
        vol_a_pct: mixer.vol_a_pct,
        vol_b_pct: mixer.vol_b_pct,
        mute_a: mixer.mute_a,
        mute_b: mixer.mute_b,
        solo_a: mixer.solo_a,
        solo_b: mixer.solo_b,
        text_content: (st.transcribed && area) ? area.value : "",
        srt_content: st.transcribed ? (st.srtText || "") : "",
      };

      const res = await apiJson("/api/export/all", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });

      const paths = res.saved_paths || [];
      global.AppState.showExportResult(paths);
      global.AppState.showToast(`全ファイルを一括保存しました（計 ${paths.length} 件）`);
    } catch (err) {
      global.AppState.showToast(`一括保存エラー: ${err.message}`, true);
    } finally {
      global.AppState.setBusy(false);
    }
  }

  async function openOutputDir(targetPath = null) {
    const input = document.getElementById("outputDir");
    const outDir = input ? input.value.trim() : "outputs";
    try {
      const res = await apiJson("/api/export/open", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          output_dir: outDir,
          target_path: targetPath || global.AppState.state.lastExportedPath || null,
        }),
      });
      if (res.opened) {
        global.AppState.showToast(`保存先フォルダを開きました: ${res.path}`);
      }
    } catch (err) {
      global.AppState.showToast(`フォルダ表示エラー: ${err.message}`, true);
    }
  }

  async function clearTemp() {
    const st = global.AppState.state;
    const qs = st.sessionId ? `?session_id=${encodeURIComponent(st.sessionId)}` : "";
    try {
      const res = await apiJson(`/api/temp/clear${qs}`, { method: "POST" });
      global.AppState.updateTempStatus(res);
      global.AppState.showToast(`過去のTempファイルを ${res.deleted_count} 件削除しました。`);
    } catch (err) {
      global.AppState.showToast(`Temp削除エラー: ${err.message}`, true);
    }
  }

  async function openTempFolder() {
    try {
      const res = await apiJson("/api/temp/open", { method: "POST" });
      if (!res.opened) {
        global.AppState.showToast("フォルダを開けませんでした。", true);
      }
    } catch (err) {
      global.AppState.showToast(`フォルダ表示エラー: ${err.message}`, true);
    }
  }

  async function browseOutputDir() {
    const input = document.getElementById("outputDir");
    const cur = input ? input.value.trim() : "";
    try {
      const res = await apiJson("/api/config/select-dir", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ current_dir: cur }),
      });
      if (res.selected_dir && input) {
        input.value = res.selected_dir;
        global.AppState.updatePathPreview();
        scheduleConfigSave();
      }
    } catch (err) {
      global.AppState.showToast(`フォルダ選択エラー: ${err.message}`, true);
    }
  }

  function bindUiEvents() {
    const dropzone = document.getElementById("dropzone");
    const fileInput = document.getElementById("fileInput");

    if (dropzone && fileInput) {
      dropzone.addEventListener("click", () => fileInput.click());
      dropzone.addEventListener("dragover", (e) => {
        e.preventDefault();
        dropzone.classList.add("dragover");
      });
      dropzone.addEventListener("dragleave", () => dropzone.classList.remove("dragover"));
      dropzone.addEventListener("drop", (e) => {
        e.preventDefault();
        dropzone.classList.remove("dragover");
        if (e.dataTransfer.files.length > 0) {
          uploadFile(e.dataTransfer.files[0]);
        }
      });
      fileInput.addEventListener("change", (e) => {
        if (e.target.files.length > 0) {
          uploadFile(e.target.files[0]);
          fileInput.value = "";
        }
      });
    }

    const strengthSlider = document.getElementById("strengthSlider");
    const strengthValue = document.getElementById("strengthValue");
    if (strengthSlider) {
      strengthSlider.addEventListener("input", () => {
        if (strengthValue) strengthValue.textContent = `${strengthSlider.value}%`;
        scheduleConfigSave();
      });
    }

    document.querySelectorAll('input[name="processMode"]').forEach((r) => {
      r.addEventListener("change", () => {
        global.AppState.updatePathPreview();
        scheduleConfigSave();
      });
    });

    ["modelSelect", "wavTarget", "langSelect"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("change", () => {
          global.AppState.updatePathPreview();
          scheduleConfigSave();
        });
      }
    });

    ["outputDir", "prefixPattern"].forEach((id) => {
      const el = document.getElementById(id);
      if (el) {
        el.addEventListener("input", () => {
          global.AppState.updatePathPreview();
          scheduleConfigSave();
        });
      }
    });

    const timestampCheck = document.getElementById("timestampCheck");
    const disableVadCheck = document.getElementById("disableVadCheck");
    const promptPresetSelect = document.getElementById("promptPresetSelect");
    const customPromptBox = document.getElementById("customPromptBox");
    const customPromptInput = document.getElementById("customPromptInput");
    const transcriptArea = document.getElementById("transcriptArea");

    if (timestampCheck) {
      timestampCheck.addEventListener("change", () => {
        const st = global.AppState.state;
        if (st.transcribed && !st.transcriptEdited && transcriptArea) {
          transcriptArea.value = timestampCheck.checked ? st.timestampText : st.plainText;
        }
        scheduleConfigSave();
      });
    }

    if (disableVadCheck) {
      disableVadCheck.addEventListener("change", () => {
        scheduleConfigSave();
      });
    }

    if (promptPresetSelect) {
      promptPresetSelect.addEventListener("change", () => {
        const val = promptPresetSelect.value;
        if (PRESET_PROMPTS[val] !== undefined && customPromptInput) {
          customPromptInput.value = PRESET_PROMPTS[val];
        }
        if (disableVadCheck) {
          if (val === "action_shouts") {
            disableVadCheck.checked = true;
          } else if (val === "standard") {
            disableVadCheck.checked = false;
          }
        }
        scheduleConfigSave();
      });
    }

    if (customPromptInput) {
      customPromptInput.addEventListener("input", () => {
        if (promptPresetSelect) {
          promptPresetSelect.value = "custom";
        }
        scheduleConfigSave();
      });
    }

    if (global.AudioVideoSync && global.AudioVideoSync.setOnMixerChange) {
      global.AudioVideoSync.setOnMixerChange(() => {
        scheduleConfigSave();
      });
    }

    const btnResetDefaults = document.getElementById("btnResetDefaults");
    if (btnResetDefaults) {
      btnResetDefaults.addEventListener("click", async () => {
        const ok = window.confirm("すべての設定（保存先、命名規則、音量バランス、プロンプト等）を出荷時の推奨初期状態に戻しますか？");
        if (!ok) return;
        try {
          const res = await apiJson("/api/config/reset", { method: "POST" });
          if (res && res.saved) {
            applyConfigToUi(res.saved);
            global.AppState.showToast("全設定を出荷時初期値にリセットしました");
          }
        } catch (err) {
          global.AppState.showToast(`リセット失敗: ${err.message}`, true);
        }
      });
    }

    if (transcriptArea) {
      transcriptArea.addEventListener("input", () => {
        global.AppState.state.transcriptEdited = true;
        global.AppState.refreshButtons();
      });
    }

    document.querySelectorAll(".var-chip[data-var]").forEach((chip) => {
      chip.addEventListener("click", () => {
        global.AppState.insertVar(chip.dataset.var || "");
      });
    });

    const btnSeparate = document.getElementById("btnSeparate");
    if (btnSeparate) btnSeparate.addEventListener("click", runSeparate);

    const btnTranscribe = document.getElementById("btnTranscribe");
    if (btnTranscribe) btnTranscribe.addEventListener("click", runTranscribe);

    const btnCopy = document.getElementById("btnCopyTranscript");
    if (btnCopy && transcriptArea) {
      btnCopy.addEventListener("click", async () => {
        if (!transcriptArea.value.trim()) return;
        try {
          await navigator.clipboard.writeText(transcriptArea.value);
          global.AppState.showToast("テキストをクリップボードにコピーしました。");
        } catch (_) {
          transcriptArea.select();
          document.execCommand("copy");
          global.AppState.showToast("テキストをコピーしました。");
        }
      });
    }

    const btnSaveAll = document.getElementById("btnSaveAll");
    if (btnSaveAll) {
      btnSaveAll.addEventListener("click", runExportAll);
    }

    const btnTrackA = document.getElementById("btnSaveTrackA") || document.getElementById("btnSaveWav");
    if (btnTrackA) {
      btnTrackA.addEventListener("click", () => runExport("/api/export/wav", "トラックA音声 (WAV)", "vocal"));
    }

    const btnTrackB = document.getElementById("btnSaveTrackB");
    if (btnTrackB) {
      btnTrackB.addEventListener("click", () => runExport("/api/export/wav", "トラックB音声 (WAV)", "bgm"));
    }

    const btnRepMp4 = document.getElementById("btnSaveReplacedMp4");
    if (btnRepMp4) {
      btnRepMp4.addEventListener("click", () => runExport("/api/export/video-replaced", "音声差し替え動画 (MP4)"));
    }

    const btnVidOnly = document.getElementById("btnSaveVideoOnlyMp4");
    if (btnVidOnly) {
      btnVidOnly.addEventListener("click", () => runExport("/api/export/video-only", "映像のみ動画 (MP4)"));
    }

    const btnTxt = document.getElementById("btnSaveTxt");
    if (btnTxt) {
      btnTxt.addEventListener("click", () => runExport("/api/export/transcript", "文字起こしテキスト (TXT / SRT)"));
    }

    const btnClearTemp = document.getElementById("btnClearTemp");
    if (btnClearTemp) btnClearTemp.addEventListener("click", clearTemp);

    const btnOpenTemp = document.getElementById("btnOpenTemp");
    if (btnOpenTemp) btnOpenTemp.addEventListener("click", openTempFolder);

    const btnBrowseDir = document.getElementById("btnBrowseDir");
    if (btnBrowseDir) btnBrowseDir.addEventListener("click", browseOutputDir);

    const btnOpenOutputDir = document.getElementById("btnOpenOutputDir");
    if (btnOpenOutputDir) btnOpenOutputDir.addEventListener("click", () => openOutputDir());

    const btnOpenSavedFolder = document.getElementById("btnOpenSavedFolder");
    if (btnOpenSavedFolder) {
      btnOpenSavedFolder.addEventListener("click", () => openOutputDir(global.AppState.state.lastExportedPath));
    }
  }

  document.addEventListener("DOMContentLoaded", () => {
    global.AppTheme.initTheme();
    global.AudioVideoSync.bindEvents();
    bindUiEvents();
    global.AppState.refreshButtons();
    global.AppState.updatePathPreview();
    initHealth();
  });
})(window);