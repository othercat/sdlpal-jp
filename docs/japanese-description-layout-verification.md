# Issue #5：日文说明布局复核（2026-10-20）

关联 [Issue #5](https://github.com/othercat/sdlpal-jp/issues/5)、[总管 #1](https://github.com/othercat/sdlpal-jp/issues/1)。[原始审计](japanese-localization-audit.md#issue-5) 保留移植前的 12 行基线；本记录是后续实现与验证。跨引擎字体、字号及实机截图由 [#10](https://github.com/othercat/sdlpal-jp/issues/10) 承接。

## 采用的上游实现

上游已有独立提交 [d82e20f9fc38126602bebdd60f2aca3c4e552b09](https://github.com/PalMusicFan/sdlpal/commit/d82e20f9fc38126602bebdd60f2aca3c4e552b09)，作者 palxex，日期 2022-07-23。其标题写 83–86，但实际包含 **83–87**。本次抓取完整上游引用后确认：提交可从 `let_us_dub` 到达，不能从 `master` / `v2026.08`（`6dafc9c79718058f3a1a4ab8a3d3e30a102ab207`）到达。

原样移植该提交的四个文件：`palcfg.h`、`palcfg.c`、`magicmenu.c`、`script.c`。未整体合入配音开发分支。SLF 解析器按 `SCREENLAYOUT` 大小接收参数，扩充结构即可读取新索引。

| SLF 参数 | 含义 | 缺省值（旧文件不变） | 日文 SLF |
| --- | --- | --- | --- |
| 83 | MP 框宽度参数，字段名 `MagicMPDescLines` | `5,0` | `3,0` |
| 84 | MP 斜线坐标 | `45,14` | `30,14` |
| 85 | 所需 MP 坐标 | `15,14` | `5,14` |
| 86 | 当前 MP 坐标 | `50,14` | `31,14` |
| 87 | 法术说明 X 起点；第二值为 0 | `102,0` | `70,0` |

既有 81/82 控制说明行数，继续沿用；物品说明 X 起点保持 71。日文名称的 8 全角宽度、两列列表已有实现。本次未改写土星原文换行、翻译、DOS 映射或头像。

Windows 验证时另给 `win32/native_midi.cpp` 补上它直接使用的 `<chrono>`，使 VS 2026 / v145 能编译；不改变 MIDI 行为。

## 全部说明的逐像素复核

使用本仓 `fontglyph.h` + `fontglyph_jp.h`，16px Japanese 字形、320×200 逻辑画布。输入为原审计的 `description-render-layouts.json`：**296 对象、793 行**（233 道具 / 671 行，63 法术 / 122 行）。[复核工具](../tools/verify_description_layout.py) 同时计算真实笔画与 `(1,0)`、`(1,1)` 阴影；[完整结果](evidence/issue-5-description-pixels.json) 可追溯输入指纹。

| 指标 | 移植前 | 移植后 |
| --- | ---: | ---: |
| 正文裁切对象 / 行 | 11 / 12 | **1 / 1** |
| 裁切正文像素 | 437 | **31** |
| 裁切纯阴影像素 | 484 | **38** |
| 法术正文裁切行 / 像素 | 11 / 406 | **0 / 0** |
| 法术最右正文 / 含阴影 X | 345 / 346 | **313 / 314** |

下表每行以对象、消息 ID 和 Y 定位。像素数为正文，不含阴影。

| 对象 ID / 名称 | Win 消息 | Y | 裁切像素 前→后 | 最右正文 X 前→后 |
| --- | ---: | ---: | ---: | ---: |
| 149 赤血蚕 | 12920 | 119 | **31→31** | 326→326 |
| 306 净衣咒 | 13437 | 3 | 16→0 | 329→297 |
| 307 冰心诀 | 13436 | 3 | 16→0 | 329→297 |
| 308 灵血咒 | 13466 | 3 | 27→0 | 329→297 |
| 308 灵血咒 | 13466 | 19 | 16→0 | 329→297 |
| 311 天罡战气 | 13444 | 3 | 72→0 | 341→309 |
| 370 酒神 | 13451 | 3 | 63→0 | 345→313 |
| 374 爆炸蛊 | 13094 | 19 | 37→0 | 325→293 |
| 377 飞龙探云手 | 13458 | 3 | 21→0 | 329→297 |
| 390 醉仙望月步 | 13455 | 3 | 86→0 | 341→309 |
| 393 仙风云体术 | 13457 | 3 | 26→0 | 329→297 |
| 394 乾坤一掷 | 13464 | 3 | 26→0 | 329→297 |

**残留是赤血蚕首行末字「者」**；它是物品说明，不受 87 控制。需后续结合土星原换行和物品栏截图决定调整方式，当前不能关闭 #5。酒神的字格仍延伸到 326，但末尾标点的墨迹止于 313，不能把空白字格越界计为裁字。

全部同对象行对的正文交集为 0。既有 360 对相邻行有阴影接触（1,154 像素），平移前后完全相同：没有新增正文重叠，不能写成“任何像素都不接触”。法术正文最下 Y=50、含阴影 Y=51，距菜单起点 Y=58 留 6 空行；物品正文最下 Y=198、阴影 Y=199，无底部越界。此分析不包含 MP 框美术与其他界面元素的遮挡。

## 构建与自动验证

环境：Windows 11 Pro 10.0.26200，Visual Studio 2026 Community 18，MSVC v145，Windows SDK 10.0。SDL 子模块固定 `6c89fad1f947e3173e822945adf534ca21ba52b5`，GoogleTest 固定 `aa148eb2b7f70ede0eb10de34b6254826bfb34f4`。

- `Release|x64`：成功，0 错误；历史编码、类型转换等警告保留。
- `Test|x64`：成功；执行 **4/4 测试通过**。
- 新增测试通过真实 SLF 解析、`PAL_RunAutoScript` 和字体绘制，确认旧文件默认值、新参数生效、法术尾部重新可见，以及物品画面逐像素不变。两个 ASCII 小样本不依赖游戏资源。
- `git -c core.whitespace=cr-at-eol diff --check`：通过（保留仓库既有 CRLF）。

从仓库根目录运行，`$evidenceRoot` 指向本机证据目录：

```powershell
$msbuild = 'C:\Program Files\Microsoft Visual Studio\18\Community\MSBuild\Current\Bin\MSBuild.exe'
& $msbuild win32\sdlpal.sln /m:4 /t:Build /p:Configuration=Release /p:Platform=x64 /p:PlatformToolset=v145 /p:WindowsTargetPlatformVersion=10.0 "/p:OutDir=$evidenceRoot\build-release\"
# 固定的旧版 GoogleTest 使用了新版 MSVC 不再提供的 TR1；本测试不依赖 TR1。
$env:CL = '/utf-8 /DGTEST_HAS_TR1_TUPLE=0'
& $msbuild win32\sdlpal.sln /m:4 /t:Build /p:Configuration=Test /p:Platform=x64 /p:PlatformToolset=v145 /p:WindowsTargetPlatformVersion=10.0 "/p:OutDir=$evidenceRoot\build-test\"
& "$evidenceRoot\build-test\sdlpal.exe" "--gtest_output=xml:$evidenceRoot/test-results.xml"
Remove-Item Env:CL
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tools\verify_description_layout.py "$auditRoot\description-render-layouts.json" "$auditRoot\paljpn-win.slf"
```

本次构建日志、测试 XML、资源和静态验证 JSON 保存在 `D:\Workspace\PALWork\artifacts\sdlpal-jp-issue-5\layout-compatibility-20261020-131927`。最初两次构建使用未正确展开的自定义 `IntDir` 失败；改用项目原有中间目录后解决。随后分别补齐 `<chrono>`、旧版 GoogleTest TR1 开关及测试构建 UTF-8 开关；最终成功结果以上述日志为准。

## 实机验收边界

自动化与静态检查已完成，**完整实机验收仍待完成**。后续 [#10 源码渲染对照](pal98-font-rendering-comparison.md) 已用真实引擎函数输出 MP 框、两列菜单、全部 10 个受影响法术与赤血蚕，并以 PAL98 + PALDLL_DX9 的中文实机截图作对照。SDLPAL 不再依赖窗口截图验证这些绘制结果；完整游戏回归、普通对白分页和赤血蚕修正仍待完成，外部字体与 DOS 未覆盖。

## 后续源码图像证据（#10，2026-10-20）

真实 `PAL_RunAutoScript` 扩宽画布测得的越界正文为 437→31 像素，11 对象逐项与本页静态结果一致。真实菜单输出确认 83–87 的 MP 框与说明平移生效，赤血蚕物品图前后字节相同。精选前后图、中文与日文字形、输入指纹、复现命令及实机/源码证据区别见 [对照文档](pal98-font-rendering-comparison.md)。这增加了实际绘制证据，未将本单验收状态改为通过。

完整实现 SHA、普通合并 SHA、目标 `feature`、源分支最终 SHA 及清理状态写入 GitHub Issue，避免依赖日后可能删除的分支。
