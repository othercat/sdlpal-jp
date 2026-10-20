# 日文转换工具

三个上游入口来自 [PalMusicFan/sdlpal v2026.08 Release](https://github.com/PalMusicFan/sdlpal/releases/tag/v2026.08)。初始导入逐字节保留附件，下载地址、GitHub asset ID、大小和 SHA256 记录于 [upstream.json](upstream.json)。后续差异通过独立提交追溯，原始导入提交记录在 [Issue #2](https://github.com/othercat/sdlpal-jp/issues/2)。

- `makemessage_j.py`：Win PC 根资源与土星提取文本生成 UTF-8 SLF，默认包含 #3 恢复的 119 组映射。
- `steam_to_legacy.py`：Steam 的 UTF-16LE `编号:文本` 转为 PC MSG/WORD 格式；它本身不进行土星日文映射。
- `rungui.py`：Tkinter 图形入口，调用前两个脚本。

上游仓库与本仓采用 [GPL v3](../../LICENSE)，`rungui.py` 内保留 SDLPal Community contributors 的 GNU GPL 声明，`makemessage_j.py` 保留 SDLPal Team、PalAlexx、OPL3ChipFan、Palxex 的署名。两个 CLI 附件未单独声明更具体的许可证版本；本次不改写其声明，也不重新许可。游戏资源仍由用户本地提供。

Agent 使用官方 CPython 3.11 的 `~/CodexTools/python`；三个脚本只依赖标准库，GUI 另外要求 Python 安装中包含 Tcl/Tk。当前映射表对应 Win 版，不能把生成文件当成 DOS 映射。

## 审计：复现固定 Win 上游输出

[`verify_baseline.py`](verify_baseline.py)先检查 3 个 Win 输入、4 个土星输入的 SHA256，再调用当前转换器的 `--upstream-baseline` 模式，要求输出全文与上游指纹完全一致。JSON 同时记录当前和原始转换器指纹；不把修订后的脚本称为原始附件。它要求新的输出目录，拒绝改版资源、DOS、错误编码，以及输入目录内的输出。此模式仅用于历史对照，保留原有遗漏、错配和重复键。

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\verify_baseline.py 'PC资源目录' '土星提取目录' '新的产物目录'
```

Win 输入为 `SSS.MKF`、`M.MSG`、`WORD.DAT`，当前固定版本是 GBK 的 `PAL98_v1.72_20261014`。土星输入为 `JM.SEC`、`JM.NOR`、`JM.MSG`、`PROG.BIN`；消息为 Shift-JIS，PROG 中的索引/名称位置由上游脚本固定，不能替换为任意版本。文件名核对不区分大小写。

输出是 UTF-8 SLF 3.1。Windows 输出沿用上游 CRLF，其他平台比较统一为 LF 后的指纹；平台差异不当作正文差异。输出中的旧 CRC 注释直接沿用上游，其中部分字段引用不准确，输入身份以 JSON 的整文件 SHA256 为准。

## 当前 CLI 与 GUI

下面的直接 CLI 默认恢复 119 组遗漏，不包含 `verify_baseline.py` 的完整输入指纹和覆盖保护，输出路径需选择新的文件。恢复段的首尾脚本锚点不匹配时会中止。GUI 同样采用当前默认映射：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\makemessage_j.py 'PC资源目录' '土星提取目录' '新的输出.slf' gbk
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\rungui.py
```

GUI 选择 PC 目录、土星目录、输出文件和 GBK/BIG5。工具路径已相对脚本自身解析，不要求特定工作目录；子进程统一 UTF-8 输出。资源准备失败会停止，不会继续启动生成器。GUI 准备阶段会在所选 PC 目录创建缺失的 `M.MSG`/`WORD.DAT`，应选择工作副本。它没有原子事务：词表失败时，消息文件可能已经生成。

## Steam 文本入口

输入是**无 BOM 的 UTF-16LE** `编号:文本`，首个冒号分隔，`;` 开头为注释。GBK 对应 `MSG_chs.txt` / `WORD_chs.txt`，BIG5 对应 `MSG_cht.txt` / `WORD_cht.txt`。消息长度取自同版本 `SSS.MKF`，词条固定 10 字节，短内容补空格。`all` 的输出参数是已存在的独立目录：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\steam_to_legacy.py msg 'Steam文本目录' '新的M.MSG' gbk
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\steam_to_legacy.py word 'Steam文本目录' '新的WORD.DAT' gbk
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\steam_to_legacy.py all 'Steam文本目录' '已存在的独立输出目录' big5
```

本轮保留 Steam 转换算法及以下上游输入限制：BOM、空消息、缺失/稀疏/负编号没有完整拒绝机制，重复编号按最后一条覆盖，退出 0 不足以证明资源完整；失败也不会删除此前已有的输出。只使用编号完整、版本匹配的输入，并核对长度和输出指纹。CLI 无参数/参数不足退出 1 并显示用法，提示中的 `steam_msg_to_legacy.py` 是上游遗留旧名称，以本页命令为准。

已用合成小夹具验证 GBK/BIG5 和真实子进程，未对真实 Steam 文本整包作完整转换验收。

## 加载与验证

当前输出为 4,773 块 / 4,766 唯一键。生成上游对照和当前输出后，先运行独立资源校验：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\verify_restored_dialogues.py 'PC资源目录' '土星提取目录' '上游对照.slf' '当前输出.slf' '新的核对目录'
```

它从原始脚本重建运行时区间，核对全部 119 组正文、编号、CLEAR、首尾脚本与逐组审查记录，并要求旧输出逐字节保留、无新增重复键。生成的 `recovery-fixtures.csv` 可供 Test 引擎逐一读取全部 4,766 个键。详情见 [#3 恢复记录与源码图](../../docs/japanese-missing-dialogues.md)。

转换器没有内嵌 #5 的赤血蚕换行修改。上述映射校验完成后，使用生成 SLF 时继续执行已有适配步骤：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\adapt_red_silkworm_description.py '原始输出.slf' '新的适配输出.slf'
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tests\test_japanese_conversion_tools.py -v
```

历史工具结果、源码加载图与限制见 [#2 基线记录](../../docs/japanese-conversion-baseline.md)。GUI 回调测试不创建 Tk 窗口。按用户最新要求，所有子 Issue 的实现和专项验证完成后再统一实机验收。
