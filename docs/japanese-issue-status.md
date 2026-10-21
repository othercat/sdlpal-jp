# 总管 #1 与子 Issue 剩余项核对

2026-10-21，关联 [#1](https://github.com/othercat/sdlpal-jp/issues/1)。
核对起点为 `feature @ 68c56490a9c55c223b93ff0d2b6ae6f455885337`；
检查了 #1–#10 的完整正文、折叠历史、全部评论（均为 0 条）及对应当前源码／项目文档。
R2 完成 [Steam 稀疏编号](japanese-steam-record-offsets.md)，R3 完成 [多文件准备失败回滚](japanese-resource-preparation-rollback.md)；
本次从 `feature @ 581fe0cdf7873b4ec5be7aac15d846299cffc0c2` 继续完成 [#2 R4：中文绝对 GamePath](japanese-gamepath-unicode.md)。
随后从 `feature @ 81691383862747f3441c4eda3f3a5ed216231239` 续核 #1／#9，完成
[#9 R4：SDL1 构建／GLSL 输出验证及缩放震屏修复](japanese-portrait-backends.md)。
其他子 Issue 保留前轮审计结论，本轮没有重做全部历史验收。

**9 个子 Issue 均已有首轮实现合入，但“首轮 9/9”不表示所有技术跟进或验收已完成。**
所有 Issue 保持开放，实机由用户在全部实现完成后统一验收。
“实现完成”“兼容验证尚缺”“最终实机待测”分别记录，不把历史待办重复当作当前缺陷。

| Issue | 当前已完成 | 仍未完成 |
| --- | --- | --- |
| [#2](https://github.com/othercat/sdlpal-jp/issues/2) | 工具纳管、Win 基线、GUI 入口；Steam 跳号／BOM；多文件回滚；中文 GamePath 最新复现、宽字符文件链路和六组源码对比 | 最后 Tk／游戏加载、音乐及完整流程验收 |
| [#3](https://github.com/othercat/sdlpal-jp/issues/3) | [7 段、119 组、290 Win ID 恢复及预览透明度修正](japanese-missing-dialogues.md) | 最后实测七段剧情、相邻对白、分支、转场、分页 |
| [#4](https://github.com/othercat/sdlpal-jp/issues/4) | [10 组 NPC 错配修正，原正确五组及其他消息保留](japanese-tournament-npc-dialogues.md) | 最后实测 17 个事件及比武前／中／后状态 |
| [#5](https://github.com/othercat/sdlpal-jp/issues/5) | 83–87、赤血蚕、8 全角长名及[双列游标](japanese-menu-cursor-layout.md) | 最后实测战斗施法、完整流程、窗口与 DPI |
| [#6](https://github.com/othercat/sdlpal-jp/issues/6) | 18＋4＝22 组修订，[后四组已同步 Win／DOS](japanese-translation-followup.md) | 最后核对实际剧情／物品／法术界面；不宣称全剧本逐句审校 |
| [#7](https://github.com/othercat/sdlpal-jp/issues/7) | [4,476 个独立键、296 条说明、错版保护](japanese-dos-mapping.md) | 最后实测 DOS 开场、主要转折、菜单、分页、长名称 |
| [#8](https://github.com/othercat/sdlpal-jp/issues/8) | [两个异文冲突归零，六个复用键保留，未知同键异文拒绝](japanese-duplicate-message-keys.md) | 最后实测 16 个取得事件、五名守卫、空箱／消失状态与奖励 |
| [#9](https://github.com/othercat/sdlpal-jp/issues/9) | 86 个头像、普通日夜、[已知渐变及索引特效独立颜色](japanese-portrait-effects.md)；[SDL1／GLSL 验证和缩放震屏边缘修复](japanese-portrait-backends.md) | 配置保存重载、连续 RNG／场景／特效组合最后实测；SDL1 仍为索引近似色 |
| [#10](https://github.com/othercat/sdlpal-jp/issues/10) | 同源字体与 PALDLL 基线、[分页／控制符／三档源码缩放](pal98-dialogue-pagination-scaling.md) | 最后实测完整路线、交互、实际窗口 resize／DPI |

## 下一项可继续的技术工作

本轮完成 **#9 SDL1 构建／GLSL 输出兼容验证**：先构建再定位实际缩放震屏残留，
统一两个震屏路径的物理高度与原点计算。SDL1／SDL2 的 Release 和 Test 构建通过；
16 组共 11,362 帧、795 次完整物理读回、10,016 对索引／色表比较通过。
另有 300 次完整显示面震屏边界检查及 15＋21 项 C++、4 项证据正负测试通过。

当前已审清单没有剩余的已确认技术缺陷，可准备最后统一验收资料；
这不代表完整游戏流程或未知资源／shader 已全部测试。全部 Issue 继续开放，
不在本轮开始窗口操作、实机验收或新的土星硬件复刻目标。

## 不再算作当前待开发的历史条目

- #5 R2／R3 的赤血蚕一行裁切由 R4 处理，R5 长名称由 R6／R7 处理；#6 新译也已适配。
- #6／#7 提出的阿青、十赌九输、七步和陌生人四项已由 #6 R2 处理；有依据保留的称名／风物描写不另算缺陷。
- #10 早期未完成的同源字体、长对白分页和目标纹理缩放已有后续证据；OS 窗口层仍待实测。
- #9 R1 夜景有损配色、R2 特殊特效回退分别由 R2／R3 跟进；SDL1、未知直接改色仍是当前兼容边界。
- #9 R3 当时未执行的 SDL1 构建和 GLSL 输出验证已由 R4 补齐；仅限报告列出的后端／shader／主机。
- #7 五条 ASCII 源标记和 36 个原本无 Win 说明的对象有明确来源说明，不补造译文。
- #2 R1 的中文绝对 GamePath 失败已由 R4 复现并修复；旧文档采用 ASCII 副本是历史测试条件，不是当前仍失败的结论。
- 建单历史里的“尚无提交／尚未合并”是当时状态，完整实现、合并 SHA 和清理结果以各轮后续记录为准。

## 统一验收与追溯

最终实机须记录明确提交／构建、系统设备、Win／DOS 资源、SLF／头像包与字体配置、路线、结果、测试人及日期。
源码出图、工具测试和合并不替代实机通过，所有子 Issue 和总管继续开放。
当前已审头像目标是 PC 特效兼容下的独立源色；土星动态硬件逐帧等价没有验证，不作为已达成结论。

本轮 Issue 快照与评论清单保留在
`D:\Workspace\PALWork\artifacts\sdlpal-jp-issue-1\backlog-r1-20261021`；
[#2 的实现、合并、验证及清理](https://github.com/othercat/sdlpal-jp/issues/2)按完整 SHA 追溯。
[#9 R4 的提交和清理记录](https://github.com/othercat/sdlpal-jp/issues/9)与项目后端证据同步追溯。
历史证据不删除，不将旧的未执行项改写成通过。
