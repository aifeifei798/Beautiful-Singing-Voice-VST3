# Copyright 2026 Feifei
# SPDX-License-Identifier: GPL-3.0-only

"""Beautiful Singing Voice — one-click Suno vocal/arrangement studio."""

from __future__ import annotations

import copy
import sys
from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PyQt6.QtCore import Qt, QThread, QTimer, pyqtSignal
from PyQt6.QtGui import QColor
from PyQt6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSpinBox,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from bsv.analysis import analyze
from bsv.audio import AUDIO_EXTS
from bsv.pipeline import Project, RenderResult, export, open_project
from bsv.presets import PRESETS, Params
from bsv.ui.player import Player


SLIDERS = [
    ("人声电平", "vocal_gain_db", -6.0, 8.0, 1.0),
    ("配乐电平", "music_gain_db", -8.0, 6.0, 1.0),
    ("人声闪避 (duck)", "duck_db", 0.0, 10.0, 1.0),
    ("齿音抑制", "deesser_amount", 0.0, 1.2, 0.05),
    ("人声亮度 (presence)", "presence_db", 0.0, 6.0, 0.5),
    ("空间 (reverb)", "reverb_wet", 0.0, 0.4, 0.02),
    ("加厚 (doubling)", "doubling_db", -60.0, -6.0, 1.0),
    ("目标响度", "target_lufs", -20.0, -8.0, 0.5),
]

# Shown under the matching slider, and as its tooltip. Worth the extra row:
# doubling is the one control whose ideal setting depends on how you listen.
SLIDER_HINTS = {
    "doubling_db": "耳机监听建议调低加厚；外放 / 现场感建议拉满。",
}

A_COLOR = QColor(120, 120, 120)
B_COLOR = QColor(40, 190, 120)
A_FILL = QColor(120, 120, 120, 60)
B_FILL = QColor(40, 190, 120, 90)
DEFAULT_PRESET = "中性 (只修问题)"


def envelope(data: np.ndarray, points: int = 1400) -> tuple[np.ndarray, np.ndarray]:
    mono = data.mean(axis=1)
    n = len(mono)
    block = max(1, n // points)
    trimmed = mono[: block * (n // block)]
    if trimmed.size == 0:
        return np.array([0.0]), np.array([0.0])
    blocks = trimmed.reshape(-1, block)
    return blocks.min(axis=1), blocks.max(axis=1)


def spectrum(data: np.ndarray, sr: int = 44100, bins: int = 260) -> tuple[np.ndarray, np.ndarray]:
    """Smoothed magnitude spectrum in dB — raw FFT bins are too jagged to compare."""
    mono = data.mean(axis=1)
    window = mono[: min(len(mono), 200000)]
    if window.size < 100:
        return np.array([0.0]), np.array([0.0])
    spec = np.abs(np.fft.rfft(window * np.hanning(len(window))))
    freqs = np.fft.rfftfreq(len(window), 1.0 / sr)
    edges = np.exp(np.linspace(np.log(30.0), np.log(sr / 2.0), bins + 1))
    idx = np.clip(np.searchsorted(edges, freqs, side="right") - 1, 0, bins - 1)
    counts = np.bincount(idx, minlength=bins)
    sums = np.bincount(idx, weights=spec, minlength=bins)
    mean = sums / np.maximum(counts, 1)
    centers = np.sqrt(edges[:-1] * edges[1:])
    return centers, 20.0 * np.log10(np.maximum(mean, 1e-9))


class SeparationWorker(QThread):
    progress = pyqtSignal(float, str)
    done = pyqtSignal(object)
    failed = pyqtSignal(str)

    def __init__(self, path: Path, model: str, device: str | None = None):
        super().__init__()
        self.path = path
        self.model = model
        self.device = device

    def run(self):
        try:
            project = open_project(
                self.path,
                model=self.model,
                device=self.device,
                progress_cb=lambda p, msg: self.progress.emit(p, msg),
            )
            self.done.emit(project)
        except Exception as exc:  # keep the app alive even if the model fails
            self.failed.emit(str(exc))


class RenderWorker(QThread):
    done = pyqtSignal(object)

    def __init__(self, project: Project, params: Params, start, end):
        super().__init__()
        self.project = project
        self.params = params
        self.start_sec = start
        self.end_sec = end

    def run(self):
        self.done.emit(self.project.render(self.params, self.start_sec, self.end_sec))


class ExportWorker(QThread):
    done = pyqtSignal(str)
    failed = pyqtSignal(str)

    def __init__(self, project: Project, params: Params, fmt: str):
        super().__init__()
        self.project = project
        self.params = params
        self.fmt = fmt

    def run(self):
        try:
            source = Path(self.project.source)
            out = source.with_name(f"{source.stem}_fixed.{self.fmt}")
            export(self.project.render(self.params), out, self.project.sr, self.fmt)
            self.done.emit(str(out))
        except Exception as exc:
            self.failed.emit(str(exc))


class StudioWindow(QWidget):
    def __init__(self, model: str = "htdemucs_ft", device: str | None = None):
        super().__init__()
        self.setWindowTitle("Beautiful Singing Voice — 一键人声修复")
        self.resize(1100, 700)
        self.setAcceptDrops(True)

        self.model = model
        self.device = device
        self.project: Project | None = None
        self.current_path: Path | None = None
        self.result: RenderResult | None = None
        self.params: Params = copy.deepcopy(PRESETS[DEFAULT_PRESET])
        self.applied_preset: str | None = None
        self.dirty = False
        self.separation: SeparationWorker | None = None
        self.render_thread: RenderWorker | None = None
        self.export_thread: ExportWorker | None = None
        self.pending_render = False
        self.player = Player(44100)
        self.ab = "B"  # B = fixed version, A = original
        self.solo = "mix"
        self.region: tuple[float, float] | None = None
        self.stats: dict = {}

        self._build_ui()
        self.timer = QTimer(self)
        timer_interval = 60
        self.timer.setInterval(timer_interval)
        self.timer.timeout.connect(self._update_playhead)
        self.timer.start()

    # ---------------------------------------------------------------- UI ----
    def _build_ui(self) -> None:
        root = QHBoxLayout(self)

        left = QVBoxLayout()
        file_box = QGroupBox("1. 丢歌曲")
        file_layout = QVBoxLayout(file_box)
        self.file_label = QLabel("未选择文件")
        self.open_button = QPushButton("选择歌曲…")
        self.open_button.clicked.connect(self.choose_file)
        file_layout.addWidget(self.file_label)
        file_layout.addWidget(self.open_button)
        file_layout.addWidget(QLabel("支持 .mp3 / .flac / .wav / .webm，自动转成 44.1 kHz WAV"))
        left.addWidget(file_box)

        fix_box = QGroupBox("2. 一键修复")
        fix_layout = QVBoxLayout(fix_box)
        self.preset_combo = QComboBox()
        self.preset_combo.addItems(list(PRESETS.keys()))
        self.preset_combo.setCurrentText(DEFAULT_PRESET)
        self.preset_combo.currentIndexChanged.connect(self._preset_changed)
        self.fix_button = QPushButton("⚡ 一键修复")
        self.fix_button.setStyleSheet("font-weight: bold; padding: 8px;")
        self.fix_button.clicked.connect(self._fix)
        self.progress_label = QLabel("等待文件…")
        fix_layout.addWidget(self.preset_combo)
        fix_layout.addWidget(self.fix_button)
        fix_layout.addWidget(self.progress_label)
        left.addWidget(fix_box)

        knob_box = QGroupBox("3. 微调（改完自动重新预览）")
        grid = QGridLayout(knob_box)
        self.knobs: list[tuple[str, QSlider, QLabel, float, float, float]] = []
        row = 0
        for label, key, lo, hi, step in SLIDERS:
            slider = QSlider(Qt.Orientation.Horizontal)
            slider.setRange(int(lo * 100), int(hi * 100))
            slider.setValue(int(getattr(self.params, key) * 100))
            value = QLabel(f"{getattr(self.params, key):.2f}")
            slider.valueChanged.connect(lambda v, k=key: self._knob_changed(k, v))
            name = QLabel(label)
            grid.addWidget(name, row, 0)
            grid.addWidget(slider, row, 1)
            grid.addWidget(value, row, 2)
            row += 1

            hint = SLIDER_HINTS.get(key)
            if hint:
                slider.setToolTip(hint)
                name.setToolTip(hint)
                value.setToolTip(hint)
                note = QLabel(hint)
                note.setWordWrap(True)
                note.setContentsMargins(0, 0, 0, 4)
                note.setStyleSheet("color: #8a8f98; font-size: 11px;")
                grid.addWidget(note, row, 0, 1, 3)
                row += 1

            self.knobs.append((key, slider, value, lo, hi, step))
        left.addWidget(knob_box)

        export_box = QGroupBox("4. 导出")
        export_layout = QHBoxLayout(export_box)
        self.format_combo = QComboBox()
        self.format_combo.addItems(["wav", "flac", "mp3"])
        self.export_button = QPushButton("导出成品")
        self.export_button.clicked.connect(self.do_export)
        export_layout.addWidget(self.format_combo)
        export_layout.addWidget(self.export_button)
        left.addWidget(export_box)
        left.addStretch()
        root.addLayout(left, 1)

        right = QVBoxLayout()

        transport = QHBoxLayout()
        self.play_a = QPushButton("▶ A 原始")
        self.play_b = QPushButton("▶ B 修复")
        self.stop_button = QPushButton("■")
        self.play_a.clicked.connect(lambda: self._play("A"))
        self.play_b.clicked.connect(lambda: self._play("B"))
        self.stop_button.clicked.connect(self.player.stop)
        for button in (self.play_a, self.play_b, self.stop_button):
            transport.addWidget(button)

        self.solo_combo = QComboBox()
        self.solo_combo.addItems(["混合", "人声", "配乐"])
        self.solo_combo.currentIndexChanged.connect(self._solo_changed)
        transport.addWidget(QLabel("Solo:"))
        transport.addWidget(self.solo_combo)

        self.region_start = QSpinBox()
        self.region_start.setRange(0, 600)
        self.region_end = QSpinBox()
        self.region_end.setRange(0, 600)
        self.region_start.editingFinished.connect(self._region_changed)
        self.region_end.editingFinished.connect(self._region_changed)
        transport.addWidget(QLabel("预览区间"))
        transport.addWidget(self.region_start)
        transport.addWidget(QLabel("–"))
        transport.addWidget(self.region_end)
        transport.addWidget(QLabel("s"))
        right.addLayout(transport)

        self.wave = pg.PlotWidget(title="波形对比（灰 = 原始，绿 = 修复）")
        self.wave.setLabel("bottom", "时间 (s)")
        self.wave.setLabel("left", "幅度")
        self.wave.showGrid(x=True, y=True)
        self.curve_a_hi = pg.PlotCurveItem(pen={"color": A_COLOR, "width": 1})
        self.curve_a_lo = pg.PlotCurveItem(pen={"color": A_COLOR, "width": 1})
        self.curve_b_hi = pg.PlotCurveItem(pen={"color": B_COLOR, "width": 1})
        self.curve_b_lo = pg.PlotCurveItem(pen={"color": B_COLOR, "width": 1})
        self.fill_a = pg.FillBetweenItem(self.curve_a_hi, self.curve_a_lo, brush=A_FILL)
        self.fill_b = pg.FillBetweenItem(self.curve_b_hi, self.curve_b_lo, brush=B_FILL)
        self.wave.addItem(self.fill_a)
        self.wave.addItem(self.fill_b)
        for curve in (self.curve_a_hi, self.curve_a_lo, self.curve_b_hi, self.curve_b_lo):
            self.wave.addItem(curve)
        self.playhead = pg.InfiniteLine(pos=0, angle=90, pen={"color": QColor(255, 120, 40), "width": 1})
        self.wave.addItem(self.playhead)
        right.addWidget(self.wave, 3)

        self.spec = pg.PlotWidget(title="频谱对比")
        self.spec.setLabel("bottom", "频率 (Hz)")
        self.spec.setLabel("left", "幅度 (dB)")
        self.spec.showGrid(x=True, y=True)
        self.spec_a = pg.PlotCurveItem(pen={"color": A_COLOR, "width": 1})
        self.spec_b = pg.PlotCurveItem(pen={"color": B_COLOR, "width": 2})
        self.spec.addItem(self.spec_a)
        self.spec.addItem(self.spec_b)
        right.addWidget(self.spec, 2)

        self.chips = QHBoxLayout()
        self.chips.addWidget(QLabel("热点："))
        right.addLayout(self.chips)

        self.stats_label = QLabel("—")
        right.addWidget(self.stats_label)
        root.addLayout(right, 3)

    # ------------------------------------------------------------- actions ----
    def choose_file(self) -> None:
        path, _ = QFileDialog.getOpenFileName(self, "选择歌曲", str(Path.home()),
                                             "Audio (*.mp3 *.wav *.flac *.ogg *.opus *.m4a *.webm *.aac)")
        if path:
            self.load(path)

    def dragEnterEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls and Path(urls[0].toLocalFile()).suffix.lower() in AUDIO_EXTS:
            event.accept()
        else:
            event.ignore()

    def dropEvent(self, event) -> None:
        urls = event.mimeData().urls()
        if urls:
            self.load(urls[0].toLocalFile())

    def load(self, path: str | Path) -> None:
        path = Path(path)
        self.current_path = path
        self.file_label.setText(path.name)
        self.progress_label.setText("正在分离人声 / 配乐…（首次运行会下载模型）")
        self.separation = SeparationWorker(path, self.model, self.device)
        self.separation.progress.connect(lambda p, msg: self.progress_label.setText(f"{msg} {p:.0f}%"))
        self.separation.done.connect(self._on_project)
        self.separation.failed.connect(lambda msg: self.progress_label.setText(f"分离失败：{msg}"))
        self.separation.start()

    def _fix(self) -> None:
        """Apply the chosen preset and render the preview. Preset changes alone
        do not render — this button is the thing that does the work."""
        if self.current_path is None:
            self.progress_label.setText("先选择或拖入一首歌曲")
            return
        if self.project is None:
            if self.separation is None or not self.separation.isRunning():
                self.progress_label.setText("正在分离人声 / 配乐…（首次运行会下载模型）")
                self.load(self.current_path)
            else:
                self.progress_label.setText("分轨进行中，完成后自动预览")
            return

        name = self.preset_combo.currentText()
        if name != self.applied_preset:
            self.params = copy.deepcopy(PRESETS[name])
            self._sync_knobs()
        self.applied_preset = name
        self.dirty = False
        self._flag_fix_button()
        self.progress_label.setText(f"应用「{name}」，渲染预览…")
        self._start_render()

    def _flag_fix_button(self) -> None:
        if self.dirty:
            self.fix_button.setText("⚡ 应用预设并预览")
            self.fix_button.setStyleSheet(
                "font-weight: bold; padding: 8px; background:#ffd34d; color:#1b1b1b;"
            )
        else:
            self.fix_button.setText("⚡ 一键修复")
            self.fix_button.setStyleSheet("font-weight: bold; padding: 8px;")

    def keyPressEvent(self, event) -> None:
        key = event.key()
        if key == Qt.Key.Key_Space:
            if self.player.playing:
                self.player.stop()
                self._mark_ab()
            else:
                self._play(self.ab)
        elif key == Qt.Key.Key_A:
            self._play("A")
        elif key == Qt.Key.Key_B:
            self._play("B")
        elif key in (Qt.Key.Key_Left, Qt.Key.Key_Right):
            if self.region and self.player.data is not None:
                step = 1.0 if key == Qt.Key.Key_Right else -1.0
                rel = self.player.position_sec() + step
                rel = min(max(rel, 0.0), self.player.duration_sec() - 0.01)
                self.player.seek(rel)
                self._update_playhead()
        else:
            super().keyPressEvent(event)

    def _on_project(self, project: Project) -> None:
        self.project = project
        self.player.set_samplerate(project.sr)
        self.stats = analyze(project.vocal, project.music, project.sr) if project.has_stems else {}
        name = self.preset_combo.currentText()
        self.params = copy.deepcopy(PRESETS[name])
        self.applied_preset = name
        self.dirty = False
        self._flag_fix_button()
        self._sync_knobs()
        self._set_region(*self._default_region())
        self._build_chips()
        self.progress_label.setText(f"分轨完成，自动预览（{name}）…")
        self._start_render()

    def _set_region(self, start: float, end: float) -> None:
        """Preview window: spin range follows the track, playback resets."""
        total = int(self.project.original.shape[0] / self.project.sr) if self.project else 600
        self.region_start.setRange(0, total)
        self.region_end.setRange(0, total)
        start = min(max(0.0, float(start)), max(0.0, total - 1.0))
        end = min(float(end), float(total))
        if end <= start:
            end = min(float(total), start + 10.0)
        self.region = (start, end)
        self.region_start.setValue(int(start))
        self.region_end.setValue(int(end))
        self.player.stop()
        self.player.pos = 0
        self.playhead.setPos(start)

    def _default_region(self) -> tuple[float, float]:
        total = self.project.original.shape[0] / self.project.sr
        regions = self.stats.get("regions", {})
        spots = [r["time"] for r in regions.get("overlap", [])] + [r["time"] for r in regions.get("sibilance", [])]
        if spots:
            t = max(0.0, min(spots) - 5.0)
            return (t, min(total, t + 30.0))
        return (0.0, min(total, 30.0))

    def _build_chips(self) -> None:
        while self.chips.count() > 1:
            item = self.chips.takeAt(1)
            if item.widget():
                item.widget().deleteLater()
        for kind, regions in self.stats.get("regions", {}).items():
            for r in regions[:3]:
                label = "齿音" if kind == "sibilance" else "频段冲突"
                button = QPushButton(f"{label} @ {r['time']:.1f}s")
                button.clicked.connect(lambda _, t=r["time"]: self._jump(t))
                self.chips.addWidget(button)

    def _jump(self, t: float) -> None:
        self._set_region(max(0.0, t - 6.0), max(0.0, t - 6.0) + 20.0)
        self._start_render()

    def _knob_changed(self, key: str, raw: int) -> None:
        setattr(self.params, key, raw / 100.0)
        for k, _, label, _, _, _ in self.knobs:
            if k == key:
                label.setText(f"{getattr(self.params, key):.2f}")
        self._start_render()

    def _sync_knobs(self) -> None:
        for key, slider, label, _, _, _ in self.knobs:
            slider.setValue(int(getattr(self.params, key) * 100))
            label.setText(f"{getattr(self.params, key):.2f}")

    def _preset_changed(self, index: int) -> None:
        """Selecting a preset only loads its knobs; the ⚡ button applies it."""
        name = self.preset_combo.itemText(index)
        self.params = copy.deepcopy(PRESETS[name])
        self._sync_knobs()
        self.dirty = True
        self._flag_fix_button()
        if self.project is not None:
            self.progress_label.setText(f"已选择「{name}」 — 点击 ⚡ 一键修复 预览")

    def _start_render(self) -> None:
        if self.project is None:
            return
        if self.render_thread is not None and self.render_thread.isRunning():
            self.pending_render = True
            return
        start, end = self.region or (None, None)
        self.render_thread = RenderWorker(self.project, self.params, start, end)
        self.render_thread.done.connect(self._on_result)
        self.render_thread.start()

    def _on_result(self, result: RenderResult) -> None:
        self.result = result
        self._draw()
        self._update_stats()
        self.progress_label.setText("预览就绪 — 改参数即时重算 (A/B 键切换，空格播放/停止)")
        if self.pending_render:
            self.pending_render = False
            self._start_render()

    def _draw(self) -> None:
        if self.result is None or self.project is None:
            return
        sr = self.project.sr
        start, end = self.region or (0.0, self.project.original.shape[0] / sr)
        a = self.project.original[int(start * sr):int(end * sr)]
        b = self._source(self.result)

        lo_a, hi_a = envelope(a)
        x_a = np.arange(len(hi_a)) * (len(a) / len(hi_a)) / sr + start
        self.curve_a_hi.setData(x_a, hi_a)
        self.curve_a_lo.setData(x_a, lo_a)

        lo_b, hi_b = envelope(b)
        x_b = np.arange(len(hi_b)) * (len(b) / len(hi_b)) / sr + start
        self.curve_b_hi.setData(x_b, hi_b)
        self.curve_b_lo.setData(x_b, lo_b)

        fa, da = spectrum(a, sr)
        fb, db = spectrum(b, sr)
        self.spec_a.setData(fa, da)
        self.spec_b.setData(fb, db)
        self.wave.setRange(xRange=(start, end))

    def _source(self, result: RenderResult | None) -> np.ndarray:
        start, end = self.region or (0.0, self.project.original.shape[0] / self.project.sr)
        if self.ab == "A" or result is None:
            return self.project.original[int(start * self.project.sr):int(end * self.project.sr)]
        return {"mix": result.mix, "vocal": result.vocal, "music": result.music}[self.solo]

    def _solo_changed(self, index: int) -> None:
        """Solo is instant: the waveform and the audition both follow it."""
        self.solo = {"混合": "mix", "人声": "vocal", "配乐": "music"}[self.solo_combo.itemText(index)]
        if self.result is None:
            return
        if self.solo != "mix" and self.ab == "A":
            self.ab = "B"  # the original has no stems to solo
        self._draw()
        if self.player.playing:
            self.player.set_audio(self._source(self.result))
        self._mark_ab()
        self.progress_label.setText(f"Solo：{self.solo_combo.currentText()}（即时切换）")

    def _region_changed(self) -> None:
        self._set_region(float(self.region_start.value()), float(self.region_end.value()))
        self._start_render()

    def _play(self, version: str) -> None:
        """▶ / ■ toggle: pressing the version already playing stops it."""
        if self.project is None:
            self.progress_label.setText("先选择歌曲")
            return
        if self.player.playing and self.ab == version:
            self.player.stop()
            self._mark_ab()
            self.progress_label.setText("已停止（再点一次继续）")
            return

        self.ab = version
        data = self._source(self.result)
        if data is None or len(data) == 0:
            self.progress_label.setText("还没有预览 — 先点 ⚡ 一键修复")
            return
        self.player.set_audio(data)
        self.player.set_loop(0.0, None)  # the array *is* the preview region
        pos = self.player.position_sec()
        if not (0.0 <= pos < self.player.duration_sec()):
            pos = 0.0
        if self.player.play(pos):
            self.progress_label.setText(
                f"试听 {version} · 空格播放/停止，A/B 切换，←/→ 移动播放头"
            )
        else:
            self.progress_label.setText(self.player.error or "音频输出不可用，试听不可用")
        self._mark_ab()

    def _mark_ab(self) -> None:
        for button, label, name in ((self.play_a, "A", "原始"), (self.play_b, "B", "修复")):
            if self.player.playing and self.ab == label:
                button.setText(f"■ {label} {name}")
                button.setStyleSheet("background:#2b7f57; color:white;")
            else:
                button.setText(f"▶ {label} {name}")
                button.setStyleSheet("")

    def _update_playhead(self) -> None:
        if self.region is None:
            return
        dur = self.player.duration_sec()
        if dur <= 0:
            return
        self.playhead.setPos(self.region[0] + min(self.player.position_sec(), dur))

    def _update_stats(self) -> None:
        if self.result is None:
            return
        stems = "已分轨" if self.project.has_stems else "整轨模式(无分轨)"
        self.stats_label.setText(
            f"{stems} · 响度 {self.result.lufs_before:.1f} → {self.result.lufs_after:.1f} LUFS · "
            f"峰值 {self.result.peak_before_db:.1f} → {self.result.peak_after_db:.1f} dBFS · "
            f"人声/配乐 {self.result.vocal_ratio_db:.1f} dB"
        )

    def do_export(self) -> None:
        if self.project is None:
            self.progress_label.setText("先选择歌曲并点击一键修复")
            return
        fmt = self.format_combo.currentText()
        self.progress_label.setText(f"整曲渲染并导出 .{fmt}…（约几秒）")
        self.export_thread = ExportWorker(self.project, self.params, fmt)
        self.export_thread.done.connect(lambda out: self.progress_label.setText(f"已导出：{out}"))
        self.export_thread.failed.connect(lambda msg: self.progress_label.setText(f"导出失败：{msg}"))
        self.export_thread.start()

    def close(self) -> None:
        self.player.stop()
        self.player.close()
        super().close()


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Beautiful Singing Voice GUI")
    parser.add_argument("files", nargs="*", help="audio file(s) to open immediately")
    parser.add_argument("--model", default="htdemucs_ft", help="demucs model name")
    parser.add_argument("--device", default=None, help="cuda or cpu (default: auto-detect)")
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    app = QApplication([])
    window = StudioWindow(model=args.model, device=args.device)
    window.show()
    if args.files:
        window.load(args.files[0])
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
