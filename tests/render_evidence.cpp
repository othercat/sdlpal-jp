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
extern SDL_Window *gpWindow;
extern SDL_Renderer *gpRenderer;
extern SDL_Texture *gpTexture;
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

void PrepareInn() {
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
}

void DrawAunt(const std::string& directory, bool translated) {
    PrepareInn();
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

// Exercise the real four-line wait/restore path. The test supplies an SDL event
// to the existing input-filter interface; it never writes a page/line counter.
int pageWaits = 0;
int AdvancePage(const SDL_Event *event, volatile PALINPUTSTATE *state) {
    if (event->type != SDL_USEREVENT || (event->user.code != 10 && event->user.code != 5)) return 0;
    Require(event->user.code == 10 ? g_TextLib.nCurrentDialogLine == 4 :
        g_TextLib.nCurrentDialogLine > 0, "Unexpected page wait position");
    ++pageWaits;
    state->dwKeyPress |= kKeySearch;
    return 1;
}

void SaveScales(const std::string& directory, const std::string& name) {
    Save(directory, name);
    SDL_Texture *previousTexture = gpTexture;
    SDL_Texture *previousTarget = SDL_GetRenderTarget(gpRenderer);
    const int widths[] = {640, 960, 800};
    for (int width : widths) {
        SDL_Surface *output = SDL_CreateRGBSurface(0, width, width * 5 / 8, 32,
            0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000);
        Require(output != nullptr, "Cannot allocate scale output");
        SDL_Texture *target = SDL_CreateTexture(gpRenderer, SDL_PIXELFORMAT_ARGB8888,
            SDL_TEXTUREACCESS_TARGET, width, output->h);
        Require(target && SDL_SetRenderTarget(gpRenderer, target) == 0,
            "Cannot create renderer target");
        gpTexture = nullptr;
        g_bRenderPaused = FALSE;
        // Use the production renderer, texture layout and palette conversion.
        // A render target provides readback without a screenshot or visible UI.
        VIDEO_Resize(width, output->h);
        VIDEO_UpdateScreen(nullptr);
        Require(SDL_RenderReadPixels(gpRenderer, nullptr, SDL_PIXELFORMAT_ARGB8888,
            output->pixels, output->pitch) == 0, "Cannot read renderer target");
        Require(SDL_SaveBMP(output, (directory + "/" + name + "-" +
            std::to_string(width) + ".bmp").c_str()) == 0, "Cannot save scale output");
        g_bRenderPaused = TRUE;
        SDL_DestroyTexture(gpTexture);
        Require(SDL_SetRenderTarget(gpRenderer, previousTarget) == 0, "Cannot restore target");
        SDL_DestroyTexture(target);
        SDL_FreeSurface(output);
    }
    gpTexture = previousTexture;
}

void DrawPages(const std::string& directory, bool translated) {
    PrepareInn();
    PAL_StartDialog(kDialogUpper, 0, 55, FALSE);
    g_TextLib.fUserSkip = TRUE;
    for (int i = 0; i < 3; ++i) {
        const int message = translated ? PAL_GetMsgNum(1317, 2, i) : 1317 + i;
        Require(message > 0, "Aunt dialogue mapping missing");
        const WCHAR *text = PAL_GetMsg(message);
        Require(text && *text, "Aunt dialogue text missing");
        PAL_ShowDialogText(text);
    }
    SaveScales(directory, "aunt-dialogue");
    PAL_ClearDialog(FALSE);
    PAL_InitInput();
    PAL_RegisterInputFilter(nullptr, AdvancePage, nullptr);
    FILE *report = fopen((directory + "/pagination.csv").c_str(), "w");
    Require(report != nullptr, "Cannot create pagination report");
    fprintf(report, "group,order,message,page,line,color,icon_x,icon_y,waits\n");
    struct Group { int first, last, face; BYTE position; };
    const Group groups[] = {{1326, 1332, 8, kDialogUpper},
                            {1333, 1340, 55, kDialogLower}};
    for (const Group& group : groups) {
        PAL_MakeScene();
        PAL_StartDialog(group.position, 0, group.face, FALSE);
        const int span = group.last - group.first;
        const int count = translated ? 1024 : span + 1;
        int page = 1;
        int messages = 0;
        const int waitsBeforeGroup = pageWaits;
        bool terminated = !translated;
        const std::string name = "dialogue-" + std::to_string(group.first);
        for (int order = 0; order < count; ++order) {
            const int id = translated ? PAL_GetMsgNum(group.first, span, order) : group.first + order;
            if (translated && id < 0) { terminated = true; break; }
            if (translated && id == 0) {
                SaveScales(directory, name + "-page-" + std::to_string(page++));
                SDL_Event event = {};
                event.type = SDL_USEREVENT; event.user.code = 5;
                Require(SDL_PushEvent(&event) == 1, "Cannot queue explicit page advance");
                const int waitsBefore = pageWaits;
                PAL_ClearDialog(TRUE);
                Require(pageWaits == waitsBefore + 1 && g_TextLib.nCurrentDialogLine == 0,
                    "Explicit page did not wait and reset");
                VIDEO_RestoreScreen(gpScreen);
                VIDEO_UpdateScreen(nullptr);
                continue;
            }
            const WCHAR *line = PAL_GetMsg(id);
            Require(line && *line, "Missing dialogue message");
            ++messages;
            const bool automaticPage = g_TextLib.nCurrentDialogLine == 4;
            const int waitsBefore = pageWaits;
            if (automaticPage) {
                SaveScales(directory, name + "-page-" + std::to_string(page++));
                SDL_Event event = {};
                event.type = SDL_USEREVENT;
                event.user.code = 10;
                Require(SDL_PushEvent(&event) == 1, "Cannot queue page advance");
            }
            g_TextLib.fUserSkip = TRUE;
            g_TextLib.iDelayTime = 0;
            PAL_ShowDialogText(line);
            Require(pageWaits == waitsBefore + (automaticPage ? 1 : 0),
                "Automatic page wait count changed");
            Require(g_TextLib.nCurrentDialogLine <= 4, "Page contains more than four lines");
            fprintf(report, "%d,%d,%d,%d,%d,%u,%d,%d,%d\n", group.first, order,
                id, page, g_TextLib.nCurrentDialogLine, g_TextLib.bCurrentFontColor,
                PAL_X(g_TextLib.posIcon), PAL_Y(g_TextLib.posIcon), pageWaits);
        }
        Require(terminated && messages == (translated ? (group.first == 1326 ? 8 : 15) : span + 1),
            "Dialogue fixture missing messages or terminator");
        Require(pageWaits - waitsBeforeGroup == (translated && group.first == 1333 ? 4 : 1),
            "Dialogue fixture missing page waits");
        SaveScales(directory, name + "-page-" + std::to_string(page));
        PAL_ClearDialog(FALSE);
    }
    // Synthetic boundary fixture, explicitly separate from unchanged resources:
    // full-width punctuation, escaped controls, color spanning a page, 3 pages.
    const WCHAR *controls[] = {L"\"一二三四五六七八九十，。！？",
        L"黄色连续第二行", L"黄色连续第三行", L"黄色连续第四行",
        L"跨页仍为黄色\"恢复", L"\\-\\'\\@\\\"\\(\\)\\\\",
        L"'红色'恢复@红色@恢复", L"-青色-恢复", L"第三页：结束。"};
    PAL_MakeScene();
    PAL_StartDialog(kDialogUpper, 0, 8, FALSE);
    for (int i = 0; i < 9; ++i) {
        if (i && i % 4 == 0) {
            SaveScales(directory, "controls-page-" + std::to_string(i / 4));
            SDL_Event event = {};
            event.type = SDL_USEREVENT; event.user.code = 10;
            Require(SDL_PushEvent(&event) == 1, "Cannot queue control-page advance");
        }
        g_TextLib.fUserSkip = TRUE; g_TextLib.iDelayTime = 0;
        PAL_ShowDialogText(controls[i]);
        Require(g_TextLib.nCurrentDialogLine == i % 4 + 1, "Unexpected pagination boundary");
        Require(g_TextLib.bCurrentFontColor == (i < 4 ? 0x2d : 0x4f),
            "Color changed unexpectedly across page/control boundaries");
        fprintf(report, "controls,%d,-1,%d,%d,%u,%d,%d,%d\n", i, i / 4 + 1,
            g_TextLib.nCurrentDialogLine, g_TextLib.bCurrentFontColor,
            PAL_X(g_TextLib.posIcon), PAL_Y(g_TextLib.posIcon), pageWaits);
    }
    SaveScales(directory, "controls-page-3");
    Require(pageWaits == (translated ? 7 : 4), "Unexpected total page waits");
    PAL_ClearDialog(FALSE);
    fclose(report);
    PAL_ShutdownInput();
    PAL_FreeResources();
    printf("Pagination and color assertions passed; %d real page waits\n", pageWaits);
}
} // namespace

int RenderEvidence(int argc, char **argv) {
    if (argc != 6) {
        fprintf(stderr, "Usage: --render-evidence RESOURCE_DIR SLF_OR_DASH OUTPUT_DIR "
                        "cn|jp|jp-legacy|cn-jp-font|cn-jp-font-field|cn-pages|jp-pages\n");
        return 2;
    }
    const std::string mode(argv[5]), directory(argv[4]);
    const bool pages = mode == "cn-pages" || mode == "jp-pages";
    const bool translated = mode == "jp" || mode == "jp-legacy" || mode == "jp-pages";
    const bool fieldMenu = mode == "cn-jp-font-field";
    if (!translated && mode != "cn" && mode != "cn-jp-font" && !fieldMenu && !pages) return 2;
    if (translated && strcmp(argv[3], "-") == 0) return 2;
    try {
        Require(SDL_Init(pages ? SDL_INIT_VIDEO | SDL_INIT_EVENTS : 0) == 0, "SDL_Init failed");
        PAL_LoadConfig(FALSE);
        free(gConfig.pszGamePath);
        gConfig.pszGamePath = strdup(argv[2]);
        if (translated) gConfig.pszMsgFile = strdup(argv[3]);
        Require(PAL_InitGlobals() == 0 && gConfig.fIsWIN95, "Expected Win95 resources");
        Require(PAL_InitText() == 0, "Cannot load game text");
        if (mode == "cn-jp-font" || fieldMenu || pages) g_TextLib.iFontFlavor = kFontFlavorJapanese;
        if (pages) g_TextLib.fUseISOFont = FALSE;
        Require(PAL_InitFont(&gConfig) == 0, "Cannot load engine font");
        PAL_InitGameData(0);
        Require(PAL_InitUI() == 0, "Cannot load UI sprites");
        if (pages) {
            gConfig.fEnableGLSL = FALSE;
            gConfig.fUseTouchOverlay = FALSE;
            gConfig.fFullScreen = FALSE;
            gConfig.fKeepAspectRatio = TRUE;
            gConfig.dwTextureWidth = 320; gConfig.dwTextureHeight = 200;
            free(gConfig.pszScaleQuality); gConfig.pszScaleQuality = strdup("0");
            gpWindow = SDL_CreateWindow("SDLPAL source evidence", 0, 0, 640, 400, SDL_WINDOW_HIDDEN);
            Require(gpWindow && VIDEO_Startup() == 0, "Cannot initialize hidden source renderer");
            // This bundled SDL suppresses even target-texture drawing for a
            // hidden window. Notify its event watcher without showing an OS
            // window; all evidence below is read from the explicit target.
            SDL_Event shown = {};
            shown.type = SDL_WINDOWEVENT;
            shown.window.windowID = SDL_GetWindowID(gpWindow);
            shown.window.event = SDL_WINDOWEVENT_SHOWN;
            Require(SDL_PushEvent(&shown) == 1, "Cannot enable target rendering");
            Require((SDL_GetWindowFlags(gpWindow) & SDL_WINDOW_HIDDEN) != 0,
                "Source renderer unexpectedly opened a visible window");
            SDL_RendererInfo rendererInfo = {};
            Require(SDL_GetRendererInfo(gpRenderer, &rendererInfo) == 0, "Cannot read renderer info");
            printf("Renderer: %s; flags=%u; ScaleQuality=0; UseISOFont=0\n",
                rendererInfo.name, rendererInfo.flags);
            g_bRenderPaused = TRUE;
            PAL_SetPalette(0, FALSE);
            DrawPages(directory, translated);
            PAL_FreeUI(); PAL_FreeText(); PAL_FreeFont();
            VIDEO_Shutdown(); PAL_FreeGlobals(); SDL_Quit();
            return 0;
        }
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
            // Match PAL98's outside-battle menu for the same-font comparison.
            // The original modes retain their battle-menu fixture.
            PAL_MagicSelectionMenuInit(0, !fieldMenu, object);
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
