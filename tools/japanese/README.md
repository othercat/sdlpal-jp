# 日文转换工具

三个上游入口来自 [PalMusicFan/sdlpal v2026.08 Release](https://github.com/PalMusicFan/sdlpal/releases/tag/v2026.08)。初始导入逐字节保留附件，下载地址、GitHub asset ID、大小和 SHA256 记录于 [upstream.json](upstream.json)。后续差异通过独立提交追溯，原始导入提交记录在 [Issue #2](https://github.com/othercat/sdlpal-jp/issues/2)。

- `makemessage_j.py`：Win PC 根资源与土星提取文本生成 UTF-8 SLF。
- `steam_to_legacy.py`：Steam 的 JSON 文本容器转为 PC MSG/WORD 格式；它本身不进行土星日文映射。
- `rungui.py`：Tkinter 图形入口，调用前两个脚本。

上游仓库与本仓采用 [GPL v3](../../LICENSE)，`rungui.py` 内保留 SDLPal Community contributors 的 GNU GPL 声明，`makemessage_j.py` 保留 SDLPal Team、PalAlexx、OPL3ChipFan、Palxex 的署名。两个 CLI 附件未单独声明更具体的许可证版本；本次不改写其声明，也不重新许可。游戏资源仍由用户本地提供。

Agent 使用官方 CPython 3.11 的 `~/CodexTools/python`；三个脚本只依赖标准库，GUI 另外要求 Python 安装中包含 Tcl/Tk。当前映射表对应 Win 版，不能把生成文件当成 DOS 映射。
