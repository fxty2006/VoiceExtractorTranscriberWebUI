/**
 * UI状態管理モジュール (static/js/ui_state.js)
 * ボタンの暗転（disabled）状態遷移、パスプリフィックスプレビュー、Temp状態表示、トースト通知を一元管理する。
 */
(function (global) {
  const state = {
    sessionId: null,
    originalFilename: "",
    baseName: "sample_video",
    hasVideo: false,
    duration: 0,
    separated: false,
    transcribed: false,
    busy: false,
    busyText: "",
    gpuLabel: "確認中...",
    ffmpegOk: true,
    plainText: "",
    timestampText: "",
    srtText: "",
    transcriptEdited: false,
  };

  let toastTimer = null;

  function showToast(msg, isError = false) {
    const el = document.getElementById("toast");
    if (!el) return;
    el.textContent = msg;
    el.classList.toggle("error", Boolean(isError));
    el.classList.add("show");
    clearTimeout(toastTimer);
    toastTimer = setTimeout(() => el.classList.remove("show"), 3400);
  }

  function formatDuration(sec) {
    const total = Math.max(0, Math.floor(Number(sec) || 0));
    const m = String(Math.floor(total / 60)).padStart(2, "0");
    const s = String(total % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  function sanitizeFilenamePart(name) {
    return String(name || "")
      .replace(/[<>:"/\\|?*\x00-\x1f]/g, "_")
      .replace(/^[ .]+|[ .]+$/g, "")
      .replace(/__+/g, "_");
  }

  function getSelectedMode() {
    const radio = document.querySelector('input[name="processMode"]:checked');
    return radio ? radio.value : "vocal_extract";
  }

  function setBusy(busy, message = "") {
    state.busy = Boolean(busy);
    state.busyText = message;
    renderHeaderStatus();
    refreshButtons();
  }

  function renderHeaderStatus() {
    const badge = document.getElementById("systemStatusBadge");
    const badgeText = document.getElementById("systemStatusText");
    const gpuMeta = document.getElementById("gpuDeviceMeta");
    if (gpuMeta) {
      gpuMeta.textContent = `推論エンジン: ${state.gpuLabel}`;
    }
    if (!badge || !badgeText) return;

    badge.classList.remove("busy", "warn", "err");
    if (state.busy) {
      badge.classList.add("busy");
      badgeText.textContent = state.busyText || "処理実行中...";
    } else if (!state.ffmpegOk) {
      badge.classList.add("err");
      badgeText.textContent = "ffmpeg未検出（PATHを確認してください）";
    } else {
      badgeText.textContent = `稼働中 (${state.gpuLabel})`;
    }
  }

  function updateVideoPanelVisibility() {
    const inputTypeBadge = document.getElementById("inputTypeBadge");
    const videoStage = document.getElementById("videoStage");
    const videoPlayer = document.getElementById("syncVideoPlayer");
    const videoPlaceholder = document.getElementById("videoPlaceholder");
    const videoNotice = document.getElementById("videoAudioOnlyNotice");
    const syncLabel = document.getElementById("syncTrackLabel");
    const videoFileHud = document.getElementById("videoFileHud");

    if (!state.sessionId) {
      if (inputTypeBadge) inputTypeBadge.textContent = "ファイル待機中";
      if (videoStage) videoStage.style.display = "flex";
      if (videoPlayer) videoPlayer.style.display = "none";
      if (videoPlaceholder) videoPlaceholder.style.display = "block";
      if (videoNotice) videoNotice.style.display = "none";
      if (syncLabel) syncLabel.textContent = "🔗 ファイル読み込み待ち";
      if (videoFileHud) videoFileHud.textContent = "ファイル未読込";
      return;
    }

    if (videoFileHud) {
      videoFileHud.textContent = state.hasVideo
        ? `${state.originalFilename} (映像無音・下のトラック音声と同期)`
        : `${state.originalFilename} (音声ファイル)`;
    }

    if (!state.hasVideo) {
      if (inputTypeBadge) inputTypeBadge.textContent = "音声のみモード";
      if (videoStage) videoStage.style.display = "none";
      if (videoPlayer) videoPlayer.style.display = "none";
      if (videoNotice) videoNotice.style.display = "block";
      if (syncLabel) syncLabel.textContent = "音声のみ入力";
    } else {
      if (inputTypeBadge) inputTypeBadge.textContent = "動画モード";
      if (videoStage) videoStage.style.display = "flex";
      if (videoNotice) videoNotice.style.display = "none";
      if (videoPlayer && videoPlayer.getAttribute("src")) {
        videoPlayer.style.display = "block";
        if (videoPlaceholder) videoPlaceholder.style.display = "none";
      } else {
        if (videoPlayer) videoPlayer.style.display = "none";
        if (videoPlaceholder) videoPlaceholder.style.display = "block";
      }
      if (syncLabel) {
        syncLabel.textContent = state.separated
          ? "🔗 音声再生・シーク連動 ON"
          : "🔗 音声再生・シーク連動（分離待ち）";
      }
    }
  }

  function refreshButtons() {
    const hasFile = Boolean(state.sessionId);
    const separated = Boolean(state.separated);
    const hasVideo = Boolean(state.hasVideo);
    const transcriptArea = document.getElementById("transcriptArea");
    const hasText = Boolean(transcriptArea && transcriptArea.value.trim());
    const textReady = separated && (state.transcribed || hasText);
    const locked = state.busy;

    const btnSeparate = document.getElementById("btnSeparate");
    if (btnSeparate) {
      btnSeparate.disabled = locked || !hasFile;
    }

    const previewBadge = document.getElementById("previewStatusBadge");
    const unprocessedNote = document.getElementById("unprocessedPreviewNote");
    if (previewBadge && unprocessedNote) {
      if (!hasFile) {
        previewBadge.textContent = "未分離（ファイル読込待ち）";
        previewBadge.classList.remove("ready");
        unprocessedNote.style.display = "block";
      } else if (!separated) {
        previewBadge.textContent = "未分離（分離実行待ち）";
        previewBadge.classList.remove("ready");
        unprocessedNote.style.display = "block";
      } else if (!hasVideo) {
        previewBadge.textContent = state.transcribed
          ? "一時プレビュー中（音声のみ・文字起こし完了）"
          : "一時プレビュー中（音声のみ入力）";
        previewBadge.classList.add("ready");
        unprocessedNote.style.display = "none";
      } else {
        previewBadge.textContent = state.transcribed
          ? "一時プレビュー中（文字起こし完了）"
          : "一時プレビュー中（保存ボタン押下時のみ本保存）";
        previewBadge.classList.add("ready");
        unprocessedNote.style.display = "none";
      }
    }

    const btnTranscribe = document.getElementById("btnTranscribe");
    const noteTranscribe = document.getElementById("noteTranscribe");
    const btnCopy = document.getElementById("btnCopyTranscript");
    const btnSaveAll = document.getElementById("btnSaveAll");
    const subSaveAll = document.getElementById("subSaveAll");
    const btnTrackA = document.getElementById("btnSaveTrackA") || document.getElementById("btnSaveWav");
    const subTrackA = document.getElementById("subSaveTrackA") || document.getElementById("subSaveWav");
    const btnTrackB = document.getElementById("btnSaveTrackB");
    const subTrackB = document.getElementById("subSaveTrackB");
    const btnRepMp4 = document.getElementById("btnSaveReplacedMp4");
    const subRepMp4 = document.getElementById("subSaveReplacedMp4");
    const btnVidOnly = document.getElementById("btnSaveVideoOnlyMp4");
    const subVidOnly = document.getElementById("subSaveVideoOnlyMp4");
    const btnTxt = document.getElementById("btnSaveTxt");
    const subTxt = document.getElementById("subSaveTxt");

    if (!separated) {
      if (btnTranscribe) btnTranscribe.disabled = true;
      if (noteTranscribe) {
        noteTranscribe.style.display = "inline-block";
        noteTranscribe.textContent = "🔒 音声分離が未実行のため無効";
      }
      if (btnCopy) btnCopy.disabled = !hasText;

      if (btnSaveAll) btnSaveAll.disabled = true;
      if (subSaveAll) subSaveAll.textContent = "🔒 音声分離が未処理のため暗転（無効）";

      if (btnTrackA) btnTrackA.disabled = true;
      if (subTrackA) subTrackA.textContent = "🔒 音声分離が未処理のため暗転（無効）";

      if (btnTrackB) btnTrackB.disabled = true;
      if (subTrackB) subTrackB.textContent = "🔒 音声分離が未処理のため暗転（無効）";

      if (btnRepMp4) btnRepMp4.disabled = true;
      if (subRepMp4) subRepMp4.textContent = "🔒 音声分離が未処理のため暗転（無効）";

      if (btnVidOnly) btnVidOnly.disabled = true;
      if (subVidOnly) subVidOnly.textContent = "🔒 動画処理待ちのため暗転（無効）";

      if (btnTxt) btnTxt.disabled = true;
      if (subTxt) subTxt.textContent = "🔒 文字起こし未実行のため暗転（無効）";
    } else {
      if (btnTranscribe) btnTranscribe.disabled = locked;
      if (noteTranscribe) noteTranscribe.style.display = "none";
      if (btnCopy) btnCopy.disabled = !hasText;

      if (btnSaveAll) {
        btnSaveAll.disabled = locked;
        if (hasVideo && textReady && hasText) {
          if (subSaveAll) subSaveAll.textContent = "✨ 音声（A/B）・動画差し替え・映像のみ・字幕テキストを一括書き出し";
        } else if (hasVideo) {
          if (subSaveAll) subSaveAll.textContent = "✨ 音声（A/B）・動画差し替え・映像のみを一括書き出し";
        } else if (textReady && hasText) {
          if (subSaveAll) subSaveAll.textContent = "✨ 音声（A/B）・字幕テキストを一括書き出し";
        } else {
          if (subSaveAll) subSaveAll.textContent = "✨ 音声（トラックA・B）を一括書き出し";
        }
      }

      if (btnTrackA) btnTrackA.disabled = locked;
      if (subTrackA) subTrackA.textContent = "24bit / 48kHz WAV（抽出された声のみ保存）";

      if (btnTrackB) btnTrackB.disabled = locked;
      if (subTrackB) subTrackB.textContent = "24bit / 48kHz WAV（抽出された背景音/BGMのみ保存）";

      if (hasVideo) {
        if (btnRepMp4) btnRepMp4.disabled = locked;
        if (subRepMp4) subRepMp4.textContent = "映像無劣化コピー（-c:v copy）";
        if (btnVidOnly) btnVidOnly.disabled = locked;
        if (subVidOnly) subVidOnly.textContent = "映像無劣化・音声完全除去（-an）";
      } else {
        if (btnRepMp4) btnRepMp4.disabled = true;
        if (subRepMp4) subRepMp4.textContent = "🔒 音声ファイル入力のため対象外（暗転）";
        if (btnVidOnly) btnVidOnly.disabled = true;
        if (subVidOnly) subVidOnly.textContent = "🔒 音声ファイル入力のため対象外（暗転）";
      }

      if (textReady && hasText) {
        if (btnTxt) btnTxt.disabled = locked;
        if (subTxt) subTxt.textContent = "テキスト / DaVinci用字幕 (.txt / .srt)";
      } else {
        if (btnTxt) btnTxt.disabled = true;
        if (subTxt) subTxt.textContent = "🔒 文字起こし未実行のため暗転（無効）";
      }
    }

    // プレビュー再生系ボタンの有効化
    const playA = document.getElementById("playBtnA");
    const playB = document.getElementById("playBtnB");
    const playMix = document.getElementById("playBtnMix");
    if (playA) playA.disabled = !separated;
    if (playB) playB.disabled = !separated;
    if (playMix) playMix.disabled = !separated;

    const origPlay = document.getElementById("origPlayBtn");
    if (origPlay) origPlay.disabled = !hasFile;

    updateVideoPanelVisibility();
  }

  function updateTempStatus(tempStatus) {
    if (!tempStatus) return;
    const box = document.getElementById("tempManageBox");
    const alertEl = document.getElementById("tempAlertText");
    const metaEl = document.getElementById("tempMetaText");
    const clearBtn = document.getElementById("btnClearTemp");

    if (alertEl) {
      alertEl.textContent = tempStatus.alert_text || "";
    }
    if (box) {
      box.classList.remove("clean", "info");
      if (!tempStatus.has_any_files && !tempStatus.has_past_files) {
        box.classList.add("clean");
      } else if (!tempStatus.has_past_files && tempStatus.has_any_files) {
        box.classList.add("info");
      }
    }
    if (metaEl) {
      if (tempStatus.has_past_files) {
        metaEl.textContent = `※ 自動削除は行われません。格納先: ${tempStatus.temp_dir} （不要な過去プレビューを手動で削除してください）`;
      } else if (tempStatus.has_any_files) {
        metaEl.textContent = `※ 現在の作業中プレビューは保持されています。格納先: ${tempStatus.temp_dir}`;
      } else {
        metaEl.textContent = `格納先: ${tempStatus.temp_dir}`;
      }
    }
    if (clearBtn) {
      clearBtn.disabled = !tempStatus.has_past_files;
    }
  }

  function updatePathPreview() {
    const dirEl = document.getElementById("outputDir");
    const patternEl = document.getElementById("prefixPattern");
    const targetEl = document.getElementById("wavTarget");
    const previewEl = document.getElementById("pathPreview");
    if (!dirEl || !patternEl || !targetEl || !previewEl) return;

    const dir = (dirEl.value.trim() || "outputs").replace(/[\\\/]+$/, "");
    const pattern = patternEl.value.trim() || "%date%\\%time%_%filename%";
    const wavTarget = targetEl.value || "vocal";
    const modeVal = getSelectedMode();

    const now = new Date();
    const yyyy = String(now.getFullYear());
    const mm = String(now.getMonth() + 1).padStart(2, "0");
    const dd = String(now.getDate()).padStart(2, "0");
    const hh = String(now.getHours()).padStart(2, "0");
    const mi = String(now.getMinutes()).padStart(2, "0");
    const ss = String(now.getSeconds()).padStart(2, "0");
    const dateStr = `${yyyy}-${mm}-${dd}`;
    const timeStr = `${hh}-${mi}-${ss}`;

    const suffixMap = {
      vocal: "_vocal.wav",
      mixed: "_mixed.wav",
      bgm: "_bgm.wav",
      both: "_vocal.wav (+ _bgm.wav)",
    };

    const resolved = pattern
      .replaceAll("%datetime%", `${dateStr}_${timeStr}`)
      .replaceAll("%date%", dateStr)
      .replaceAll("%time%", timeStr)
      .replaceAll("%YYYY%", yyyy)
      .replaceAll("%MM%", mm)
      .replaceAll("%DD%", dd)
      .replaceAll("%hh%", hh)
      .replaceAll("%mm%", mi)
      .replaceAll("%ss%", ss)
      .replaceAll("%filename%", sanitizeFilenamePart(state.baseName) || "sample_video")
      .replaceAll("%mode%", sanitizeFilenamePart(modeVal));

    previewEl.textContent = `出力例: ${dir}\\${resolved}${suffixMap[wavTarget] || "_vocal.wav"}`;
  }

  function insertVar(token) {
    const input = document.getElementById("prefixPattern");
    if (!input) return;
    const start = input.selectionStart ?? input.value.length;
    const end = input.selectionEnd ?? input.value.length;
    input.value = input.value.slice(0, start) + token + input.value.slice(end);
    input.focus();
    const pos = start + token.length;
    input.setSelectionRange(pos, pos);
    updatePathPreview();
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }

  function showExportResult(paths) {
    const box = document.getElementById("exportResultBox");
    const pathsEl = document.getElementById("exportResultPaths");
    if (!box || !pathsEl || !Array.isArray(paths) || paths.length === 0) return;
    state.lastExportedPath = paths[0];
    pathsEl.innerHTML = paths.map((p) => `<div>・${p}</div>`).join("");
    box.classList.add("visible");
  }

  function clearExportResult() {
    const box = document.getElementById("exportResultBox");
    const pathsEl = document.getElementById("exportResultPaths");
    if (box) box.classList.remove("visible");
    if (pathsEl) pathsEl.innerHTML = "";
  }

  global.AppState = {
    state,
    showToast,
    formatDuration,
    getSelectedMode,
    setBusy,
    renderHeaderStatus,
    refreshButtons,
    updateTempStatus,
    updatePathPreview,
    insertVar,
    showExportResult,
    clearExportResult,
  };
})(window);
