# 日文转换工具

[#9 R3 特效证据](../../docs/japanese-portrait-effects.md)：
`verify_portrait_effects.py` 使用固定 Codex Python 3.11 环境内的 NumPy／Pillow，
独立核对实际特效帧的头像 RGB、背景索引、调色板和 SDL 纹理读回。
修前与修后使用相同 Test 入口；不是实机验收或土星硬件逐帧复刻。

三个上游入口来自 [PalMusicFan/sdlpal v2026.08 Release](https://github.com/PalMusicFan/sdlpal/releases/tag/v2026.08)。初始导入逐字节保留附件，下载地址、GitHub asset ID、大小和 SHA256 记录于 [upstream.json](upstream.json)。后续差异通过独立提交追溯，原始导入提交记录在 [Issue #2](https://github.com/othercat/sdlpal-jp/issues/2)。

- `makemessage_j.py`：Win PC 根资源与土星提取文本生成 UTF-8 SLF，默认包含 #3 恢复的 119 组映射、#4 的 10 组 NPC 修正，以及 #8 两个复用消息键的中性取得用语。
- `steam_to_legacy.py`：Steam 的 UTF-16LE `编号:文本` 转为 PC MSG/WORD 格式；它本身不进行土星日文映射。
- `rungui.py`：Tkinter 图形入口，调用前两个脚本。

上游仓库与本仓采用 [GPL v3](../../LICENSE)，`rungui.py` 内保留 SDLPal Community contributors 的 GNU GPL 声明，`makemessage_j.py` 保留 SDLPal Team、PalAlexx、OPL3ChipFan、Palxex 的署名。两个 CLI 附件未单独声明更具体的许可证版本；本次不改写其声明，也不重新许可。游戏资源仍由用户本地提供。

Agent 使用官方 CPython 3.11 的 `~/CodexTools/python`；转换脚本只依赖标准库，GUI 另外要求 Python 安装中包含 Tcl/Tk，源码图校验／导出需要 Pillow。`makemessage_j.py` 的映射表对应 Win 版，DOS 使用独立的 `makemessage_dos.py`，两者不能混用。

## 审计：复现固定 Win 上游输出

[`verify_baseline.py`](verify_baseline.py)先检查 3 个 Win 输入、4 个土星输入的 SHA256，再调用当前转换器的 `--upstream-baseline` 模式，要求输出全文与上游指纹完全一致。JSON 同时记录当前和原始转换器指纹；不把修订后的脚本称为原始附件。它要求新的输出目录，拒绝改版资源、DOS、错误编码，以及输入目录内的输出。此模式仅用于历史对照，保留原有遗漏、错配和重复键。

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\verify_baseline.py 'PC资源目录' '土星提取目录' '新的产物目录'
```

Win 输入为 `SSS.MKF`、`M.MSG`、`WORD.DAT`，当前固定版本是 GBK 的 `PAL98_v1.72_20261014`。土星输入为 `JM.SEC`、`JM.NOR`、`JM.MSG`、`PROG.BIN`；消息为 Shift-JIS，PROG 中的索引/名称位置由上游脚本固定，不能替换为任意版本。文件名核对不区分大小写。

输出是 UTF-8 SLF 3.1。Windows 输出沿用上游 CRLF，其他平台比较统一为 LF 后的指纹；平台差异不当作正文差异。输出中的旧 CRC 注释直接沿用上游，其中部分字段引用不准确，输入身份以 JSON 的整文件 SHA256 为准。

## 当前 CLI 与 GUI

下面的直接 CLI 默认恢复 119 组遗漏，并将 #4 的 10 组错套对白替换为经过校读的 Win 原文补译（没有确认对应的土星原段）。自 #7 起，CLI 也先检查固定 Win／土星输入指纹和 GBK 编码；DOS 和未审资源会停止。输出路径仍需选择新的文件，CLI 不提供完整的覆盖保护。恢复段首尾或 NPC 消息区间/脚本锚点不匹配时会中止。GUI 同样采用当前默认映射：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\makemessage_j.py 'PC资源目录' '土星提取目录' '新的输出.slf' gbk
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\rungui.py
```

`--before-tournament-fix` 仅重现 #3 完成后 / #4 修前输出；`--before-duplicate-fix` 重现 #4 完成后 / #8 修前输出；`--before-translation-fix` 重现 #8 完成后 / #6 R1 修前输出；`--before-translation-followup` 重现 #7 完成后 / #6 R2 修前输出（含 Win 版本标签）。它们与 `--upstream-baseline` 五者互斥，均用于历史审计，不能代替当前游戏用输出。

默认模式将两个复用取得键的所有出现统一为已有土星 `獲得` 句，并核对四个 Win/土星来源锚点；六个重复键的块与来源注释全部保留，其中四键原已同文。任一同键异文未经明确处理会报出区间和 Win 脚本并停止写文件，不再靠文件顺序静默决定用语。详见 [#8 来源、覆盖规则与源码图](../../docs/japanese-duplicate-message-keys.md)。

默认 CLI/GUI 也包含 [#6 的 18 组日译修订](../../docs/japanese-translation-review.md)：五组对白、三组物品、十组法术。逐组核对 Win/土星脚本、土星消息首尾和完整原文后替换；不匹配、重复目标或缺少目标均停止写入。源资源、人名、控制码与映射键不改。它是明确抽查条目的修正，不是全剧本审校。

默认输出还包含 [#6 R2 的四组修订](../../docs/japanese-translation-followup.md)，共六行，修正阿青指代、十赌九输、七步／行动禁令和陌生人范围。DOS 桥接同步复用这些正文，保留其独立消息键和专属说明；来源锚点及整文件版本保护继续生效。

GUI 选择 PC 目录、土星目录、输出文件和编码；当前已审 Win 映射要求 GBK，选择 BIG5 会收到明确错误。工具路径已相对脚本自身解析，不要求特定工作目录；子进程统一 UTF-8 输出。资源准备失败会停止，不会继续启动生成器。GUI 准备阶段在工作副本中创建缺失的 `M.MSG`/`WORD.DAT`：已有规范文件优先，否则复用所选编码缓存，缺缓存才转换。两类规范文件及新缓存先一起暂存，准备／发布失败时移除本轮新文件，保留已有文件。入口锁定本次输入并阻止日志刷新期间重入。准备成功后才启动独立的 SLF 生成阶段；该阶段失败不撤销已完成的准备。

## PAL_DOS 独立入口

DOS 按固定 CP950 资源生成，另需已审 Win 和土星资源复现共享译文。输出目录必须尚不存在且位于全部输入目录之外：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\makemessage_dos.py 'DOS资源目录' 'Win资源目录' '土星提取目录' '新的生成目录'
```

使用输出 `paljpn-dos.slf`；其中 4,476 键独立映射、5 条源标记显式保留，296 条描述使用十六进制对象 ID。新 Win/DOS 产物分别包含 `ResourceVersion=WIN95`／`DOS`，加载错版会被引擎拒绝；旧的无标签文件继续兼容，没有此保护。`audit-wrong-win.slf` 仅供错误映射的源码对照。完整说明、来源表和验证命令见 [#7 文档](../../docs/japanese-dos-mapping.md)。

## Steam 文本入口

输入是 UTF-16LE `编号:文本`，支持有／无 BOM，首个冒号分隔，`;` 开头为注释。GBK 对应 `MSG_chs.txt` / `WORD_chs.txt`，BIG5 对应 `MSG_cht.txt` / `WORD_cht.txt`。消息长度取自同版本 `SSS.MKF`，词条固定 10 字节，短内容补空格。`all` 的输出参数是已存在的独立目录：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\steam_to_legacy.py msg 'Steam文本目录' '新的M.MSG' gbk
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\steam_to_legacy.py word 'Steam文本目录' '新的WORD.DAT' gbk
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\steam_to_legacy.py all 'Steam文本目录' '已存在的独立输出目录' big5
```

沿用 Steam 原文件约定：允许跳号、显式空文本和重复编号，重复时最后一条生效。缺失消息按 SSS 的原偏移留空格，缺失词条按 `ID × 10` 留空格，后续编号不再前移；WORD ID 限于旧版脚本／对象可引用的 16 位范围。SSS 最后一项是 EOF 偏移，不占消息字节，可省略或提供空记录。WORD 没有独立总数索引，以最大有效 ID 决定长度，不能推断被省略的末尾词条。

损坏的 MKF／消息索引、负数／越界编号、坏记录行、无记录输入及超长内容报错，单文件验证失败不覆盖已有目标。仍须匹配同版本 SSS：结构检查不能证明两个版本语义一致。`all` 先在输出目录的临时子目录准备两个文件，全部成功后备份旧目标并逐个替换；可捕获的发布失败恢复旧文件、移除本轮新文件。成功时仍替换已有的一对输出；单独 `msg`／`word` 入口行为不变。

CLI `all` 与 GUI 共享 [`resource_transaction.py`](resource_transaction.py)。若恢复旧文件也被系统拒绝，保留 `.sdlpal-prepare-*` 中的备份并尽可能写入 `recovery.json`，错误提示给出目录；清理临时目录失败会提示残留路径。它不承诺断电、强杀或其他进程并发写同一目录时原子恢复，仍应使用工作副本。GUI 已有规范文件即使为空也继续优先，切换编码不会主动重建它们。详见 [#2 R3 的失败注入、成功输出及源码图](../../docs/japanese-resource-preparation-rollback.md)。

[#2 R2 复核与源码前后图](../../docs/japanese-steam-record-offsets.md)已覆盖真实 Steam 简、繁体整包、删除编号 0 的副本和 BOM 紧邻首编号的副本。完整输入的输出逐字节保持不变；稀疏输入及 BOM 首记录的编号修复通过独立字节布局核对和引擎源码加载。此入口只生成中文旧格式资源，不把该 Steam 版当成已认证的 Win／DOS 日文映射输入；Tk 交互和实际游戏流程仍待最后统一验收。

## 加载与验证

Windows 中文绝对 GamePath 已由 [#2 R4](../../docs/japanese-gamepath-unicode.md)复现并修复：
设置窗口的 GamePath 使用 UTF-8，核心文件检查／打开及 RIX 入口使用宽字符路径，旧无效 UTF-8 字节回退到系统 ACP。
`verify_gamepath.py` 覆盖同源 ASCII／中文副本、UTF-8／旧 CP936 配置及原始 PAL98 目录，保留完整源码帧与差异记录。
这是源码专项验证；Tk、音乐和实际游戏流程仍在最后统一验收。

当前输出仍为 4,773 块 / 4,766 唯一键，六个重复键均为同文、异文冲突为零。生成上游对照和当前输出后，另生成三份历史输出，分别核对 #3、#4、#8、#6：

```powershell
$jpPython = Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe'
& $jpPython -B -X utf8 tools\japanese\makemessage_j.py 'PC资源目录' '土星提取目录' 'NPC修前.slf' gbk --before-tournament-fix
& $jpPython -B -X utf8 tools\japanese\makemessage_j.py 'PC资源目录' '土星提取目录' '重复键修前.slf' gbk --before-duplicate-fix
& $jpPython -B -X utf8 tools\japanese\makemessage_j.py 'PC资源目录' '土星提取目录' '译文修前.slf' gbk --before-translation-fix
& $jpPython -B -X utf8 tools\japanese\makemessage_j.py 'PC资源目录' '土星提取目录' '译文R2修前.slf' gbk --before-translation-followup
& $jpPython -B -X utf8 tools\japanese\verify_restored_dialogues.py 'PC资源目录' '土星提取目录' '上游对照.slf' 'NPC修前.slf' '新的恢复核对目录'
& $jpPython -B -X utf8 tools\japanese\verify_tournament_dialogues.py 'PC资源目录' '土星提取目录' 'NPC修前.slf' '重复键修前.slf' '新的NPC核对目录'
& $jpPython -B -X utf8 tools\japanese\verify_duplicate_messages.py 'PC资源目录' '土星提取目录' '重复键修前.slf' '译文修前.slf' '新的重复键核对目录'
& $jpPython -B -X utf8 tools\japanese\verify_translations.py 'PC资源目录' '土星提取目录' '译文修前.slf' '译文R2修前.slf' '新的译文核对目录'
```

第一个校验核对 #3 的 119 组恢复、CLEAR 和旧输出不变。第二个校验检查 #4 十组修正，保持历史重复键不变。第三个校验核对 #8 六个复用键的全部 13 个原始消息组、取得事件和守卫脚本，要求仅两条正文改变，其余 4,771 块及文件字节不变，#3/#4 文本全部保留。

三个校验器的 `recovery-fixtures.csv` 均检查全部 4,766 个引擎键；#3 使用 `jp-recovery-before` / `jp-recovery`，#4 使用 `jp-npc-before` / `jp-npc`，#8 使用 `jp-duplicates-before` / `jp-duplicates`。夹具、历史 SLF 与模式须对应。详情见 [#3 恢复记录](../../docs/japanese-missing-dialogues.md)、[#4 NPC 记录](../../docs/japanese-tournament-npc-dialogues.md)及 [#8 重复键记录](../../docs/japanese-duplicate-message-keys.md)。

第四个校验器保护 #6 修订以外的全部字节，仅允许 #7 在 SETTING 起点新增唯一的 Win 版本标签；它不会统一换行后忽略其他字节变化。还会核对源码、原资源、控制码及战斗说明证据，并生成全键 `recovery-fixtures.csv` 和 `translation-objects.csv`；两者放入出图目录，使用 `jp-translation-before` / `jp-translation`，输出五组对白、十九个菜单及全部有效正文。

R2 使用 `verify_translation_followup.py`，同时比较 Win／DOS 修前修后目录，只允许各四组正文改变。随后使用 `verify_followup_rendering.py` 调用现有 Test 引擎并校验全键、字形、分页、缩放和图片；完整命令及历史输入的取得方式见 [R2 复现说明](../../docs/japanese-translation-followup.md#验证与复现)。不能把当前 R2 默认输出直接当成上述 R1 验证器的历史结果。

当前 #6 赤血蚕新译已排成完整两行，可直接加载生成 SLF。旧历史输出仍可使用 #5 的换行适配器；适配器对受保护的新译原样通过，拒绝未审阅正文。下面的步骤对两种版本都适用：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\adapt_red_silkworm_description.py '原始输出.slf' '新的适配输出.slf'
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tests\test_japanese_conversion_tools.py -v
```

历史工具结果、源码加载图与限制见 [#2 基线记录](../../docs/japanese-conversion-baseline.md)。GUI 回调测试不创建 Tk 窗口。按用户最新要求，所有子 Issue 的实现和专项验证完成后再统一实机验收。

## 可选土星头像包

[`convert_portraits.py`](convert_portraits.py) 独立于 SLF 转换；需要已审 PC 资源及土星 `RGM.JOE`、`ALLDAT.NEW`、`PROG.BIN`，输出目录必须尚不存在：

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\japanese\convert_portraits.py 'PC资源目录' '土星提取目录' '新的头像包目录' --target win
```

DOS 使用 `--target dos` 及其独立资源。转换器固定输入指纹，只替换已审 86 个 ID，按原 PC 头像范围等比缩小／透明填充，保留原文件。加载相应 `paljpn-win.por`／`paljpn-dos.por` 时设置 `PortraitFileName`；默认不设置，保留 PC 头像。

SDL2 普通日夜及已知颜色／索引特效独立处理头像源 RGB；SDL1 和未识别的直接调色板改写保留近似映射。来源、江少云回退和包配置见 [R1 头像审计](../../docs/japanese-portrait-palettes.md)，日夜验证见 [R2 夜景头像颜色](../../docs/japanese-portrait-night-colors.md)，当前特效实现及兼容边界见 [R3 特效证据](../../docs/japanese-portrait-effects.md)。当前 GUI 不自动生成或启用头像包。
