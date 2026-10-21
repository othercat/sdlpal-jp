// Opt-in resource-backed rendering tool; never compiled into Release builds.
// Uses the engine's drawing functions and skips only window presentation.
#include <cstdio>
#include <cstring>
#include <stdexcept>
#include <string>
#include <set>
#include <utility>
#include <vector>

extern "C" {
#include "main.h"
extern SDL_Surface *gpScreenReal;
#if SDL_VERSION_ATLEAST(2, 0, 0)
extern SDL_Window *gpWindow;
extern SDL_Renderer *gpRenderer;
extern SDL_Texture *gpTexture;
extern BOOL VIDEO_TestHiddenWindow;
#endif
extern void (*VIDEO_TestFrameHook)(void);
}

namespace {
void Require(bool ok, const char *what) {
    if (!ok) throw std::runtime_error(what);
}

void PrepareInn() {
    VIDEO_FillRect(gpScreen, nullptr, 0);
    // Reconstruct scene 2 from its resource scripts, without gameplay/input.
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

#include "portrait_effect_evidence.h"
}

#if SDL_VERSION_ATLEAST(2, 0, 0)
namespace {
bool portraitRGB = false;

std::vector<BYTE> ComposedRGB() {
    SDL_Color base[256];
    Require(PAL_ReadPalette(gpGlobals->wNumPalette, gpGlobals->fNightPalette, base),
        "Cannot read base palette");
    SDL_Surface *output = SDL_CreateRGBSurface(0, gpScreen->w, gpScreen->h, 32,
        0x00ff0000, 0x0000ff00, 0x000000ff, 0);
    Require(output && VIDEO_ComposeSurface(gpScreen, output, base) == 0,
        "Cannot compose source RGB");
    std::vector<BYTE> rgb;
    for (int y = 0; y < output->h; ++y)
        for (int x = 0; x < output->w; ++x) {
            Uint32 color = ((Uint32 *)((BYTE *)output->pixels + y * output->pitch))[x];
            rgb.push_back((color >> 16) & 255);
            rgb.push_back((color >> 8) & 255);
            rgb.push_back(color & 255);
        }
    SDL_FreeSurface(output);
    return rgb;
}

void Save(const std::string& directory, const std::string& name) {
    Require(SDL_SaveBMP(gpScreen, (directory + "/" + name + ".bmp").c_str()) == 0,
            "Cannot save BMP (create the output directory first)");
}

void DrawDescription(WORD object, bool item) {
    if (!gConfig.fIsWIN95) {
        const WCHAR *text = PAL_GetObjectDesc(gpGlobals->lpObjectDesc, object);
        Require(text != nullptr, "Missing DOS object description");
        std::wstring remaining(text);
        int y = item ? 150 - gConfig.ScreenLayout.ExtraItemDescLines * 16 :
            PAL_Y(gConfig.ScreenLayout.MagicDescMsgPos) + 3;
        const int x = item ? 75 : PAL_X(gConfig.ScreenLayout.MagicDescMsgPos);
        while (true) {
            const size_t split = remaining.find(L'*');
            const std::wstring line = remaining.substr(0, split);
            PAL_DrawText(line.c_str(), PAL_XY(x, y), DESCTEXT_COLOR, TRUE, FALSE, FALSE);
            if (split == std::wstring::npos) break;
            remaining.erase(0, split + 1);
            y += 16;
        }
        return;
    }
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
    VIDEO_FillRect(gpScreen, nullptr, 0xfe); // distinguish black shadows from background
    DrawDescription(object, item);
    int count = 0;
    for (int y = 0; y < gpScreen->h; ++y) {
        const BYTE *row = (BYTE *)gpScreen->pixels + y * gpScreen->pitch;
        for (int x = 320; x < gpScreen->w; ++x) count += row[x] == DESCTEXT_COLOR;
    }
    VIDEO_FreeSurface(gpScreen);
    gpScreen = screen;
    return count;
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

void SaveScales(const std::string& directory, const std::string& name);

// Portrait fixtures exercise the unmodified production RGM/palette path. A
// separate verifier checks every indexed pixel, palette and background byte.
// Only selected cases are published as scaled images; all frames are archived.
void DrawPortraitEvidence(const std::string& directory) {
    FILE *fixtures = fopen((directory + "/portrait-fixtures.csv").c_str(), "r");
    FILE *report = fopen((directory + "/portraits.csv").c_str(), "w");
    FILE *frames = fopen((directory + "/portrait-frames.bin").c_str(), "wb");
    FILE *rgbFrames = portraitRGB ?
        fopen((directory + "/portrait-rgb.bin").c_str(), "wb") : nullptr;
    Require(fixtures && report && frames, "Cannot open portrait fixtures/output");
    Require(!portraitRGB || rgbFrames, "Cannot open RGB output");
    char header[256], name[64];
    Require(fgets(header, sizeof(header), fixtures) != nullptr,
        "Missing portrait fixture header");
    fprintf(report, "name,face,location,palette,night,width,height,x,y,offset,stage,initial_black\n");
    unsigned face, location, palette, night, publish;
    int count = 0, fields;
    long offset = 0;
    while ((fields = fscanf(fixtures, "%63[^,],%u,%u,%u,%u,%u\n",
                            name, &face, &location, &palette, &night, &publish)) == 6) {
        Require(face > 0 && face < 256 && location <= 1 && palette < 9 && night <= 1 && publish <= 2,
                "Invalid portrait fixture");
        for (const char *p = name; *p; ++p)
            Require((*p >= 'a' && *p <= 'z') || (*p >= '0' && *p <= '9') || *p == '-',
                    "Unsafe portrait fixture name");
        BYTE rle[16384];
        Require(PAL_MKFReadChunk(rle, sizeof(rle), face, gpGlobals->f.fpRGM) > 0,
                "Missing portrait chunk");
        const int width = PAL_RLEGetWidth(rle), height = PAL_RLEGetHeight(rle);
        Require(width > 0 && height > 0 && width <= 320 && height <= 200,
                "Unexpected portrait dimensions");
        gpGlobals->wNumPalette = palette;
        gpGlobals->fNightPalette = night;
        PAL_SetPalette(palette, night);
        if (publish == 2) {
            SDL_Color black[256] = {};
            VIDEO_SetPalette(black);
        }
        // Pattern contains every palette index. It exposes accidental global
        // palette changes and preserves visible pixels through RLE transparency.
        VIDEO_ClearPortraits(gpScreen);
        for (int y = 0; y < 200; ++y)
            for (int x = 0; x < 320; ++x)
                ((BYTE *)gpScreen->pixels)[y * gpScreen->pitch + x] = (x / 4 + y / 3) & 255;
        PAL_ClearDialog(FALSE);
        PAL_StartDialog(location ? kDialogLower : kDialogUpper, 0, face, FALSE);
        const int left = location ? 270 - width / 2 : (width > 96 ? 0 : 48 - width / 2);
        const int top = location ? 144 - height / 2 : (height > 110 ? 0 : 55 - height / 2);
        SDL_Color colors[256];
        memcpy(colors, VIDEO_GetPalette(), sizeof(colors));
        for (int stage = 0; stage < (publish ? 4 : 1); ++stage) {
            if (stage == 1) {
                // The same palette rotation used by the real dialogue wait.
                const SDL_Color first = colors[0xf9];
                for (int i = 0xf9; i < 0xfe; ++i) colors[i] = colors[i + 1];
                colors[0xfe] = first;
                VIDEO_SetPalette(colors);
            } else if (stage == 2) {
                PAL_SetPalette(palette, night);
                memcpy(colors, VIDEO_GetPalette(), sizeof(colors));
                for (int i = 0; i < 256; ++i) {
                    colors[i].r /= 2; colors[i].g /= 2; colors[i].b /= 2;
                }
                VIDEO_SetPalette(colors);
            } else if (stage == 3) {
                memset(colors, 0, sizeof(colors));
                VIDEO_SetPalette(colors);
            }
            fprintf(report, "%s,%u,%u,%u,%u,%d,%d,%d,%d,%ld,%d,%d\n",
                name, face, location, palette, night, width, height, left, top, offset, stage, publish == 2);
            for (int y = 0; y < 200; ++y)
                Require(fwrite((BYTE *)gpScreen->pixels + y * gpScreen->pitch, 1, 320, frames) == 320,
                        "Cannot save portrait frame");
            SDL_Color *actual = VIDEO_GetPalette();
            for (int i = 0; i < 256; ++i) {
                const BYTE rgb[] = {actual[i].r, actual[i].g, actual[i].b};
                Require(fwrite(rgb, 1, 3, frames) == 3, "Cannot save portrait palette");
            }
            offset += 320 * 200 + 256 * 3;
            if (portraitRGB) {
                const auto rgb = ComposedRGB();
                Require(fwrite(rgb.data(), 1, rgb.size(), rgbFrames) == rgb.size(),
                    "Cannot save composed RGB frame");
            }
            if (publish && stage == 0) SaveScales(directory, name);
        }
        // The existing backup/restore path must retain the indexed portrait.
        std::vector<BYTE> original((BYTE *)gpScreen->pixels,
            (BYTE *)gpScreen->pixels + gpScreen->pitch * gpScreen->h);
        VIDEO_BackupScreen(gpScreen);
        VIDEO_FillRect(gpScreen, nullptr, 0);
        VIDEO_RestoreScreen(gpScreen);
        Require(memcmp(original.data(), gpScreen->pixels, original.size()) == 0,
                "Portrait backup/restore changed pixels");
        if (portraitRGB) {
            PAL_SetPalette(palette, night);
            const auto rgb = ComposedRGB();
            VIDEO_BackupScreen(gpScreen);
            VIDEO_FillRect(gpScreen, nullptr, 0);
            VIDEO_RestoreScreen(gpScreen);
            Require(rgb == ComposedRGB(), "Portrait RGB backup/restore changed");
            if (count == 0) {
                SDL_Color expected[256];
                Require(PAL_ReadPalette(5, FALSE, expected), "Missing palette 5");
                // Run the actual timed palette effect with an explicit target
                // different from globals. Composition must not overwrite its
                // shared PAL_GetPalette buffer.
                g_bRenderPaused = FALSE;
                PAL_FadeIn(5, FALSE, 1);
                for (int i = 0; i < 256; ++i) {
                    const SDL_Color actual = VIDEO_GetPalette()[i];
                    Require(actual.r == expected[i].r && actual.g == expected[i].g &&
                        actual.b == expected[i].b, "Renderer corrupted explicit-target fade");
                }
                g_bRenderPaused = TRUE;
                PAL_SetPalette(palette, night);
            }
        }
        ++count;
    }
    Require(fields == EOF && count > 0, "Invalid or empty portrait fixture list");
    fclose(fixtures); fclose(report); fclose(frames);
    if (rgbFrames) fclose(rgbFrames);
    printf("Portrait fixtures: %d; frame bytes: %ld; backup/restore passed\n", count, offset);
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
    if (portraitRGB) {
        const auto rgb = ComposedRGB();
        SDL_Surface *output = SDL_CreateRGBSurfaceFrom((void *)rgb.data(), 320, 200, 24,
            320 * 3, 0xff, 0xff00, 0xff0000, 0);
        Require(output && SDL_SaveBMP(output, (directory + "/" + name + "-rgb.bmp").c_str()) == 0,
            "Cannot save composed RGB view");
        SDL_FreeSurface(output);
    }
    SDL_Texture *previousTexture = gpTexture;
    SDL_Texture *previousTarget = SDL_GetRenderTarget(gpRenderer);
    const int widths[] = {640, 960, 800};
    for (int width : widths) {
        // The game framebuffer is opaque. Target-texture alpha is not coverage
        // (Direct3D readback can return zero); do not export it as transparency.
        SDL_Surface *output = SDL_CreateRGBSurface(0, width, width * 5 / 8, 32,
            0x00ff0000, 0x0000ff00, 0x000000ff, 0);
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
        Require(SDL_RenderReadPixels(gpRenderer, nullptr, SDL_PIXELFORMAT_RGB888,
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

void DrawSteamRecords(const std::string& directory) {
    // These are raw Chinese legacy records, before any Japanese SLF mapping.
    // Use the real loader/font/renderer, with a neutral source-test background.
    FILE *report = fopen((directory + "/steam-records.csv").c_str(), "w");
    Require(report != nullptr, "Cannot create Steam record report");
    fprintf(report, "kind,id,codepoints\n");
    const int ids[2][4] = {{5, 6, 7, 8}, {36, 37, 149, 150}};
    for (int kind = 0; kind < 2; ++kind) {
        VIDEO_FillRect(gpScreen, nullptr, 0);
        for (int row = 0; row < 4; ++row) {
            const int id = ids[kind][row];
            const WCHAR *text = kind ? PAL_GetWord(id) : PAL_GetMsg(id);
            Require(text != nullptr, "Steam record missing");
            const std::wstring label = (kind ? L"WORD " : L"MSG ") + std::to_wstring(id);
            PAL_DrawText(label.c_str(), PAL_XY(8, 4 + row * 48), MENUITEM_COLOR,
                         TRUE, FALSE, FALSE);
            PAL_DrawText(text, PAL_XY(8, 24 + row * 48), DESCTEXT_COLOR,
                         TRUE, FALSE, FALSE);
            fprintf(report, "%s,%d,", kind ? "word" : "msg", id);
            for (const WCHAR *p = text; *p; ++p) fprintf(report, "%04x ", (unsigned)*p);
            fprintf(report, "\n");
        }
        SaveScales(directory, kind ? "steam-word" : "steam-msg");
    }
    fclose(report);
}

std::string centerDirectory, centerName;
int centerWaits = 0;
int CaptureCenterMessage(const SDL_Event *event, volatile PALINPUTSTATE *state) {
    if (event->type != SDL_USEREVENT || event->user.code != 11)
        return AdvancePage(event, state);
    Require(g_TextLib.bDialogPosition == kDialogCenterWindow &&
        g_TextLib.nCurrentDialogLine == 0, "Expected acquisition window wait");
    // Capture during the real timed wait, before PAL_ShowDialogText removes the box.
    SaveScales(centerDirectory, centerName);
    ++centerWaits;
    state->dwKeyPress |= kKeySearch;
    return 1;
}

void DrawLongNames(const std::string& directory, bool grid) {
    Require(g_TextLib.iFontFlavor == kFontFlavorJapanese && !g_TextLib.fUseISOFont &&
        PAL_FontHeight() == 16 && gConfig.dwWordLength == 16,
        "Expected Japanese 16px font and two-column word layout");
    Require(gConfig.ScreenLayout.ExtraItemDescLines == 2 &&
        gConfig.ScreenLayout.ExtraMagicDescLines == 1 &&
        gConfig.ScreenLayout.MagicMPDescLines == PAL_XY(3, 0) &&
        gConfig.ScreenLayout.MagicMPSlashPos == PAL_XY(30, 14) &&
        gConfig.ScreenLayout.MagicMPNeededPos == PAL_XY(5, 14) &&
        gConfig.ScreenLayout.MagicMPCurrentPos == PAL_XY(31, 14) &&
        gConfig.ScreenLayout.MagicDescMsgPos == PAL_XY(70, 0),
        "Expected Japanese layout 81-87");
    Require(wcscmp(PAL_GetWord(270), L"紫金のひょうたん") == 0 &&
        wcscmp(PAL_GetWord(384), L"霊ひょうたんの術") == 0,
        "Expected eight-character resource names");
    gpGlobals->wMaxPartyMemberIndex = 0;
    gpGlobals->rgParty[0].wPlayerRole = 0;
    gpGlobals->g.PlayerRoles.rgwHP[0] = gpGlobals->g.PlayerRoles.rgwMaxHP[0] = 150;
    gpGlobals->g.PlayerRoles.rgwMP[0] = gpGlobals->g.PlayerRoles.rgwMaxMP[0] = 999;
    // In-memory menu fixtures only; no save, object record or resource is changed.
    memset(gpGlobals->g.PlayerRoles.rgwEquipment, 0, sizeof(gpGlobals->g.PlayerRoles.rgwEquipment));
    PrepareInn();
    FILE *report = fopen((directory + "/long-names.csv").c_str(), "w");
    Require(report != nullptr, "Cannot create long-name report");
    fprintf(report, "object_id,column,selected,description_object,clipped_description_ink\n");
    for (bool item : {true, false}) {
        const WORD object = item ? 270 : 384;
        for (int column = 0; column < 2; ++column) {
            // Magic menus sort by object ID; pick a neighbour on the needed side.
            const WORD neighbour = item ? 149 : (column == 0 ? 390 : 306);
            for (bool selected : {true, false}) {
                const WORD descriptionObject = selected ? object : neighbour;
                PAL_MakeScene();
                PAL_ClearKeyState();
                if (item) {
                    memset(gpGlobals->rgInventory, 0, sizeof(gpGlobals->rgInventory));
                    gpGlobals->rgInventory[column].wItem = object;
                    gpGlobals->rgInventory[1 - column].wItem = neighbour;
                    gpGlobals->rgInventory[0].nAmount = gpGlobals->rgInventory[1].nAmount = 99;
                    gpGlobals->iCurInvMenuItem = selected ? column : 1 - column;
                    PAL_ItemSelectMenuInit(kItemFlagUsable);
                    Require(PAL_ItemSelectMenuUpdate() == 0xffff, "Unexpected item menu action");
                } else {
                    memset(gpGlobals->g.PlayerRoles.rgwMagic, 0, sizeof(gpGlobals->g.PlayerRoles.rgwMagic));
                    gpGlobals->g.PlayerRoles.rgwMagic[0][0] = object;
                    gpGlobals->g.PlayerRoles.rgwMagic[1][0] = neighbour;
                    PAL_PlayerInfoBox(PAL_XY(45, 165), 0, 100, TIMEMETER_COLOR_DEFAULT, TRUE);
                    PAL_MagicSelectionMenuInit(0, FALSE, descriptionObject);
                    Require(PAL_MagicSelectionMenuUpdate() == 0xffff, "Unexpected magic menu action");
                }
                const std::string name = std::string(item ? "item-270-" : "magic-384-") +
                    (column == 0 ? "left-" : "right-") + (selected ? "selected" : "unselected");
                SaveScales(directory, name);
                const int clipped = CountClippedInk(descriptionObject, item);
                Require(clipped == 0, "Description ink extends beyond the right edge");
                fprintf(report, "%u,%d,%d,%u,%d\n", object, column, selected, descriptionObject, clipped);
            }
        }
    }
    fclose(report);
    if (grid) {
        // Deliberately repeated objects stress every full-width cell, including
        // the selected cell's left neighbour and the rows above/below it.
        // This is an in-memory boundary fixture, not a naturally acquired list.
        for (bool item : {true, false}) {
            PAL_MakeScene();
            PAL_ClearKeyState();
            if (item) {
                memset(gpGlobals->rgInventory, 0, sizeof(gpGlobals->rgInventory));
                for (int i = 0; i < 10; ++i) {
                    gpGlobals->rgInventory[i].wItem = 270;
                    gpGlobals->rgInventory[i].nAmount = 99;
                }
                gpGlobals->iCurInvMenuItem = 5;
                PAL_ItemSelectMenuInit(kItemFlagUsable);
                Require(PAL_ItemSelectMenuUpdate() == 0xffff, "Unexpected grid item action");
            } else {
                memset(gpGlobals->g.PlayerRoles.rgwMagic, 0, sizeof(gpGlobals->g.PlayerRoles.rgwMagic));
                for (int i = 0; i < 8; ++i) gpGlobals->g.PlayerRoles.rgwMagic[i][0] = 384;
                PAL_PlayerInfoBox(PAL_XY(45, 165), 0, 100, TIMEMETER_COLOR_DEFAULT, TRUE);
                PAL_MagicSelectionMenuInit(0, FALSE, 384);
                // Move to the third row/right column through the real menu
                // input path, without depending on its private selection index.
                for (int i = 0; i < 5; ++i) {
                    g_InputState.dwKeyPress = kKeyRight;
                    Require(PAL_MagicSelectionMenuUpdate() == 0xffff, "Unexpected grid magic action");
                }
                PAL_ClearKeyState();
            }
            SaveScales(directory, item ? "item-270-grid" : "magic-384-grid");
        }
    }
    PAL_FreeResources();
    printf("Rendered eight long-name menu states%s; no right-clipped description ink\n",
        grid ? " plus two dense grids, each at four sizes" : ", each at four sizes");
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

void DrawRecoveredDialogues(const std::string& directory, bool before, bool tournament, bool duplicates,
                           bool translations, bool dos = false) {
    // Input generated by the Issue #3/#4/#6/#8 verifiers after checking raw sources.
    // Neutral background: this verifies lookup/text/page rendering, not a route.
    Require(g_TextLib.iFontFlavor == kFontFlavorJapanese && !g_TextLib.fUseISOFont &&
        PAL_FontHeight() == 16, "Expected Japanese 16px font without ISO substitution");
    FILE *fixtures = fopen((directory + "/recovery-fixtures.csv").c_str(), "r");
    Require(fixtures != nullptr, "Missing recovery-fixtures.csv");
    FILE *report = fopen((directory + "/recovery.csv").c_str(), "w");
    Require(report != nullptr, "Cannot create recovery report");
    fprintf(report, "first,last,entries,clear_markers,drawn,pages,page_waits\n");
    FILE *texts = (duplicates || translations || dos) ?
        fopen((directory + "/effective-text.csv").c_str(), "w") : nullptr;
    Require(!(duplicates || translations || dos) || texts, "Cannot create effective-text report");
    if (texts) fprintf(texts, "first,last,order,codepoints\n");
    PAL_RegisterInputFilter(nullptr, duplicates ? CaptureCenterMessage : AdvancePage, nullptr);
    int first, last, oldCount, newCount, draw, op, a, b, c, matched = 0, absent = 0;
    int drawn = 0, expectedPresent = 0;
    std::set<std::pair<int, int>> keys;
    int fields;
    while ((fields = fscanf(fixtures, "%d,%d,%d,%d,%d,%d,%d,%d,%d",
                            &first, &last, &oldCount, &newCount, &draw, &op, &a, &b, &c)) == 9) {
        const int count = before ? oldCount : newCount;
        expectedPresent += count != 0;
        Require(first >= 0 && last >= first && last < 65536 && count >= 0 && count < 1024,
                "Invalid recovery fixture");
        Require(keys.insert(std::make_pair(first, last)).second, "Duplicate recovery fixture key");
        Require(draw == 0 || draw == 1, "Invalid recovery draw flag");
        drawn += draw;
        const std::string name = "dialogue-" + std::to_string(first);
        int page = 1, clears = 0, waitsBefore = pageWaits;
        const bool center = op == 0x003e;
        if (draw) {
            PAL_EndDialog();
            VIDEO_FillRect(gpScreen, nullptr, 0);
            const BYTE position = op == 0x003b ? kDialogCenter :
                (center ? kDialogCenterWindow : (op == 0x003d ? kDialogLower : kDialogUpper));
            Require(op >= 0x003b && op <= 0x003e && !c && (!center || (duplicates && count == 1)),
                "Unsupported fixture dialog command");
            PAL_StartDialog(position, (op == 0x003b || center) ? a : b,
                (op == 0x003b || center) ? 0 : a, FALSE);
        }
        for (int order = 0; order < count; ++order) {
            const int id = PAL_GetMsgNum(first, last - first, order);
            Require(id >= 0, "Engine mapping terminated before expected entry count");
            if (id == 0) {
                if (texts) fprintf(texts, "%d,%d,%d,CLEAR\n", first, last, order);
                ++clears;
                if (draw) {
                    SaveScales(directory, name + "-page-" + std::to_string(page++));
                    // A preceding ~NN timed line already resets the line count.
                    // PAL_ClearDialog then clears without another key wait.
                    const bool waits = g_TextLib.nCurrentDialogLine > 0;
                    if (waits) {
                        SDL_Event event = {};
                        event.type = SDL_USEREVENT; event.user.code = 5;
                        Require(SDL_PushEvent(&event) == 1, "Cannot queue recovery CLEAR");
                    }
                    const int prior = pageWaits;
                    PAL_ClearDialog(TRUE);
                    Require(pageWaits == prior + (waits ? 1 : 0), "Recovery CLEAR wait changed");
                    VIDEO_RestoreScreen(gpScreen);
                    VIDEO_UpdateScreen(nullptr);
                }
            } else {
                const WCHAR *line = PAL_GetMsg(id);
                Require(line && *line, "Recovered mapping contains empty text");
                if (texts) {
                    fprintf(texts, "%d,%d,%d,", first, last, order);
                    for (const WCHAR *ch = line; *ch; ++ch) fprintf(texts, "%04x ", (unsigned)*ch);
                    fprintf(texts, "\n");
                }
                if (draw) {
                    const bool automaticPage = g_TextLib.nCurrentDialogLine == 4;
                    const int prior = pageWaits;
                    if (automaticPage) {
                        SaveScales(directory, name + "-page-" + std::to_string(page++));
                        SDL_Event event = {};
                        event.type = SDL_USEREVENT; event.user.code = 10;
                        Require(SDL_PushEvent(&event) == 1, "Cannot queue recovery page");
                    }
                    const int priorCenter = centerWaits;
                    if (center) {
                        centerDirectory = directory; centerName = name + "-page-1";
                        SDL_Event event = {};
                        event.type = SDL_USEREVENT; event.user.code = 11;
                        Require(SDL_PushEvent(&event) == 1, "Cannot queue acquisition capture");
                    }
                    g_TextLib.fUserSkip = TRUE; g_TextLib.iDelayTime = 0;
                    PAL_ShowDialogText(line);
                    Require(centerWaits == priorCenter + (center ? 1 : 0),
                        "Acquisition window was not captured during its wait");
                    Require(pageWaits == prior + (automaticPage ? 1 : 0),
                            "Recovery automatic page wait changed");
                    Require(g_TextLib.nCurrentDialogLine <= 4, "Recovery page overflow");
                }
            }
        }
        Require(PAL_GetMsgNum(first, last - first, count) == -1, "Mapping lacks expected terminator");
        if (draw) {
            if (!center) SaveScales(directory, name + "-page-" + std::to_string(page));
            PAL_ClearDialog(FALSE);
        }
        fprintf(report, "%d,%d,%d,%d,%d,%d,%d\n", first, last, count, clears,
                draw, draw ? page : 0, pageWaits - waitsBefore);
        count ? ++matched : ++absent;
    }
    const bool omittedBaseline = before && !tournament && !duplicates && !translations && !dos;
    Require(fields == EOF && keys.size() == (dos ? 4476 : 4766) &&
        drawn == (translations ? 5 : (duplicates ? 6 : (tournament ? 10 : 8))) &&
        matched == (dos ? expectedPresent : (omittedBaseline ? 4647 : 4766)) &&
        absent == (dos ? 4476 - expectedPresent : (omittedBaseline ? 119 : 0)),
        "Incomplete recovery fixture coverage");
    Require(!duplicates || centerWaits == 2, "Incomplete acquisition window coverage");
    if (texts) fclose(texts);
    fclose(fixtures); fclose(report);
    PAL_ShutdownInput();
    printf("Engine lookup: %d mapped, %d absent; %d page waits; neutral source renders\n",
           matched, absent, pageWaits);
    if (duplicates) printf("Captured %d acquisition windows during real timed waits\n", centerWaits);
}

void DrawTranslationDescriptions(const std::string& directory) {
    FILE *fixtures = fopen((directory + "/translation-objects.csv").c_str(), "r");
    Require(fixtures != nullptr, "Missing translation-objects.csv");
    std::vector<std::pair<WORD, bool>> objects;
    std::set<WORD> seen;
    int object, item, fields;
    memset(gpGlobals->g.PlayerRoles.rgwMagic, 0, sizeof(gpGlobals->g.PlayerRoles.rgwMagic));
    int magics = 0;
    while ((fields = fscanf(fixtures, "%d,%d", &object, &item)) == 2) {
        Require(object > 0 && object < MAX_OBJECTS && (item == 0 || item == 1) &&
            seen.insert((WORD)object).second, "Invalid translation object fixture");
        objects.push_back(std::make_pair((WORD)object, item != 0));
        if (!item) {
            Require(magics < MAX_PLAYER_MAGICS, "Too many translation magic fixtures");
            gpGlobals->g.PlayerRoles.rgwMagic[magics++][0] = (WORD)object;
        }
    }
    Require(fields == EOF && !objects.empty(), "Incomplete translation object fixtures");
    fclose(fixtures);
    gpGlobals->wMaxPartyMemberIndex = 0;
    gpGlobals->rgParty[0].wPlayerRole = 0;
    gpGlobals->g.PlayerRoles.rgwHP[0] = gpGlobals->g.PlayerRoles.rgwMaxHP[0] = 999;
    gpGlobals->g.PlayerRoles.rgwMP[0] = gpGlobals->g.PlayerRoles.rgwMaxMP[0] = 999;
    FILE *report = fopen((directory + "/description-clipping.csv").c_str(), "w");
    Require(report != nullptr, "Cannot create translation description report");
    fprintf(report, "object_id,item,clipped_ink\n");
    for (const auto& entry : objects) {
        PAL_EndDialog();
        VIDEO_FillRect(gpScreen, nullptr, 0);
        PAL_ClearKeyState();
        if (entry.second) {
            memset(gpGlobals->rgInventory, 0, sizeof(gpGlobals->rgInventory));
            gpGlobals->rgInventory[0].wItem = entry.first;
            gpGlobals->rgInventory[0].nAmount = 2;
            gpGlobals->iCurInvMenuItem = 0;
            PAL_ItemSelectMenuInit(0);
            Require(PAL_ItemSelectMenuUpdate() == 0xffff, "Unexpected translation item action");
        } else {
            PAL_MagicSelectionMenuInit(0, TRUE, entry.first);
            Require(PAL_MagicSelectionMenuUpdate() == 0xffff, "Unexpected translation magic action");
        }
        SaveScales(directory, std::string(entry.second ? "item-" : "magic-") +
                   std::to_string(entry.first));
        fprintf(report, "%u,%d,%d\n", entry.first, entry.second,
                CountClippedInk(entry.first, entry.second));
    }
    fclose(report);
    printf("Source description menus: %u objects\n", (unsigned)objects.size());
}

void DrawDOSDescriptions(const std::string& directory) {
    FILE *fixtures = fopen((directory + "/dos-objects.csv").c_str(), "r");
    FILE *report = fopen((directory + "/dos-descriptions.csv").c_str(), "w");
    Require(fixtures && report, "Cannot open DOS description fixtures/report");
    fprintf(report, "object_id,item,drawn,overflow_ink,codepoints\n");
    gpGlobals->wMaxPartyMemberIndex = 0;
    gpGlobals->rgParty[0].wPlayerRole = 0;
    gpGlobals->g.PlayerRoles.rgwHP[0] = gpGlobals->g.PlayerRoles.rgwMaxHP[0] = 999;
    gpGlobals->g.PlayerRoles.rgwMP[0] = gpGlobals->g.PlayerRoles.rgwMaxMP[0] = 999;
    int object, item, draw, fields, drawn = 0;
    std::set<int> seen;
    while ((fields = fscanf(fixtures, "%d,%d,%d", &object, &item, &draw)) == 3) {
        Require(object > 0 && object < MAX_OBJECTS && (item == 0 || item == 1) &&
            (draw == 0 || draw == 1) && seen.insert(object).second, "Invalid DOS object fixture");
        const WCHAR *description = PAL_GetObjectDesc(gpGlobals->lpObjectDesc, object);
        Require(description && *description, "Empty DOS description");
        SDL_Surface *screen = gpScreen;
        gpScreen = SDL_CreateRGBSurface(0, 384, 256, 8, 0, 0, 0, 0);
        Require(gpScreen != nullptr, "Cannot allocate DOS overflow probe");
        VIDEO_FillRect(gpScreen, nullptr, 0xfe);
        DrawDescription((WORD)object, item != 0);
        int overflow = 0;
        std::vector<std::pair<int, int>> expectedInk;
        for (int y = 0; y < gpScreen->h; ++y) {
            const BYTE *row = (BYTE *)gpScreen->pixels + y * gpScreen->pitch;
            for (int x = 0; x < gpScreen->w; ++x) {
                overflow += (x >= 320 || y >= 200) && row[x] == DESCTEXT_COLOR;
                if (x < 320 && y < 200 && row[x] == DESCTEXT_COLOR)
                    expectedInk.push_back(std::make_pair(x, y));
            }
        }
        VIDEO_FreeSurface(gpScreen);
        gpScreen = screen;
        fprintf(report, "%d,%d,%d,%d,", object, item, draw, overflow);
        for (const WCHAR *ch = description; *ch; ++ch) fprintf(report, "%04x ", (unsigned)*ch);
        fprintf(report, "\n");
        if (!draw) continue;
        ++drawn;
        PAL_EndDialog();
        VIDEO_FillRect(gpScreen, nullptr, 0);
        PAL_ClearKeyState();
        if (item) {
            memset(gpGlobals->rgInventory, 0, sizeof(gpGlobals->rgInventory));
            gpGlobals->rgInventory[0].wItem = (WORD)object;
            gpGlobals->rgInventory[0].nAmount = 2;
            gpGlobals->iCurInvMenuItem = 0;
            PAL_ItemSelectMenuInit(0);
            Require(PAL_ItemSelectMenuUpdate() == 0xffff, "Unexpected DOS item action");
        } else {
            memset(gpGlobals->g.PlayerRoles.rgwMagic, 0, sizeof(gpGlobals->g.PlayerRoles.rgwMagic));
            gpGlobals->g.PlayerRoles.rgwMagic[0][0] = (WORD)object;
            PAL_MagicSelectionMenuInit(0, TRUE, (WORD)object);
            Require(PAL_MagicSelectionMenuUpdate() == 0xffff, "Unexpected DOS magic action");
        }
        for (const auto& point : expectedInk)
            Require(((BYTE *)gpScreen->pixels)[point.second * gpScreen->pitch + point.first] == DESCTEXT_COLOR,
                "Production menu obscured DOS description ink");
        SaveScales(directory, std::string(item ? "item-" : "magic-") + std::to_string(object));
    }
    Require(fields == EOF && seen.size() == 296 && drawn == 10, "Incomplete DOS description coverage");
    fclose(fixtures); fclose(report);
    printf("DOS descriptions: %u lookups/probes, %d source-rendered menus\n", (unsigned)seen.size(), drawn);
}
} // namespace

int RenderEvidence(int argc, char **argv) {
    if (argc != 6 && argc != 7) {
        fprintf(stderr, "Usage: --render-evidence RESOURCE_DIR_OR_@config SLF_OR_DASH OUTPUT_DIR MODE [PORTRAIT_FILE]\nModes: "
                        "cn|jp|jp-legacy|cn-jp-font|cn-jp-font-field|cn-pages|jp-pages|jp-long-names|jp-cursor-grid|jp-recovery-before|jp-recovery|jp-npc-before|jp-npc|jp-duplicates-before|jp-duplicates|jp-translation-before|jp-translation|dos-before|dos|dos-layout-before|jp-portraits|dos-portraits|jp-portraits-rgb|dos-portraits-rgb|jp-translation-rgb|dos-rgb|jp-translation-night-rgb|dos-night-rgb|steam-records\n");
        return 2;
    }
    std::string mode(argv[5]);
    const std::string directory(argv[4]);
    const bool glsl = mode == "jp-portrait-effects-glsl" || mode == "dos-portrait-effects-glsl";
    if (glsl) mode.erase(mode.size() - 5);
    const bool steamRecords = mode == "steam-records";
    const bool pages = mode == "cn-pages" || mode == "jp-pages";
    const bool effects = mode == "jp-portrait-effects" || mode == "dos-portrait-effects";
    const bool longNames = mode == "jp-long-names" || mode == "jp-cursor-grid";
    const bool tournament = mode == "jp-npc-before" || mode == "jp-npc";
    const bool duplicates = mode == "jp-duplicates-before" || mode == "jp-duplicates";
    const bool translations = mode == "jp-translation-before" || mode == "jp-translation" ||
        mode == "jp-translation-rgb" || mode == "jp-translation-night-rgb";
    portraitRGB = mode == "jp-portraits-rgb" || mode == "dos-portraits-rgb" ||
        mode == "jp-translation-rgb" || mode == "dos-rgb" ||
        mode == "jp-translation-night-rgb" || mode == "dos-night-rgb";
    const bool portraits = mode == "jp-portraits" || mode == "dos-portraits" ||
        mode == "jp-portraits-rgb" || mode == "dos-portraits-rgb";
    const bool dos = mode == "dos" || mode == "dos-before" || mode == "dos-layout-before" ||
        mode == "dos-portraits" || mode == "dos-portraits-rgb" || mode == "dos-rgb" ||
        mode == "dos-night-rgb" || mode == "dos-portrait-effects";
    const bool recovery = mode == "jp-recovery-before" || mode == "jp-recovery" ||
        tournament || duplicates || translations || (dos && !portraits);
    const bool scaled = pages || longNames || recovery || portraits || effects || steamRecords;
    const bool translated = mode == "jp" || mode == "jp-legacy" || mode == "jp-pages" || longNames || recovery || portraits || effects;
    const bool fieldMenu = mode == "cn-jp-font-field";
    if (!translated && mode != "cn" && mode != "cn-jp-font" && !fieldMenu && !pages && !steamRecords) return 2;
    if (translated && strcmp(argv[3], "-") == 0) return 2;
    try {
        Require(SDL_Init(scaled ? SDL_INIT_VIDEO | SDL_INIT_EVENTS : 0) == 0, "SDL_Init failed");
        const bool fromConfig = strcmp(argv[2], "@config") == 0;
        PAL_LoadConfig(fromConfig);
        if (!fromConfig) {
            free(gConfig.pszGamePath);
            gConfig.pszGamePath = strdup(argv[2]);
        }
        if (translated) { free(gConfig.pszMsgFile); gConfig.pszMsgFile = strdup(argv[3]); }
        if (argc == 7) { free(gConfig.pszPortraitFile); gConfig.pszPortraitFile = strdup(argv[6]); }
        Require(PAL_InitGlobals() == 0 && (steamRecords || !!gConfig.fIsWIN95 == !dos), "Unexpected resource version");
        Require(PAL_InitText() == 0, "Cannot load game text");
        if (mode == "cn-jp-font" || fieldMenu || pages || steamRecords) g_TextLib.iFontFlavor = kFontFlavorJapanese;
        if (pages || steamRecords) g_TextLib.fUseISOFont = FALSE;
        Require(PAL_InitFont(&gConfig) == 0, "Cannot load engine font");
        PAL_InitGameData(0);
        Require(PAL_InitUI() == 0, "Cannot load UI sprites");
        if (scaled) {
            gConfig.fEnableGLSL = glsl;
            gConfig.fUseTouchOverlay = FALSE;
            gConfig.fFullScreen = FALSE;
            gConfig.fKeepAspectRatio = TRUE;
            gConfig.dwTextureWidth = 320; gConfig.dwTextureHeight = 200;
            gConfig.dwScreenWidth = 640; gConfig.dwScreenHeight = 400;
            free(gConfig.pszScaleQuality); gConfig.pszScaleQuality = strdup("0");
            VIDEO_TestHiddenWindow = TRUE;
            if (!glsl)
                gpWindow = SDL_CreateWindow("SDLPAL source evidence", 0, 0, 640, 400, SDL_WINDOW_HIDDEN);
            Require(!glsl || (gConfig.pszShader && *gConfig.pszShader), "GLSL evidence requires a configured shader");
            Require(VIDEO_Startup() == 0 && gpWindow, "Cannot initialize hidden source renderer");
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
            gpGlobals->fNightPalette = mode.find("-night-") != std::string::npos;
            PAL_SetPalette(0, gpGlobals->fNightPalette);
            if (steamRecords) DrawSteamRecords(directory);
            else if (effects) DrawPortraitEffects(directory);
            else if (portraits) DrawPortraitEvidence(directory);
            else if (longNames) DrawLongNames(directory, mode == "jp-cursor-grid");
            else if (recovery) {
                if (mode != "dos-layout-before")
                    DrawRecoveredDialogues(directory, mode == "jp-recovery-before" ||
                        mode == "jp-npc-before" || mode == "jp-duplicates-before" ||
                        mode == "jp-translation-before" || mode == "dos-before",
                        tournament, duplicates, translations, dos);
                if (translations) DrawTranslationDescriptions(directory);
                if (dos && mode != "dos-before") {
                    if (mode == "dos-layout-before") {
                        // Reproduce the original DOS hardcoded coordinates only.
                        gConfig.ScreenLayout.MagicMPDescLines = PAL_XY(5, 0);
                        gConfig.ScreenLayout.MagicMPSlashPos = PAL_XY(45, 14);
                        gConfig.ScreenLayout.MagicMPNeededPos = PAL_XY(15, 14);
                        gConfig.ScreenLayout.MagicMPCurrentPos = PAL_XY(50, 14);
                        gConfig.ScreenLayout.MagicDescMsgPos = PAL_XY(102, 0);
                    }
                    DrawDOSDescriptions(directory);
                }
            }
            else DrawPages(directory, translated);
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
            VIDEO_FillRect(gpScreen, nullptr, 0);
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
        VIDEO_FillRect(gpScreen, nullptr, 0);
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
        VIDEO_FreeSurface(gpScreen);
        VIDEO_FreeSurface(gpScreenBak);
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
int RenderEvidence(int argc, char **argv) {
    if ((argc != 6 && argc != 7) ||
        (strcmp(argv[5], "jp-portrait-effects") && strcmp(argv[5], "dos-portrait-effects"))) {
        fprintf(stderr, "SDL1 evidence supports jp-portrait-effects|dos-portrait-effects only.\n");
        return 2;
    }
    try {
        // SDL1 dummy exercises its indexed video surface without opening a window.
        char driver[64] = {};
        Require(SDL_Init(SDL_INIT_VIDEO) == 0, "SDL1 video initialization failed");
        Require(SDL_VideoDriverName(driver, sizeof(driver)) && !strcmp(driver, "dummy"),
            "SDL1 source evidence requires SDL_VIDEODRIVER=dummy");
        PAL_LoadConfig(!strcmp(argv[2], "@config"));
        if (strcmp(argv[2], "@config")) {
            free(gConfig.pszGamePath); gConfig.pszGamePath = strdup(argv[2]);
        }
        free(gConfig.pszMsgFile); gConfig.pszMsgFile = strdup(argv[3]);
        if (argc == 7) { free(gConfig.pszPortraitFile); gConfig.pszPortraitFile = strdup(argv[6]); }
        Require(PAL_InitGlobals() == 0 && !!gConfig.fIsWIN95 == !strcmp(argv[5], "jp-portrait-effects"),
            "Unexpected SDL1 resource version");
        Require(PAL_InitText() == 0 && PAL_InitFont(&gConfig) == 0, "Cannot load text/font");
        PAL_InitGameData(0);
        Require(PAL_InitUI() == 0, "Cannot load UI");
        gConfig.fFullScreen = FALSE; gConfig.fKeepAspectRatio = TRUE;
        gConfig.dwScreenWidth = 640; gConfig.dwScreenHeight = 400;
        Require(VIDEO_Startup() == 0, "Cannot initialize SDL1 indexed video");
        g_bRenderPaused = TRUE;
        PAL_SetPalette(0, FALSE);
        printf("Renderer: SDL1 %s; indexed palette fallback; 640x400\n", driver);
        DrawPortraitEffects(argv[4]);
        PAL_FreeUI(); PAL_FreeText(); PAL_FreeFont();
        VIDEO_Shutdown(); PAL_FreeGlobals(); SDL_Quit();
        return 0;
    } catch (const std::exception& e) {
        fprintf(stderr, "SDL1 evidence failed: %s (%s)\n", e.what(), SDL_GetError());
        return 1;
    }
}
#endif
