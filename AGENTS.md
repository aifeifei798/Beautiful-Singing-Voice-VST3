# AGENTS.md

给在本仓库里干活的编码代理看的说明书。人类读者请看 [README.md](README.md)。

## 项目是什么

Beautiful Singing Voice（BSV）是一个修复生成式音乐（Suno 等）的桌面工具：丢入一首歌，
用 Demucs 分成人声与配乐，各自过一条 DSP 链，再合成、限幅、响度归一到 −14 LUFS 导出。
同一套处理逻辑还有一个 JUCE 写的 VST3，可以挂在 DAW 轨道上。

两个部分共用一套参数语义，但代码是两份（Python / C++），改动时要同时考虑。

## 常用命令

```bash
# 环境（首次）
./install.sh                      # venv + 依赖 + 预下载模型 + 自检 + 跑测试
source .venv/bin/activate

# 应用
./run.sh                          # GUI
./run.sh cli song.flac --preset "中性 (只修问题)"
.venv/bin/python -m bsv.cli --list-presets
.venv/bin/python -m bsv.cli demo/demo_30.wav -o /tmp/out.wav --device cpu

# 测试与基准
.venv/bin/python -m pytest -q tests
.venv/bin/python scripts/bench_render.py demo/demo_30.wav

# 插件
./plugin/build.sh                 # 编译 + 安装到 ~/.vst3
./plugin/build.sh --package       # 顺便打 release zip 到 dist/
.venv/bin/python plugin/verify.py # 黑盒校验 EQ / limiter / 侧链 / doubling
plugin/build/BSVHost_artefacts/Release/BSVHost "~/.vst3/Beautiful Singing Voice.vst3" --list

# 发版
git tag v0.1.1 && git push origin v0.1.1   # CI 自动编译、冒烟测试、挂 Release
```

无显示器环境跑 GUI 或宿主，用 `xvfb-run -a`。

## 代码地图

| 路径 | 职责 |
| --- | --- |
| `bsv/audio.py` | ffmpeg 输入规范化（任意格式 → 44.1 kHz 立体声 WAV）、导出 |
| `bsv/separate.py` | Demucs sidecar 子进程、显存规划、OOM 回退、分轨缓存 |
| `bsv/filters.py` | RBJ / 预畸变 biquad 系数。**与 `plugin/Source/Dsp.h` 一一对应** |
| `bsv/dsp.py` | de-clip、de-esser、sidechain duck、doubling、reverb、LUFS、链构建 |
| `bsv/analysis.py` | 齿音热点、人声/配乐频段冲突检测 |
| `bsv/presets.py` | `Params` 默认值与预设表。**参数的唯一事实来源** |
| `bsv/pipeline.py` | `open_project()` / `Project.render()` / `export()` |
| `bsv/cli.py` | 命令行入口 |
| `bsv/ui/app.py` | PyQt6 主窗口（4 步流程、A/B、Solo、导出） |
| `bsv/ui/player.py` | 可 seek 的双版本播放器（sounddevice） |
| `plugin/Source/Dsp.h` | Python DSP 的 C++ 移植：biquad、压缩、ducker、doubling、limiter |
| `plugin/Source/PluginProcessor.cpp` | APVTS 参数、预设、总线/侧链、模式分发 |
| `plugin/Source/PluginEditor.cpp` | 深色界面，模式按钮 + 旋钮矩阵 |
| `plugin/Tools/Host.cpp` | 无界面测试宿主（`--list` / `--set` / `--sidechain` / `--snapshot`） |
| `plugin/verify.py` | 把插件当黑盒，与 Python 频响对拍；失败退出码非 0 |

`demo/demo_30.wav` 是标准测试素材。

## 不变量（改之前先想清楚）

- **时钟固定 44.1 kHz**。所有 stem 与中间结果都重采样到工程采样率；不要引入第二个
  时间基准，否则会变调。任何处理都不得改变音高与速度。
- **分轨缓存**在 `~/.cache/bsv/stems/<sha256>/<model>-f32/`。缓存键只跟输入文件与模型
  有关，改 DSP 参数不会重跑模型 —— 这是特性，不要"优化"掉。
- **参数默认值只有一处**：`bsv/presets.py` 的 `Params`。插件的 `kPresets` 是它的镜像，
  改任何默认值或预设都要两边同步，并跑 `plugin/verify.py`。
- 默认必须是**中性修复**：混响关（`space=0`，保留原空间感）、加厚开（每层 −20 dB）、
  预设 `中性 (只修问题)`。
- **插件延迟恒为 240 采样 @ 48 kHz**（5 ms 前瞻）。三种模式都一样，切换模式不许改延迟。
- CUDA 分轨**不保证逐位可复现**（stem 差异量级 1e-2）。需要确定性时用 `BSV_DEVICE=cpu`。
- 插件里的非 ASCII 字面量**必须**走 `plugin/Source/Text.h` 的 `u8()`。
  `juce::String(const char*)` 在 Linux 上按 Latin-1 解释，中文会变乱码。

## 修改指引

**改音色 / 加参数**：`bsv/presets.py` 加字段 → `bsv/dsp.py` 使用 → `bsv/ui/app.py` 加控件
→ `bsv/cli.py` 加开关 → `plugin/Source/{Dsp.h,PluginProcessor,PluginEditor}` 同步 →
`plugin/verify.py` 的 `RANGES` 补范围。

**改分轨**：只动 `bsv/separate.py`。显存规划按可用 VRAM 选 `segment`，
OOM 阶梯是 `cuda → cuda --segment 4 → cpu`，不要删掉任何一级。

**改 UI**：`bsv/ui/app.py` 是单文件窗口，`player.py` 只负责播放。预览只渲染当前区间
（默认 30 秒或检测到的热点），导出才渲染整曲 —— 别把整曲渲染塞进滑块回调。

**改插件 DSP**：先改 Python，用 `scripts/bench_render.py` 与测试确认听感/指标，
再 1:1 移植到 C++，最后 `plugin/verify.py` 对拍。两个实现分叉是主要 bug 来源。

## 测试

- `pytest` 共 48 个用例，覆盖滤波系数、DSP 数值、流水线时长不变、CLI、播放器、
  分轨规划。改动后必须全绿。
- 时长/音高不变是硬指标：`tests/test_pipeline.py` 会检查输出采样数与输入一致。
- 插件没有单元测试框架，靠 `plugin/verify.py`（EQ 误差 < 0.35 dB、limiter 峰值 ≤ −0.9 dBFS、
  侧链闪避生效、doubling 音高漂移 < 2 cents、无 NaN/DC）和 `Host.cpp` 冒烟。
- 提交前跑：`pytest` + `./plugin/build.sh` + `plugin/verify.py`。

## 约定

- 每个源文件头两行：`# Copyright 2026 Feifei` + SPDX。Python / shell 为
  `GPL-3.0-only`；`plugin/Source/`、`plugin/Tools/` 为 `AGPL-3.0-or-later`（JUCE 要求）。
  新增文件必须带同样的头。
- 代码标识符英文；界面文案、注释、文档中文。注释解释"为什么"，不复述代码。
- 提交信息用英文、祈使句、一行标题 + 需要时正文。不要把 `dist/`、`build/`、`.venv/`、
  `*_fixed.wav` 提交进去（已在 `.gitignore`）。
- 不要凭猜测改许可证。主项目 GPL-3.0，插件 AGPL-3.0，原因见 README。

## 环境备注

- venv 在 `.venv`，用 `uv` 创建；直接 `pip install` 也可以，但 `install.sh` 是标准路径。
- 分轨需要 `ffmpeg`、`torch`、`demucs`；没有这些时应用退化为整轨处理（`--no-separate`）。
- 编译插件需要 CMake ≥ 3.22、Ninja、X11/ALSA/freetype/fontconfig/GL/curl 开发包；
  JUCE 默认在 `~/develop/JUCE`，可用 `JUCE_DIR` 覆盖，`build.sh` 会按 8.0.12 clone。
- Release 由 GitHub Actions 在 Ubuntu 22.04 上构建（glibc ≥ 2.35）。
  本机是 24.04，编出来的二进制**不能**给旧发行版用 —— 要发版请走 tag + CI。
