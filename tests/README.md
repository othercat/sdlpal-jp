How to write unit tests
=======================

### Optional Saturn portrait palettes

Issue 9 R3 adds `jp-portrait-effects` / `dos-portrait-effects` modes to the Test
renderer. They call the production effects, capture uploaded RGB and indexed
frames, and read representative hidden SDL target textures. The same harness
must be built against the before and after production sources. The independent
NumPy/Pillow oracle is `tools/japanese/verify_portrait_effects.py`; see the
[effect evidence](../docs/japanese-portrait-effects.md) for commands and inputs.
`PortraitColors` includes mixed coverage, wave wraparound and the 12-round
dissolve endpoint where the original low-nibble transition is unfinished.

`tests/test_portrait_conversion.py` covers source RLE boundaries, valid large
portraits, native-extent fitting, archive bounds and input/output preservation.
The `PortraitPalettes` C++ tests reject malformed/wrong-target packs and check
opt-in configuration Set/Get/Clear. Run the C++ tests from the repository root.

`tools/japanese/verify_portrait_rendering.py` checks real `jp-portraits` /
`dos-portraits` frames against separate palette and mask calculations, including
all reviewed native IDs, upper/lower positions, scene palettes, native fallback,
color rotations, half/black palette stages and drawing while already black.
These stages are controlled source probes, not live fade/input acceptance.
Existing dialogue/description modes accept an optional final portrait-file
argument. Menu comparisons preserve the selected glyph mask while allowing its
documented F9–FE timer-driven color phase.

Commands, fixed resources, preview exports and remaining acceptance are in
[#9 evidence](../docs/japanese-portrait-palettes.md). The Windows VS 2026 Test
build used `CL=/utf-8 /DGTEST_HAS_TR1_TUPLE=0` with the bundled old Google Test.

***SDLPAL*** adopts the [Google C++ testing framework](https://github.com/google/googletest) for unit tests.

Writing a unit test using Google C++ testing framework is easy as 1-2-3:


Step 1
------

Create a new c++ code file containing test codes in the **`tests`** directory, including necessary header files such that the stuff your test logic needs is declared. If you dont't know which appropriate header to be included, just follow the code snippet here, which should be sufficient in most cases: 

```c++
// Include the Google C++ testing framework
#include <gtest/gtest.h>
// Inlucde the functions to be tested
extern "C"{
    #include "main.h"
}
```

### Notes for file naming convention

To avoid any potential file naming conflicts, please name your test code files starting as ***test_***.


Step 2
------

Use the **`TEST`** macro to define your tests. **`TEST`** has two parameters: the first is test case name and the second is the test name. After using the macro, you should define your test logic between a pair of braces. You can use a bunch of macros such as ***EXPECT_EQ*** to indicate the success or failure of a test. The following code snippet demonstrates how to create a test named ***PALswprintf*** in test case ***sdlpal*** to test the ***`PAL_swprintf`*** function:

```c++
TEST(sdlpal, PALswprintf) {
    WCHAR test_buf[256];
    EXPECT_EQ(0, wcsncmp( L"测试",    test_buf, PAL_swprintf(test_buf, sizeof(test_buf)/sizeof(WCHAR), L"%ls%ls", L"测", L"试")));
}
```

As tests are grouped into test cases in Google Test, please put logically related tests into the same test case. The test case name and the test name should both be valid C++ identifiers, and you should avoid to use underscore (_) in these names. Google Test guarantees that each test you define is run exactly once, but it makes no guarantee on the order the tests are executed. Therefore, you should write your tests in such a way that their results don't depend on their order.


Step 3
------

When you finished writting test codes, you can use ***`make check`*** to compile and run tests. If you are using ***Visual Studio*** under Windows, please make sure you've actived the **Test** configuration before you launch the program.

### Special notes for ***Visual Studio*** users

You should put all test files into the ***Test Files*** filter, and make sure you've excluded them for compilation in configurations other than **Test**.

### Japanese SLF adapter

The resource-independent input/file-preservation checks run separately:

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tests\test_red_silkworm_adapter.py -v
```

The [red silkworm verification record](../docs/japanese-red-silkworm-layout.md)
also documents the resource-backed before/after engine rendering checks.

### Dialogue rendering evidence

The Test-only `--render-evidence` modes `cn-pages` and `jp-pages` exercise real
dialogue page waits, SLF CLEAR boundaries, colors and escaped controls, then read
back 2x, 3x and 2.5x output from the production SDL renderer.
See the [commands, pixel checks and scope](../docs/pal98-dialogue-pagination-scaling.md).

The `jp-long-names` mode renders eight-character item/magic names in both columns,
selected and unselected, through the production menu and scaling paths.
The [evidence record](../docs/japanese-long-name-rendering.md) includes commands,
glyph/shadow/cursor and quantity/MP checks, and the explicit user-owned interactive
acceptance boundary.

The `jp-cursor-grid` mode adds two full-page, repeated-object boundary fixtures
to those eight views. It selects the third row/right column to check the cursor
against the previous column's name/quantity and adjacent rows. These lists are
prepared in memory and are not naturally acquired game inventories.
Run `tools/verify_long_name_rendering.py` with `--dense-grid` to require zero
cursor/name/shadow overlap. `--legacy-cursor` verifies archived pre-fix renders
with the original column spacing and explicitly counted 7/4 covered ink pixels.
See the [cursor fix and before/after evidence](../docs/japanese-menu-cursor-layout.md).

### Japanese conversion tool entries

Run the resource-free entry and failure-path checks with the fixed interpreter:

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tests\test_japanese_conversion_tools.py -v
```

These use real Steam converter subprocesses and the real GUI callback
definitions with substituted Tk controls; no GUI window is created.
See the [resource-backed baseline and source-load evidence](../docs/japanese-conversion-baseline.md)
for the separate full Win conversion and deferred unified acceptance.

### DOS Japanese mapping

`tests/test_dos_mapping.py` checks independent DOS identities, explicit source
markers, raw script/text drift, and failure without overwriting an existing
file. The C++ `DescriptionLayout` tests also check both incompatible resource
directions before loading and hexadecimal DOS object-description keys.

`tools/japanese/verify_dos_rendering.py` runs the Test-only `dos-before`, `dos`,
and `dos-layout-before` modes plus both wrong-version rejection cases. It
compares all 4,476 actual engine lookups and 296 descriptions, probes overflow,
checks real menu ink, and exports opaque RGB PNGs. See the
[resource inputs, commands and acceptance boundary](../docs/japanese-dos-mapping.md).

### Restored Japanese dialogue mappings

`tools/japanese/verify_restored_dialogues.py` reads the pinned raw Win/Saturn
resources, compares all 119 reviewed recoveries and preserves every upstream
block/duplicate. Its generated `recovery-fixtures.csv` probes all 4,766 runtime
keys in the Test-only `jp-recovery-before` and `jp-recovery` renderer modes.
Eight reviewed dialogue commands also produce neutral-background before/after
images, including real CLEAR waits. See the [commands and evidence](../docs/japanese-missing-dialogues.md).

`tools/export_recovery_previews.py BEFORE AFTER NEW_OUTPUT` requires both complete
recovery manifests and opaque 640x400 BMPs from the corrected Test renderer.
It writes 18 RGB PNGs and verifies their pixels after reopening the encoded files.
The GPU target's unused alpha must not be published as image transparency.
Pillow is required; the resource-free opacity regression tests run with:

```powershell
& (Join-Path $env:USERPROFILE 'CodexTools\python\Scripts\python.exe') -B -X utf8 tests\test_recovery_preview_export.py -v
```

### Tournament NPC dialogue corrections

`tools/japanese/verify_tournament_dialogues.py` verifies the ten Win-based
translations against raw Win/Saturn inputs, event references and the reviewed
text record. Complete byte comparison permits only those ten MESSAGE body
replacements; the other blocks, settings and descriptions must remain unchanged.
Use `--before-tournament-fix` only to generate the historical pre-#4 SLF.

The generated full-key fixture uses `jp-npc-before` / `jp-npc`, requiring 4,766
mapped keys and ten drawn NPC groups in both runs. The existing Issue #3 modes
retain their separate 8-group/119-omission assertions. See the
[commands, all ten source-rendered comparisons and validation](../docs/japanese-tournament-npc-dialogues.md).

### Reused message keys

`verify_duplicate_messages.py` verifies all six reused keys against raw
Win/Saturn groups and event records. Only two acquisition MESSAGE bodies may
change; all 4,773 blocks and all other bytes remain intact. Identical reuse is
valid; the converter rejects conflicting text before writing output.

The `jp-duplicates-before` / `jp-duplicates` modes check all 4,766 effective
keys, dump every loaded text entry as Unicode code points, and draw six groups.
The two `003e` acquisition boxes are captured through the existing input filter
during the real timed wait, before the engine removes them. The other four use
the reviewed upper/no-portrait default. Reversing all MESSAGE blocks in temporary
inputs demonstrates the old last-occurrence behavior and the corrected
order-independent text. See [source review, commands and comparisons](../docs/japanese-duplicate-message-keys.md).

### Reviewed Japanese translations

`verify_translations.py` checks 18 reviewed Win/Saturn groups, battle script
anchors and source fingerprints. It reconstructs the complete expected file,
preserving all non-target bytes, controls and the 4,766-key mapping.
`--before-translation-fix` reproduces the post-#8 baseline for historical checks.

Copy both generated CSV fixtures to the output directory and use
`jp-translation-before` / `jp-translation`. The Test entry dumps all effective
texts and renders five dialogue groups and nineteen real item/magic menus.
The opening dream's `~40` already resets the line counter; its subsequent CLEAR
does not require an extra key wait. Old modes retain their own fixture checks.
The red-silkworm adapter accepts the reviewed, already fitting text unchanged.
See [source decisions, comparisons and verification](../docs/japanese-translation-review.md).

### Four shared translation followups (Issue #6 R2)

`--before-translation-followup` reproduces the post-#7 Win baseline, including
the resource-version tag. `verify_translation_followup.py` checks the four
additional groups against raw Win/DOS/Saturn sources, identical corrected text
across versions and strict preservation of every other SLF byte. The R1 verifier
continues to use the historical output rather than the new default output.

`verify_followup_rendering.py` uses the existing `jp-translation-before`,
`jp-translation` and `dos` modes. Fixtures draw the four target groups plus
unchanged witnesses to retain the modes' coverage contracts. Both full key
spaces are dumped; corrected lines are checked for glyph ink, pagination and
pixel changes within their old/new glyph-and-shadow masks. PNGs must be opaque.
2x/3x scales are exact; 2.5x is checked only for dimensions.

`test_translation_followup.py` covers source-anchor/body drift and rejects
unrelated SLF bytes, newline changes, duplicate or missing targets.
See [R2 provenance, commands and before/after images](../docs/japanese-translation-followup.md).

### Portrait night colors (Issue #9 R2)

`verify_portrait_colors.py` binds the unchanged R1 portrait packs, source resource
hashes, full indexed frames and fixtures, then checks independent RGB composition.
`jp-portraits-rgb` / `dos-portraits-rgb` archive both indexed and RGB frames.
`jp-translation-rgb` / `dos-rgb` and their `-night-rgb` variants check real
message lookup, page restoration and menu drawing; the indexed BMP remains
available beside the `-rgb.bmp` view and SDL scale outputs.

The comparison excludes neither backgrounds nor transparent pixels. Exact
source RGB is the target for normal palettes; black fades are checked separately,
and unknown color effects intentionally retain indexed output. The C++ tests
also cover same-index overwrite, opaque black, clipped fill and saved coverage.
See [source evidence, reproduction and remaining acceptance](../docs/japanese-portrait-night-colors.md).
