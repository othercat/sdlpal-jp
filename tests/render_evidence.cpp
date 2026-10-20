// Opt-in resource-backed rendering tool; never compiled into Release builds.
// Uses the engine's drawing functions and skips only window presentation.
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <vector>

extern "C" {
#include "main.h"
extern SDL_Surface *gpScreenReal;
}

#if SDL_VERSION_ATLEAST(2, 0, 0)
namespace {
void Require(bool ok, const char *what) {
    if (!ok) throw std::runtime_error(what);
}

void Save(const std::string& directory, const std::string& name) {
    Require(SDL_SaveBMP(gpScreen, (directory + "/" + name + ".bmp").c_str()) == 0,
            "Cannot save BMP (create the output directory first)");
}

void DrawDescription(WORD object, bool item) {
    WORD script = gpGlobals->g.rgObject[object].item.wScriptDesc;
    int line = 0, steps = 0;
    while (script) {
        Require(++steps < 100 && script < gpGlobals->g.nScriptEntry,
                "Unexpected description script");
        const SCRIPTENTRY& entry = gpGlobals->g.lprgScriptEntry[script];
        if (entry.wOperation == 0) break;
        // 0x00a7 is the Win95 description marker (a no-op in autoscript).
        Require(entry.wOperation == 0xffff || entry.wOperation == 0x00a7,
                "Description contains gameplay operation");
        if (entry.wOperation == 0x00a7) {
            script = PAL_RunAutoScript(script, 0);
            continue;
        }
        const int increment = entry.rgwOperand[1] != 1;
        script = PAL_RunAutoScript(script, (item ? PAL_ITEM_DESC_BOTTOM : 0) | line);
        line += increment;
    }
}

int CountClippedInk(WORD object, bool item) {
    SDL_Surface *screen = gpScreen;
    gpScreen = SDL_CreateRGBSurface(0, 384, 200, 8, 0, 0, 0, 0);
    Require(gpScreen != nullptr, "Cannot allocate overflow probe");
    SDL_FillRect(gpScreen, nullptr, 0xfe); // distinguish black shadows from background
    DrawDescription(object, item);
    int count = 0;
    for (int y = 0; y < gpScreen->h; ++y) {
        const BYTE *row = (BYTE *)gpScreen->pixels + y * gpScreen->pitch;
        for (int x = 320; x < gpScreen->w; ++x) count += row[x] == DESCTEXT_COLOR;
    }
    SDL_FreeSurface(gpScreen);
    gpScreen = screen;
    return count;
}

void DrawAunt(const std::string& directory, bool translated) {
    SDL_FillRect(gpScreen, nullptr, 0);
    // Reconstruct this scene from startup scripts 5-7 and scene-2 entry 3547.
    // No route, animation, input loop, sound, or save file is replayed.
    gpGlobals->wNumScene = 2;
    gpGlobals->viewport = PAL_XY(1152, 176);
    gpGlobals->wPartyDirection = kDirSouth;
    gpGlobals->rgParty[0].x = 160;
    gpGlobals->rgParty[0].y = 112;
    gpGlobals->rgParty[0].wFrame = 0;
    gpGlobals->g.PlayerRoles.rgwSpriteNum[0] = 193;
    PAL_InitResources();
    PAL_SetLoadFlags(kLoadScene | kLoadPlayerSprite);
    PAL_LoadResources();
    PAL_MakeScene();
    PAL_StartDialog(kDialogUpper, 0, 55, FALSE);
    g_TextLib.fUserSkip = TRUE;
    for (int i = 0; i < 3; ++i) {
        const int message = translated ? PAL_GetMsgNum(1317, 2, i) : 1317 + i;
        Require(message > 0, "Aunt dialogue mapping missing");
        const WCHAR *text = PAL_GetMsg(message);
        Require(text && *text, "Aunt dialogue text missing");
        PAL_ShowDialogText(text);
    }
    Save(directory, "aunt-dialogue");
    PAL_ClearDialog(FALSE);
    PAL_FreeResources();
}
} // namespace

int RenderEvidence(int argc, char **argv) {
    if (argc != 6) {
        fprintf(stderr, "Usage: --render-evidence RESOURCE_DIR SLF_OR_DASH OUTPUT_DIR "
                        "cn|jp|jp-legacy|cn-jp-font\n");
        return 2;
    }
    const std::string mode(argv[5]), directory(argv[4]);
    const bool translated = mode == "jp" || mode == "jp-legacy";
    if (!translated && mode != "cn" && mode != "cn-jp-font") return 2;
    if (translated && strcmp(argv[3], "-") == 0) return 2;
    try {
        Require(SDL_Init(0) == 0, "SDL_Init failed");
        PAL_LoadConfig(FALSE);
        free(gConfig.pszGamePath);
        gConfig.pszGamePath = strdup(argv[2]);
        if (translated) gConfig.pszMsgFile = strdup(argv[3]);
        Require(PAL_InitGlobals() == 0 && gConfig.fIsWIN95, "Expected Win95 resources");
        Require(PAL_InitText() == 0, "Cannot load game text");
        if (mode == "cn-jp-font") g_TextLib.iFontFlavor = kFontFlavorJapanese;
        Require(PAL_InitFont(&gConfig) == 0, "Cannot load engine font");
        PAL_InitGameData(0);
        Require(PAL_InitUI() == 0, "Cannot load UI sprites");
        gpScreen = SDL_CreateRGBSurface(0, 320, 200, 8, 0, 0, 0, 0);
        gpScreenBak = SDL_CreateRGBSurface(0, 320, 200, 8, 0, 0, 0, 0);
        // VIDEO_UpdateScreen reads the surface height before checking pause.
        gpScreenReal = SDL_CreateRGBSurface(0, 320, 200, 32, 0, 0, 0, 0);
        Require(gpScreen && gpScreenBak && gpScreenReal, "Cannot allocate surfaces");
        g_bRenderPaused = TRUE;
        SDL_Color *palette = PAL_GetPalette(0, FALSE);
        Require(palette != nullptr, "Cannot read PAT.MKF palette 0");
        SDL_SetPaletteColors(gpScreen->format->palette, palette, 0, 256);
        SDL_SetPaletteColors(gpScreenBak->format->palette, palette, 0, 256);

        // Reproduce the pre-#5 defaults without modifying the input SLF.
        if (mode == "jp-legacy") {
            gConfig.ScreenLayout.MagicMPDescLines = PAL_XY(5, 0);
            gConfig.ScreenLayout.MagicMPSlashPos = PAL_XY(45, 14);
            gConfig.ScreenLayout.MagicMPNeededPos = PAL_XY(15, 14);
            gConfig.ScreenLayout.MagicMPCurrentPos = PAL_XY(50, 14);
            gConfig.ScreenLayout.MagicDescMsgPos = PAL_XY(102, 0);
        }

        DrawAunt(directory, translated);
        const WORD magics[] = {306, 307, 308, 311, 370, 374, 377, 390, 393, 394};
        memset(gpGlobals->g.PlayerRoles.rgwMagic, 0, sizeof(gpGlobals->g.PlayerRoles.rgwMagic));
        for (size_t i = 0; i < sizeof(magics) / sizeof(magics[0]); ++i)
            gpGlobals->g.PlayerRoles.rgwMagic[i][0] = magics[i];
        gpGlobals->g.PlayerRoles.rgwMP[0] = 999;
        FILE *report = fopen((directory + "/clipped-ink.csv").c_str(), "w");
        Require(report != nullptr, "Cannot create clipping report");
        fprintf(report, "object_id,clipped_ink\n");
        for (WORD object : magics) {
            SDL_FillRect(gpScreen, nullptr, 0);
            PAL_ClearKeyState();
            PAL_MagicSelectionMenuInit(0, TRUE, object);
            Require(PAL_MagicSelectionMenuUpdate() == 0xffff, "Unexpected menu action");
            Save(directory, "magic-" + std::to_string(object));
            fprintf(report, "%u,%d\n", object, CountClippedInk(object, false));
        }

        memset(gpGlobals->rgInventory, 0, sizeof(gpGlobals->rgInventory));
        gpGlobals->rgInventory[0].wItem = 149;
        gpGlobals->rgInventory[0].nAmount = 2;
        gpGlobals->rgInventory[1].wItem = 150;
        gpGlobals->rgInventory[1].nAmount = 2;
        gpGlobals->iCurInvMenuItem = 0;
        SDL_FillRect(gpScreen, nullptr, 0);
        PAL_ClearKeyState();
        PAL_ItemSelectMenuInit(0); // show without adding equipped usable items
        Require(PAL_ItemSelectMenuUpdate() == 0xffff, "Unexpected item menu action");
        Save(directory, "item-149");
        fprintf(report, "149,%d\n", CountClippedInk(149, true));
        fclose(report);
        printf("Rendered %s: 12 BMPs, 320x200, palette 0, font flavor %d, "
               "font height %d, "
               "word length %u, magic description X=%d\n", mode.c_str(),
               g_TextLib.iFontFlavor, PAL_FontHeight(), gConfig.dwWordLength,
               PAL_X(gConfig.ScreenLayout.MagicDescMsgPos));
        PAL_FreeUI();
        PAL_FreeText();
        PAL_FreeFont();
        PAL_FreeGlobals();
        SDL_FreeSurface(gpScreen);
        SDL_FreeSurface(gpScreenBak);
        SDL_FreeSurface(gpScreenReal);
        gpScreen = gpScreenBak = gpScreenReal = nullptr;
        SDL_Quit();
        return 0;
    } catch (const std::exception& e) {
        fprintf(stderr, "Render evidence failed: %s (%s)\n", e.what(), SDL_GetError());
        return 1;
    }
}
#else
int RenderEvidence(int, char **) {
    fprintf(stderr, "Render evidence requires an SDL2 Test build.\n");
    return 2;
}
#endif
