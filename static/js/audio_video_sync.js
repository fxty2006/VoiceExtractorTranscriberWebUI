/**
 * 音声・映像同期再生およびWeb Audio APIミキサーモジュール (static/js/audio_video_sync.js)
 * ・元ファイル単体プレイヤー制御
 * ・トラックA（声）およびトラックB（背景音/ノイズ）の実波形Canvas描画＆クリックシーク
 * ・AudioContext + GainNode による 0%〜150% スライダー・ミュート・ソロの0msリアルタイム反映
 * ・無音化した <video> 要素のフレーム・再生位置同期
 */
(function (global) {
  let audioCtx = null;
  let gainNodeA = null;
  let gainNodeB = null;
  let graphInitialized = false;

  let activeMode = null; // null | "A" | "B" | "MIX"
  let rafId = null;

  let peaksA = [];
  let peaksB = [];
  let totalDuration = 0;

  let muteA = false;
  let muteB = false;
  let soloA = false;
  let soloB = false;
  let onMixerChangeCb = null;

  function els() {
    return {
      origAudio: document.getElementById("origAudioEl"),
      origPlayBtn: document.getElementById("origPlayBtn"),
      origFill: document.getElementById("origProgressFill"),
      origTrack: document.getElementById("origProgressTrack"),
      origTime: document.getElementById("origTimeText"),

      video: document.getElementById("syncVideoPlayer"),
      videoStage: document.getElementById("videoStage"),
      videoTimeHud: document.getElementById("videoTimeHud"),
      syncTrackLabel: document.getElementById("syncTrackLabel"),

      audioA: document.getElementById("trackAAudioEl"),
      audioB: document.getElementById("trackBAudioEl"),
      playBtnA: document.getElementById("playBtnA"),
      playBtnB: document.getElementById("playBtnB"),
      playBtnMix: document.getElementById("playBtnMix"),

      progTrackA: document.getElementById("progTrackA"),
      progTrackB: document.getElementById("progTrackB"),
      progTrackMix: document.getElementById("progTrackMix"),
      progA: document.getElementById("progA"),
      progB: document.getElementById("progB"),
      progMix: document.getElementById("progMix"),
      timeA: document.getElementById("timeA"),
      timeB: document.getElementById("timeB"),
      timeMix: document.getElementById("timeMix"),

      sliderA: document.getElementById("sliderVolA"),
      sliderB: document.getElementById("sliderVolB"),
      valA: document.getElementById("volA"),
      valB: document.getElementById("volB"),
      btnMuteA: document.getElementById("btnMuteA"),
      btnSoloA: document.getElementById("btnSoloA"),
      btnMuteB: document.getElementById("btnMuteB"),
      btnSoloB: document.getElementById("btnSoloB"),

      canvasA: document.getElementById("waveCanvasA"),
      canvasB: document.getElementById("waveCanvasB"),
    };
  }

  function ensureAudioGraph() {
    const { audioA, audioB } = els();
    if (!audioA || !audioB) return;

    if (!graphInitialized) {
      const AC = window.AudioContext || window.webkitAudioContext;
      if (AC) {
        try {
          audioCtx = new AC();
          const srcA = audioCtx.createMediaElementSource(audioA);
          const srcB = audioCtx.createMediaElementSource(audioB);
          gainNodeA = audioCtx.createGain();
          gainNodeB = audioCtx.createGain();
          srcA.connect(gainNodeA).connect(audioCtx.destination);
          srcB.connect(gainNodeB).connect(audioCtx.destination);
          // 前段での信号遮断を防ぐため、DOM要素自体のボリュームは常に等倍(1.0)に維持する
          audioA.volume = 1.0;
          audioB.volume = 1.0;
          graphInitialized = true;
        } catch (err) {
          console.warn("[AudioSync] Web Audio graph fallback:", err);
        }
      }
    }
    if (audioCtx && audioCtx.state === "suspended") {
      audioCtx.resume().catch(() => {});
    }
  }

  function getExportParams() {
    const { sliderA, sliderB } = els();
    return {
      vol_a_pct: sliderA ? Number(sliderA.value) : 100,
      vol_b_pct: sliderB ? Number(sliderB.value) : 100,
      mute_a: muteA,
      mute_b: muteB,
      solo_a: soloA,
      solo_b: soloB,
    };
  }

  function computeMixGains() {
    const p = getExportParams();
    const anySolo = Boolean(p.solo_a || p.solo_b);
    const activeA = !p.mute_a && (!anySolo || p.solo_a);
    const activeB = !p.mute_b && (!anySolo || p.solo_b);
    return {
      gainA: activeA ? Math.max(0, Math.min(1.5, p.vol_a_pct / 100)) : 0,
      gainB: activeB ? Math.max(0, Math.min(1.5, p.vol_b_pct / 100)) : 0,
    };
  }

  function setOnMixerChange(cb) {
    onMixerChangeCb = typeof cb === "function" ? cb : null;
  }

  function notifyMixerChange() {
    if (onMixerChangeCb) onMixerChangeCb();
  }

  function setMuteStates(newMuteA, newMuteB) {
    muteA = Boolean(newMuteA);
    muteB = Boolean(newMuteB);
    const { btnMuteA, btnMuteB } = els();
    if (btnMuteA) btnMuteA.classList.toggle("active-mute", muteA);
    if (btnMuteB) btnMuteB.classList.toggle("active-mute", muteB);
    applyLiveGains();
  }

  function applyLiveGains() {
    const { audioA, audioB, sliderA, sliderB } = els();
    const mix = computeMixGains();

    let liveA = mix.gainA;
    let liveB = mix.gainB;

    if (activeMode === "A") {
      const sliderVal = sliderA ? Number(sliderA.value) / 100 : 1.0;
      liveA = muteA ? 0 : sliderVal;
      liveB = 0;
    } else if (activeMode === "B") {
      const sliderVal = sliderB ? Number(sliderB.value) / 100 : 1.0;
      liveA = 0;
      liveB = muteB ? 0 : sliderVal;
    }

    if (gainNodeA && gainNodeB && audioCtx) {
      if (audioA) audioA.volume = 1.0;
      if (audioB) audioB.volume = 1.0;
      const t = audioCtx.currentTime;
      gainNodeA.gain.setValueAtTime(liveA, t);
      gainNodeB.gain.setValueAtTime(liveB, t);
    } else {
      if (audioA) audioA.volume = Math.min(1, liveA);
      if (audioB) audioB.volume = Math.min(1, liveB);
    }
  }

  function drawSingleWaveform(canvas, peaks, colorVar, progressRatio) {
    if (!canvas) return;
    const rect = canvas.getBoundingClientRect();
    const dpr = window.devicePixelRatio || 1;
    const w = Math.max(200, Math.floor(rect.width || canvas.clientWidth || 500));
    const h = Math.max(40, Math.floor(rect.height || canvas.clientHeight || 46));
    if (canvas.width !== Math.floor(w * dpr) || canvas.height !== Math.floor(h * dpr)) {
      canvas.width = Math.floor(w * dpr);
      canvas.height = Math.floor(h * dpr);
    }

    const ctx = canvas.getContext("2d");
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    const styles = getComputedStyle(document.documentElement);
    const barColor = styles.getPropertyValue(colorVar).trim() || "#0284c7";
    const mutedColor = styles.getPropertyValue("--border-strong").trim() || "#94a3b8";
    const playheadColor = styles.getPropertyValue("--text-main").trim() || "#1e293b";

    const list = peaks && peaks.length > 0 ? peaks : new Array(140).fill(0.08);
    const count = list.length;
    const slotW = w / count;
    const barW = Math.max(1.5, slotW * 0.68);
    const midY = h / 2;

    for (let i = 0; i < count; i++) {
      const val = Math.max(0.05, Math.min(1.0, Number(list[i]) || 0.05));
      const barH = val * (h - 6);
      const x = i * slotW + (slotW - barW) / 2;
      const ratio = i / count;
      const played = progressRatio > 0 && ratio < progressRatio;
      ctx.fillStyle = played ? barColor : mutedColor;
      ctx.globalAlpha = played ? 0.92 : 0.45;
      ctx.fillRect(x, midY - barH / 2, barW, barH);
    }

    ctx.globalAlpha = 1.0;
    if (progressRatio > 0 && progressRatio <= 1) {
      const px = Math.min(w - 1, Math.max(1, progressRatio * w));
      ctx.strokeStyle = playheadColor;
      ctx.lineWidth = 1.5;
      ctx.beginPath();
      ctx.moveTo(px, 0);
      ctx.lineTo(px, h);
      ctx.stroke();
    }
  }

  function redrawWaveforms(progressRatio = 0) {
    const { canvasA, canvasB } = els();
    drawSingleWaveform(canvasA, peaksA, "--track-a", progressRatio);
    drawSingleWaveform(canvasB, peaksB, "--track-b", progressRatio);
  }

  function updateTimeDisplays(currentSec) {
    const { progA, progB, progMix, timeA, timeB, timeMix, videoTimeHud } = els();
    const dur = totalDuration > 0 ? totalDuration : 0;
    const pct = dur > 0 ? Math.min(100, Math.max(0, (currentSec / dur) * 100)) : 0;
    const fmt = global.AppState.formatDuration;
    const str = `${fmt(currentSec)} / ${fmt(dur)}`;

    if (progA) progA.style.width = `${pct}%`;
    if (progB) progB.style.width = `${pct}%`;
    if (progMix) progMix.style.width = `${pct}%`;
    if (timeA) timeA.textContent = str;
    if (timeB) timeB.textContent = str;
    if (timeMix) timeMix.textContent = str;
    if (videoTimeHud) videoTimeHud.textContent = str;

    redrawWaveforms(dur > 0 ? currentSec / dur : 0);
  }

  function stopOriginalPlayer() {
    const { origAudio, origPlayBtn } = els();
    if (origAudio && !origAudio.paused) {
      origAudio.pause();
    }
    if (origPlayBtn) origPlayBtn.textContent = "▶";
  }

  function stopSyncedPlay(resetTime = false) {
    if (rafId !== null) {
      cancelAnimationFrame(rafId);
      rafId = null;
    }
    const { audioA, audioB, video, playBtnA, playBtnB, playBtnMix, videoStage, syncTrackLabel } = els();
    if (audioA) {
      audioA.pause();
      if (resetTime) audioA.currentTime = 0;
    }
    if (audioB) {
      audioB.pause();
      if (resetTime) audioB.currentTime = 0;
    }
    if (video) {
      video.pause();
      if (resetTime) video.currentTime = 0;
    }
    activeMode = null;
    if (playBtnA) playBtnA.textContent = "▶";
    if (playBtnB) playBtnB.textContent = "▶";
    if (playBtnMix) playBtnMix.textContent = "▶";
    if (videoStage) videoStage.classList.remove("playing");
    if (syncTrackLabel && global.AppState.state.hasVideo) {
      syncTrackLabel.textContent = global.AppState.state.separated
        ? "🔗 音声再生・シーク連動 ON"
        : "🔗 音声再生・シーク連動（分離待ち）";
    }
    if (resetTime) {
      updateTimeDisplays(0);
    }
  }

  function syncTick() {
    const { audioA, audioB, video } = els();
    if (!audioA || audioA.paused || activeMode === null) {
      return;
    }

    const masterT = audioA.currentTime || 0;
    if (audioB && Math.abs((audioB.currentTime || 0) - masterT) > 0.06) {
      try {
        audioB.currentTime = masterT;
      } catch (_) {}
    }

    if (video && global.AppState.state.hasVideo && video.readyState >= 1) {
      if (Math.abs((video.currentTime || 0) - masterT) > 0.08) {
        try {
          video.currentTime = masterT;
        } catch (_) {}
      }
      if (video.paused && !video.ended) {
        video.play().catch(() => {});
      }
    }

    updateTimeDisplays(masterT);
    rafId = requestAnimationFrame(syncTick);
  }

  async function toggleSyncedPlay(mode) {
    if (!global.AppState.state.separated) {
      global.AppState.showToast("先に「音声分離・ノイズ除去を実行」を行ってください。", true);
      return;
    }

    const { audioA, audioB, video, playBtnA, playBtnB, playBtnMix, videoStage, syncTrackLabel } = els();
    if (!audioA || !audioB || !audioA.getAttribute("src")) return;

    const wasSame = activeMode === mode && !audioA.paused;
    const savedTime = audioA.currentTime || 0;
    stopOriginalPlayer();
    stopSyncedPlay(false);

    if (wasSame) {
      return;
    }

    ensureAudioGraph();
    activeMode = mode;
    applyLiveGains();

    const resumeAt = totalDuration > 0 && savedTime >= totalDuration - 0.05 ? 0 : savedTime;
    try {
      audioA.currentTime = resumeAt;
      audioB.currentTime = resumeAt;
      if (video && global.AppState.state.hasVideo) {
        video.currentTime = resumeAt;
      }
    } catch (_) {}

    const labelMap = {
      A: "トラックA（声のみ）",
      B: "トラックB（背景音/ノイズのみ）",
      MIX: "ミックス試聴（A＋B）",
    };

    if (mode === "A" && playBtnA) playBtnA.textContent = "⏸";
    if (mode === "B" && playBtnB) playBtnB.textContent = "⏸";
    if (mode === "MIX" && playBtnMix) playBtnMix.textContent = "⏸";
    if (videoStage) videoStage.classList.add("playing");
    if (syncTrackLabel && global.AppState.state.hasVideo) {
      syncTrackLabel.textContent = `🔗 同期再生中: ${labelMap[mode]}`;
    }

    try {
      const promises = [audioA.play(), audioB.play()];
      if (video && global.AppState.state.hasVideo && video.getAttribute("src")) {
        promises.push(video.play().catch(() => {}));
      }
      await Promise.all(promises);
      rafId = requestAnimationFrame(syncTick);
    } catch (err) {
      stopSyncedPlay(false);
      global.AppState.showToast(`再生を開始できませんでした: ${err.message}`, true);
    }
  }

  function seekToRatio(ratio) {
    if (!global.AppState.state.separated || totalDuration <= 0) return;
    const clamped = Math.max(0, Math.min(1, ratio));
    const targetSec = clamped * totalDuration;
    const { audioA, audioB, video } = els();
    if (audioA) audioA.currentTime = targetSec;
    if (audioB) audioB.currentTime = targetSec;
    if (video && global.AppState.state.hasVideo && video.getAttribute("src")) {
      try {
        video.currentTime = targetSec;
      } catch (_) {}
    }
    updateTimeDisplays(targetSec);
  }

  function loadOriginalMedia(originalAudioUrl, videoPreviewUrl, duration) {
    stopOriginalPlayer();
    stopSyncedPlay(true);
    totalDuration = Number(duration) || 0;
    peaksA = [];
    peaksB = [];

    const { origAudio, origFill, origTime, video, audioA, audioB } = els();
    if (origAudio) {
      origAudio.src = originalAudioUrl || "";
      origAudio.load();
    }
    if (origFill) origFill.style.width = "0%";
    if (origTime) origTime.textContent = `00:00 / ${global.AppState.formatDuration(totalDuration)}`;

    if (audioA) audioA.removeAttribute("src");
    if (audioB) audioB.removeAttribute("src");

    if (video) {
      if (videoPreviewUrl) {
        video.muted = true;
        video.src = videoPreviewUrl;
        video.load();
      } else {
        video.removeAttribute("src");
      }
    }

    updateTimeDisplays(0);
  }

  function loadSeparatedTracks(trackAUrl, trackBUrl, newPeaksA, newPeaksB, duration) {
    stopOriginalPlayer();
    stopSyncedPlay(true);
    totalDuration = Number(duration) || totalDuration;
    peaksA = Array.isArray(newPeaksA) ? newPeaksA : [];
    peaksB = Array.isArray(newPeaksB) ? newPeaksB : [];

    const { audioA, audioB } = els();
    if (audioA) {
      audioA.src = trackAUrl;
      audioA.load();
    }
    if (audioB) {
      audioB.src = trackBUrl;
      audioB.load();
    }

    applyLiveGains();
    updateTimeDisplays(0);
  }

  function bindEvents() {
    const {
      origAudio,
      origPlayBtn,
      origFill,
      origTrack,
      origTime,
      audioA,
      playBtnA,
      playBtnB,
      playBtnMix,
      progTrackA,
      progTrackB,
      progTrackMix,
      canvasA,
      canvasB,
      sliderA,
      sliderB,
      valA,
      valB,
      btnMuteA,
      btnSoloA,
      btnMuteB,
      btnSoloB,
    } = els();

    if (origPlayBtn && origAudio) {
      origPlayBtn.addEventListener("click", () => {
        if (!origAudio.getAttribute("src")) return;
        if (origAudio.paused) {
          stopSyncedPlay(false);
          origAudio.play().then(() => {
            origPlayBtn.textContent = "⏸";
          }).catch(() => {});
        } else {
          origAudio.pause();
          origPlayBtn.textContent = "▶";
        }
      });

      origAudio.addEventListener("timeupdate", () => {
        const dur = origAudio.duration || totalDuration || 0;
        const cur = origAudio.currentTime || 0;
        const pct = dur > 0 ? (cur / dur) * 100 : 0;
        if (origFill) origFill.style.width = `${pct}%`;
        if (origTime) {
          const fmt = global.AppState.formatDuration;
          origTime.textContent = `${fmt(cur)} / ${fmt(dur)}`;
        }
      });

      origAudio.addEventListener("ended", () => {
        origPlayBtn.textContent = "▶";
      });
    }

    if (origTrack && origAudio) {
      origTrack.addEventListener("click", (e) => {
        const dur = origAudio.duration || totalDuration || 0;
        if (dur <= 0) return;
        const rect = origTrack.getBoundingClientRect();
        const ratio = Math.max(0, Math.min(1, (e.clientX - rect.left) / rect.width));
        origAudio.currentTime = ratio * dur;
      });
    }

    if (audioA) {
      audioA.addEventListener("ended", () => stopSyncedPlay(true));
    }

    if (playBtnA) playBtnA.addEventListener("click", () => toggleSyncedPlay("A"));
    if (playBtnB) playBtnB.addEventListener("click", () => toggleSyncedPlay("B"));
    if (playBtnMix) playBtnMix.addEventListener("click", () => toggleSyncedPlay("MIX"));

    [progTrackA, progTrackB, progTrackMix, canvasA, canvasB].forEach((el) => {
      if (!el) return;
      el.addEventListener("click", (e) => {
        const rect = el.getBoundingClientRect();
        if (rect.width <= 0) return;
        const ratio = (e.clientX - rect.left) / rect.width;
        seekToRatio(ratio);
      });
    });

    function handleSliderWithSnap(slider, badge) {
      if (!slider) return;
      let val = Number(slider.value);
      // 95%〜105%の範囲に入ったらピタッと100%に吸着
      if (val >= 95 && val <= 105) {
        val = 100;
        slider.value = "100";
      }
      if (badge) badge.textContent = `${val}%`;
      applyLiveGains();
      notifyMixerChange();
    }

    if (sliderA) {
      sliderA.addEventListener("input", () => handleSliderWithSnap(sliderA, valA));
    }
    if (sliderB) {
      sliderB.addEventListener("input", () => handleSliderWithSnap(sliderB, valB));
    }

    if (valA) {
      valA.addEventListener("click", () => {
        if (sliderA) {
          sliderA.value = "100";
          valA.textContent = "100%";
          applyLiveGains();
          notifyMixerChange();
        }
      });
    }
    if (valB) {
      valB.addEventListener("click", () => {
        if (sliderB) {
          sliderB.value = "100";
          valB.textContent = "100%";
          applyLiveGains();
          notifyMixerChange();
        }
      });
    }

    if (btnMuteA) {
      btnMuteA.addEventListener("click", () => {
        muteA = !muteA;
        btnMuteA.classList.toggle("active-mute", muteA);
        applyLiveGains();
        notifyMixerChange();
      });
    }
    if (btnSoloA) {
      btnSoloA.addEventListener("click", () => {
        soloA = !soloA;
        btnSoloA.classList.toggle("active-solo", soloA);
        applyLiveGains();
      });
    }
    if (btnMuteB) {
      btnMuteB.addEventListener("click", () => {
        muteB = !muteB;
        btnMuteB.classList.toggle("active-mute", muteB);
        applyLiveGains();
        notifyMixerChange();
      });
    }
    if (btnSoloB) {
      btnSoloB.addEventListener("click", () => {
        soloB = !soloB;
        btnSoloB.classList.toggle("active-solo", soloB);
        applyLiveGains();
      });
    }

    window.addEventListener("resize", () => {
      const { audioA: a } = els();
      const ratio = a && totalDuration > 0 ? (a.currentTime || 0) / totalDuration : 0;
      redrawWaveforms(ratio);
    });

    if (global.AppTheme) {
      global.AppTheme.onThemeChange(() => {
        const { audioA: a } = els();
        const ratio = a && totalDuration > 0 ? (a.currentTime || 0) / totalDuration : 0;
        redrawWaveforms(ratio);
      });
    }
  }

  global.AudioVideoSync = {
    bindEvents,
    loadOriginalMedia,
    loadSeparatedTracks,
    stopSyncedPlay,
    stopOriginalPlayer,
    getExportParams,
    setMuteStates,
    setOnMixerChange,
    redrawWaveforms,
  };
})(window);
