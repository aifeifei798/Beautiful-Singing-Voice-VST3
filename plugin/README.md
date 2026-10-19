# Beautiful Singing Voice — VST3

把桌面版那套"修人声"的处理做成插件，直接挂在 DAW 的轨道上。不用先分离、不用导出、
不用切软件，播放到哪就修到哪。

- 三种模式：**母带 / 整轨**、**人声**、**配乐**
- 9 个旋钮，7 个预设，全部可被宿主自动化、随工程保存
- 侧链闪避：人声一来，伴奏自动让位
- 无采样率限制，44.1 / 48 / 88.2 / 96 kHz 都可以

## 为什么必须选模式

插件看不到"你把它挂在哪条轨上"——宿主只告诉它来了一段立体声。挂在人声轨上却按整轨
的方式处理，会把人声压扁；挂在 master 上却按人声去加厚，整首歌都会糊。所以模式得由你
告诉它。

默认是 **母带 / 整轨**，这是最安全的默认值：挂错了也只是轻度打磨，不会毁掉工程。

| 模式 | 挂在哪 | 做什么 | 不做什么 |
| --- | --- | --- | --- |
| 母带 / 整轨 | master | 去毛刺、低频清理、临场/空气（60% 深度）、轻压缩、真峰值限制 | 不闪避、不加厚、不去齿音 |
| 人声 | 人声轨 | 去毛刺、双段低频清理、暖色、临场、空气、去齿音、压缩、加厚 | 不闪避、不限制 |
| 配乐 | 伴奏总线 | 去毛刺、低频清理、250–4 kHz 侧链闪避 | 不加临场/空气、不加厚 |

配乐模式下如果没接侧链，闪避自动不生效——插件不会去猜"这段里有没有人声"。界面底部会
显示"侧链：未连接"。

## 参数

| 参数 | 范围 | 默认 | 生效模式 |
| --- | --- | --- | --- |
| 模式 | 母带 / 人声 / 配乐 | 母带 | — |
| 预设 | 自定义 + 7 套 | 中性 | — |
| 低频清理 | −6 … 0 dB | −2.5 | 全部 |
| 临场感 | 0 … 6 dB | 2.0 | 人声、母带 |
| 空气感 | 0 … 4 dB | 1.5 | 人声、母带 |
| 齿音抑制 | 0 … 1.2 | 0.7 | 人声 |
| 压缩比 | 1 … 3 | 1.3 | 人声、母带 |
| 加厚 | −60 … −6 dB | −14 | 人声 |
| 闪避 | 0 … 10 dB | 3.0 | 配乐 |
| 输出增益 | −12 … +12 dB | 0 | 全部 |
| 峰值上限 | −6 … 0 dB | −1.0 | 母带 |

预设与桌面版 `bsv/presets.py` 一一对应（中性、中文流行、K-pop、EDM、Rock、Lo-fi、美式）。
选预设会把上面这些旋钮一起推过去；之后手动拧旋钮，预设名不会自动变回"自定义"。

浅灰的旋钮表示当前模式用不到它，拧了也没反应。

## 和桌面版的区别

插件里没有 Demucs——宿主不会给你一次几秒的空档去跑分离模型。所以它做的是**分离之后**
的那一半：拿到已经分开的人声或伴奏，把每一段修好。

| | 桌面版 | 插件 |
| --- | --- | --- |
| 分离 | Demucs（GPU） | 不做，由你或宿主负责 |
| 响度归一 | 有（目标 LUFS） | 不做，母带电平归 DAW |
| 齿音 | 6.5 kHz 频段，阈值跟随人声能量 | 同样的做法 |
| 压缩 | pedalboard Compressor | 自写软拐点压缩，行为接近但非逐采样一致 |
| 加厚 | 固定速率重采样，越走越偏 | 慢速三角波调制延迟，音高偏移同样是 ±0.45%，但不会漂到缓冲区外面 |
| 限制器 | 导出时归一 | 只在母带模式压 −1 dBFS 真峰值 |

EQ 部分是按 `bsv/filters.py` 的同一套 RBJ / 预畸变双二阶抄过来的，不是"听起来差不多"
的近似——`plugin/verify.py` 会把实测频响和 Python 的预测逐点比对。

## 构建

需要 CMake ≥ 3.22、C++17 编译器，以及下面这些开发包（Ubuntu）：

```bash
sudo apt-get install -y build-essential cmake ninja-build \
    libasound2-dev libfreetype-dev libfontconfig1-dev libgl1-mesa-dev \
    libcurl4-openssl-dev libx11-dev libxrandr-dev libxinerama-dev \
    libxcursor-dev libxcomposite-dev
```

JUCE 不放进仓库（112 MB）。`build.sh` 会自己 clone 到 `~/develop/JUCE`，也可以用
`JUCE_DIR` 指定已有副本：

```bash
./plugin/build.sh
```

产物：

```
~/.vst3/Beautiful Singing Voice.vst3        # 插件，宿主重启后可见
plugin/build/.../Standalone/...             # 独立程序，不装 DAW 也能试听
plugin/build/BSVHost_artefacts/Release/BSVHost   # 无界面测试宿主
```

## 验证

```bash
.venv/bin/python plugin/verify.py
```

它把插件当成黑盒，用无界面宿主跑几段信号，检查：

- **频响**：白噪声过插件，实测传递函数与 `bsv/filters.py` 的预测差 < 0.35 dB
- **限制器**：−1 dB 上限下，+3 dBFS 的正弦输出不越过 −1 dBFS
- **侧链闪避**：人声进来时 250–4 kHz 掉 7 dB 以上；没接侧链时一度都不掉
- **加厚的音高**：440 Hz 纯音过一遍，基频偏差 < 2 音分

```
vocal   EQ error: max 0.239 dB at 6471 Hz  [ok]
master  EQ error: max 0.239 dB at 6471 Hz  [ok]
limiter peak -1.00 dBFS at a -1 dB ceiling  [ok]
sidechain duck -7.3 dB in 250-4k while the vocal plays  [ok]
no sidechain, no duck: +0.0 dB  [ok]
doubling pitch drift -0.7 cents  [ok]
PASS
```

单条 230 秒的轨道，实测处理耗时 0.6–1.3 秒（185–376 倍实时，单线程），CPU 占用可以忽略。

## 接侧链

配乐模式的闪避需要宿主把**人声**送进插件的第二个输入：

- **Reaper**：在插件窗口右上角点 `2 in 2 out` → 把 I/O 的 `3/4` 指向人声轨
- **Cubase / Nuendo**：插件面板顶部的侧链按钮，选人声轨
- **Studio One**：插件窗口上方"侧链"下拉框
- **Ableton**：需要把插件放进 Effect Rack，用 Rack 的侧链输入
- **Logic**：侧链菜单在插件窗口顶部

接上后插件底部会变绿显示"侧链：已连接"。

## 延迟

母带模式的真峰值限制器有 5 ms 前瞻，所以插件固定上报 240 采样 @ 48 kHz（5 ms）。
另外两种模式不压限，但仍然走同一条延迟线——延迟值不随模式变化，宿主不需要为切模式
重新计算延迟补偿。

## 许可

主项目是 **GPL-3.0-only**，但 `plugin/` 下的 C++ 代码是 **AGPL-3.0-or-later**（见 `plugin/LICENSE`），
因为它链接 JUCE 8，而 JUCE 8 是 AGPLv3 / 商业双许可，没有 GPL 选项。AGPL 比 GPL 更严，
所以这一块不能降级成 GPL-3.0。

要闭源分发这个插件，需要向 JUCE 购买商业许可。
`plugin/verify.py` 是纯 Python，不链接 JUCE，跟随主项目的 GPL-3.0。
