# Beautiful Singing Voice (BSV)

一键把 Suno / 生成式音乐导出的人声和配乐修到更专业的桌面工具。
PyQt6 图形界面，也有命令行模式。不需要 DAW。

## 它做什么

```
丢入歌曲 (.mp3 / .flac / .wav / .webm …)
   │  自动转成 44.1 kHz 立体声 WAV
   ▼
Demucs 分轨 (htdemucs_ft) → 人声 stem + 其余 stem   （结果按文件 sha256 缓存）
   ▼
人声链:  de-clip → 浑浊清理 → warmth/presence/air → de-esser → 轻压缩 → 加厚 (doubling) → 混响（默认 0）
配乐链:  低频清理 → 以人声为侧链的 250–4 kHz 动态闪避 (duck)
   ▼
合成 + limiter + 响度归一 (-14 LUFS) → 导出
```

UI 里只有 4 步：丢文件 → 选预设 → 一键修复 → 微调导出。
预览区间 + A/B 切换 + Solo（人声 / 配乐 / 混合）让你在同一时间点对比原始与修复版本。

## 性能

分轨现在跑在 GPU 上：`htdemucs_ft` 在 RTX 5090 D 上分离一首 4 分钟的歌约 **13 秒**（约 18 倍实时），峰值显存 ~2.2 GB；结果按文件缓存，之后 0.01 秒读回。

| 环节 | 一首 4 分钟的歌 |
| --- | --- |
| 分轨（首次，GPU） | ~13 s |
| 分轨（缓存命中） | ~0.01 s |
| 整曲 DSP 渲染 + 导出 | ~5 s |
| 30 秒预览区间 | ~0.6 s |

DSP 渲染全部走 numpy/scipy 的 biquad（不是 pedalboard 的逐样本插件），并且按 262k 采样分块处理，所以整曲渲染不随系统内存压力抖动 —— 改滑块能即时重算。

```bash
.venv/bin/python scripts/bench_render.py demo/demo_30.wav      # 分阶段计时
```

## 安装

```bash
cd Beautiful-Singing-Voice-VST3
./install.sh                 # 建 venv + 装依赖 + 预下载分轨模型 + 自检
```

常用开关：

```bash
./install.sh --model htdemucs      # 更小更快的模型（84 MB，单文件）
./install.sh --no-models           # 只装依赖，模型首次运行时再下
./install.sh --clean               # 删掉 .venv 重装
./install.sh --python 3.12         # 指定 Python 版本
```

分轨需要 `demucs` + `torch`。工具会读显存余量再决定怎么跑：默认整块分段；余量偏紧时自动缩小分段（更慢，结果一样）；只有真的放不下才退回 CPU。显存被本地 LLM 占着也能用 GPU —— 模型权重只要 ~2.2 GB，不必等卡空出来。也可以强制指定：

```bash
BSV_DEVICE=cpu ./run.sh song.mp3       # 强制 CPU（约 1.4 倍实时）
BSV_DEVICE=cuda ./run.sh song.mp3      # 强制 GPU（显存不够会自己降级重试）
./run.sh cli song.mp3 --device cpu
```

`./install.sh` 结束时会打印一次自检，例如 `separation plan: cuda (free VRAM 31001 MiB)`。

没有分轨时工具仍然可用，只是退回"整轨打磨"模式。

## 用法

最省事：

```bash
./run.sh                 # 首次自动建 venv、装依赖、预下载模型，然后打开界面
./run.sh "song.mp3"      # 直接加载一首
./run.sh cli song.mp3 --preset 中文流行   # 命令行模式
```

图形界面：

```bash
bsv-ui                      # 或 .venv/bin/python -m bsv.ui.app
bsv-ui song.mp3             # 直接加载一首
bsv-ui --model htdemucs song.mp3
```

命令行：

```bash
bsv song.mp3 --preset 中文流行
bsv song.mp3 --preset EDM --vocal-gain 1.5 --duck 5 --lufs -13
bsv a.mp3 b.flac c.webm --format flac        # 批量
bsv --list-presets
```

预设：`中性 (只修问题)`（**默认**） / `中文流行` / `K-pop ballad` / `EDM / 电子流行` / `Rock` / `Lo-fi / 氛围` / `美式流行`

命令行可以只写简称（`--preset 中性`、`--preset EDM`），只要不产生歧义。

**加厚 (doubling) 默认开**，每个预设的力度不同：中性 −14 dB，中文流行 / Rock −12，美式流行 −11，K-pop −10，EDM −9，Lo-fi −16。实现是 3 层带限（220 Hz–7.5 kHz）、微失谐（±0.45%）、延迟 18 / 25 / 36 ms 的复制，所以是"身体感"而不是回声；滑块拉到 −60 dB 即关闭。混响仍然是 0，要自己推。

−14 dB 是实测挑出来的：在真实人声 stem 上，它让 200–900 Hz 的"身体"升 +0.33 dB、整体只升 +0.27 dB，与原唱的相关度还有 0.958 —— 听得出来更厚，但还是同一个人。再往上（−10 dB）身体感 +0.85 dB，就开始像加了一层人声了。

## 试听 / A-B

- 拖入歌曲 → 分轨完成后自动用「中性」预览一次（分轨按文件缓存，第二次秒开）
- 换预设只改旋钮，**点 ⚡ 一键修复 才渲染**；改旋钮则即时重算预览
- `▶ A 原始` / `▶ B 修复` 是同一时间点的对比，Solo 切 混合 / 人声 / 配乐
- 空格 = 播放/停止，`A` / `B` = 直接切换版本，`←` / `→` = 移动播放头
- 热点按钮（齿音 / 频段冲突）点击后把预览区间移到那里

## VST3 插件

同一套修复逻辑也做成了 VST3，直接挂在 DAW 轨道上，不用先分离再导出。

不想自己编译的话，直接下载编译好的：[Releases](https://github.com/aifeifei798/Beautiful-Singing-Voice-VST3/releases)。

```bash
# 用现成的（Actions 在 Ubuntu 22.04 上构建，glibc >= 2.35）
unzip Beautiful-Singing-Voice-0.1.0-linux-x86_64.zip -d ~/.vst3/

# 或者自己编译（首次会自动 clone JUCE，产物在 ~/.vst3/）
./plugin/build.sh

# 编译并打出和 Release 一样的 zip 到 dist/
./plugin/build.sh --package
```

发布走 CI：`.github/workflows/release.yml` 在推 `v*` tag 时自动编译、冒烟测试
（确认 12 个参数能枚举出来）、打包并挂到对应 Release 上。手动补一个版本：

```bash
gh workflow run release-plugin -f tag=v0.1.0
```

它必须让你选模式：插件不知道自己被挂在哪条轨上，宿主只告诉它"来了一段立体声"。

| 模式 | 挂在哪 | 说明 |
| --- | --- | --- |
| **母带 / 整轨**（默认） | master | 温和打磨 + −1 dBFS 真峰值限制，挂错也不会毁工程 |
| 人声 | 人声轨 | 完整人声链 + 加厚 |
| 配乐 | 伴奏总线 | 低频清理 + 250–4 kHz 侧链闪避（需接侧链） |

插件的 EQ 与桌面版是同一套双二阶公式，`plugin/verify.py` 会把实测频响和 Python 的预测逐点对比（误差 < 0.35 dB）。细节、构建依赖、侧链接法见 [plugin/README.md](plugin/README.md)。

## 模型下载失败时

torch 的自动下载容易被代理截断（hash 校验失败 → demucs 直接报错）。手动预下载：

```bash
.venv/bin/python scripts/download_models.py --model htdemucs_ft
```

脚本会先尝试直连（`--noproxy`），失败再走代理，并且可断点续传，校验 sha256 前缀。

## 目录结构

```
bsv/
  audio.py      # 输入规范化 (ffmpeg → 44.1k stereo WAV) + 导出
  separate.py   # Demucs sidecar，结果缓存
  dsp.py        # de-clip / de-esser / sidechain duck / 响度 / 链构建
  analysis.py   # 齿音热点、人声与配乐频段冲突热点
  pipeline.py   # Project.render(params, start, end)
  cli.py        # 命令行
  ui/           # PyQt6 界面 + 可 seek 的播放器
tests/          # 合成音频的流水线测试
plugin/         # VST3（JUCE 8）：三种模式 + 侧链闪避，同一套 EQ
  Source/       #   Dsp.h / PluginProcessor / PluginEditor
  Tools/        #   Host.cpp —— 无界面测试宿主
  verify.py     #   把插件当黑盒，对拍 Python 的频响
```

## 说明与限制

- 分轨结果缓存在 `~/.cache/bsv/stems/<sha256>/<model>-f32/`，改参数不会重跑模型；stems 是 32-bit float（demucs 默认 16-bit，会掉精度）。
- 预览只渲染当前区间（默认 30 秒或检测到的热点），导出时才渲染整曲。
- 响度归一前后会分别测量，A/B 对比时两个版本都按同一目标响度，避免"更响 = 更好"的错觉。
- `.webp` 是图片格式，若你的导出真是 `.webp` 请先转成音频容器（工具会尝试 ffmpeg，失败即报错）。

## 许可证

本项目采用 **GNU General Public License v3.0**（GPL-3.0-only），见 [LICENSE](LICENSE)。每个源文件头部都有 SPDX 标记。

这意味着：你可以自由使用、修改、再分发，包括商用；但如果分发修改后的版本，需要同样以 GPL-3.0 公开源码。

第三方依赖各自保留原有许可证：Demucs（MIT）、numpy / scipy（BSD）、soundfile（BSD）、sounddevice（MIT）、pedalboard（GPL-3.0）、PyQt6（GPL-3.0 或商业授权）、PyTorch（BSD）。其中 pedalboard 和 PyQt6 本身就是 GPL-3.0，与本项目一致。

**`plugin/` 是例外，采用 AGPL-3.0-or-later**（见 [plugin/LICENSE](plugin/LICENSE)）：它链接 JUCE 8，而 JUCE 8 只有 AGPLv3 和商业许可两种选择，没有 GPL 选项。AGPL 比 GPL 更严——通过网络提供服务也算分发。若要让整个仓库统一成 GPL-3.0，只有两条路：向 JUCE 购买商业许可，或者不用 JUCE、直接基于 VST3 SDK（GPLv3 / Steinberg 双许可）重写插件。

### 分发编译好的插件时

AGPL 要求"给二进制的人也能拿到源码"。本仓库就是插件的完整源码；JUCE 未做任何修改，固定使用 8.0.12，可从 <https://github.com/juce-framework/JUCE> 取得（`plugin/build.sh` 里写死了版本号和地址）。发 GitHub Release 时，把 release 指向同一个 tag 即可满足要求。
