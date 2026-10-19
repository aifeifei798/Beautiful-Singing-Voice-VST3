编译好的 VST3，解压后把 `Beautiful Singing Voice.vst3` 整个文件夹放进 `~/.vst3/`：

```bash
unzip Beautiful-Singing-Voice-*-linux-x86_64.zip -d ~/.vst3/
```

然后重启 DAW，或让它重新扫描 VST3。`~/.vst3` 是隐藏目录。

## 三种模式

| 模式 | 挂在哪 | 做什么 |
| --- | --- | --- |
| **母带 / 整轨**（默认） | master | 温和打磨 + −1 dBFS 真峰值限制 |
| 人声 | 人声轨 | 完整人声链 + 加厚 |
| 配乐 | 伴奏总线 | 低频清理 + 250–4 kHz 侧链闪避 |

配乐模式不接侧链时，闪避自动不生效（界面会提示"侧链：未连接"）。

## 系统要求

- Linux **x86_64**，**glibc ≥ 2.35**（由 GitHub Actions 在 Ubuntu 22.04 上构建）
- libasound2、libfreetype、libfontconfig、libGL、libcurl、libX11、libXrandr、
  libXinerama、libXcursor、libXcomposite —— 桌面发行版一般都有

更老的系统请从源码编译：`./plugin/build.sh`。

延迟固定 240 采样 @ 48 kHz（5 ms），切换模式不变。

## 校验

压缩包旁边有 `.sha256` 文件：

```bash
sha256sum -c Beautiful-Singing-Voice-*-linux-x86_64.zip.sha256
```

## 源码

对应源码就是本仓库的同一个 tag。插件为 **AGPL-3.0-or-later**（JUCE 8 的要求），
桌面版 Python 部分是 **GPL-3.0-only**。
