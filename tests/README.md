How to write unit tests
=======================

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
