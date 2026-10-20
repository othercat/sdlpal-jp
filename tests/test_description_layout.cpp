#include <gtest/gtest.h>
#include <vector>
#include <cstdio>
#include <utility>

extern "C" {
#include "main.h"
}

namespace {
std::vector<BYTE> PortraitPack(bool win) {
    std::vector<BYTE> pack(16 + 768 + 8 + 4, 0);
    memcpy(pack.data(), "PALJPOR1", 8);
    pack[8] = 1; pack[10] = win; pack[12] = 1;
    pack[16 + 3] = 248; // source color 1
    pack[784] = 1; pack[786] = 2; pack[788] = 2;
    pack[792] = 1; pack[795] = 1;
    return pack;
}

bool ReadPortraitPack(const std::vector<BYTE>& pack, bool win) {
    FILE *file = tmpfile();
    if (!file) return false;
    const bool written = fwrite(pack.data(), 1, pack.size(), file) == pack.size();
    rewind(file);
    const bool loaded = written && PAL_ReadPortraitFile(file, win);
    fclose(file);
    return loaded;
}
}

TEST(PortraitPalettes, RejectsWrongTargetAndTruncatedOrAmbiguousData) {
    const auto valid = PortraitPack(true);
    ASSERT_TRUE(ReadPortraitPack(valid, true));
    EXPECT_FALSE(ReadPortraitPack(valid, false));
    for (size_t size : {size_t(0), size_t(15), size_t(783), valid.size() - 1}) {
        const std::vector<BYTE> truncated(valid.begin(), valid.begin() + size);
        EXPECT_FALSE(ReadPortraitPack(truncated, true));
    }
    auto trailing = valid; trailing.push_back(0);
    EXPECT_FALSE(ReadPortraitPack(trailing, true));
    auto duplicate = valid;
    duplicate[12] = 2;
    duplicate.insert(duplicate.end(), valid.begin() + 784, valid.end());
    EXPECT_FALSE(ReadPortraitPack(duplicate, true));
    ASSERT_TRUE(ReadPortraitPack(PortraitPack(false), false));
    PAL_FreeText();
}

TEST(PortraitPalettes, BoundsVersionAndReservedFieldsAreChecked) {
    const auto valid = PortraitPack(true);
    for (const auto change : {std::make_pair(0, 0), std::make_pair(8, 2),
            std::make_pair(12, 0), std::make_pair(12, 128), std::make_pair(14, 1),
            std::make_pair(784, 0), std::make_pair(784, 128), std::make_pair(786, 0),
            std::make_pair(787, 2), std::make_pair(788, 0), std::make_pair(788, 201),
            std::make_pair(790, 1)}) {
        auto bad = valid;
        bad[change.first] = change.second;
        EXPECT_FALSE(ReadPortraitPack(bad, true));
    }
    EXPECT_FALSE(PAL_ReadPortraitFile(nullptr, TRUE));
    ASSERT_TRUE(ReadPortraitPack(valid, true));
    // The reviewed PC portraits include widths/heights greater than 127.
    auto large = valid;
    large[786] = 135; large[788] = 131;
    large.resize(792 + 135 * 131, 1);
    ASSERT_TRUE(ReadPortraitPack(large, true));
    PAL_FreeText();
}

TEST(PortraitPalettes, ConfigurationIsOptInAndCanBeCleared) {
    PAL_FreeConfig();
    PAL_LoadConfig(FALSE);
    EXPECT_EQ(nullptr, gConfig.pszPortraitFile);
    EXPECT_STREQ("PortraitFileName", PAL_ConfigName(PALCFG_PORTRAITFILE));
    ConfigValue value = {};
    value.sValue = "portraits.por";
    PAL_SetConfigItem(PALCFG_PORTRAITFILE, value);
    EXPECT_STREQ("portraits.por", PAL_GetConfigItem(PALCFG_PORTRAITFILE, FALSE).sValue);
    value.sValue = "";
    PAL_SetConfigItem(PALCFG_PORTRAITFILE, value);
    EXPECT_EQ(nullptr, gConfig.pszPortraitFile);
    PAL_FreeConfig();
}

#if SDL_VERSION_ATLEAST(2,0,0)
namespace {
struct PortraitCanvas {
    SDL_Surface *indexed = SDL_CreateRGBSurface(0, 4, 4, 8, 0, 0, 0, 0);
    SDL_Surface *rgb = SDL_CreateRGBSurface(0, 4, 4, 32,
        0x00ff0000, 0x0000ff00, 0x000000ff, 0xff000000);
    SDL_Color base[256] = {};
    BYTE colors[768] = {};
    PortraitCanvas() {
        for (int i = 0; i < 256; ++i) {
            base[i].r = i; base[i].g = i / 2; base[i].b = i / 3;
        }
        colors[3] = 248; colors[4] = 160; colors[5] = 104;
        // Index 2 is opaque black; source index 0 alone is transparent.
        const BYTE pixels[] = {1, 0, 2, 1};
        SDL_SetPaletteColors(indexed->format->palette, base, 0, 256);
        VIDEO_FillRect(indexed, nullptr, 7);
        VIDEO_SetPortrait(indexed, pixels, 2, 2, PAL_XY(1, 1), colors);
    }
    ~PortraitCanvas() { VIDEO_FreeSurface(indexed); SDL_FreeSurface(rgb); }
    Uint32 Pixel(int x, int y) {
        return ((Uint32 *)((BYTE *)rgb->pixels + y * rgb->pitch))[x] & 0xffffff;
    }
    void Compose() { ASSERT_EQ(0, VIDEO_ComposeSurface(indexed, rgb, base)); }
};
}

TEST(PortraitColors, IndependentRGBTransparencyWaitAndAllBlackFadeLevels) {
    PortraitCanvas canvas;
    const auto original = std::vector<BYTE>((BYTE *)canvas.indexed->pixels,
        (BYTE *)canvas.indexed->pixels + 16);
    for (int level = 0; level <= 64; ++level) {
        SDL_Color colors[256] = {};
        for (int i = 0; i < 256; ++i) {
            colors[i].r = canvas.base[i].r * level / 64;
            colors[i].g = canvas.base[i].g * level / 64;
            colors[i].b = canvas.base[i].b * level / 64;
        }
        colors[249].r ^= 255; // A wait color must never recolor the portrait.
        SDL_SetPaletteColors(canvas.indexed->format->palette, colors, 0, 256);
        canvas.Compose();
        EXPECT_EQ(Uint32((248 * level / 64) << 16 | (160 * level / 64) << 8 |
            104 * level / 64), canvas.Pixel(1, 1));
        EXPECT_EQ(0u, canvas.Pixel(1, 2)); // opaque black
        EXPECT_EQ(Uint32((7 * level / 64) << 16 | (3 * level / 64) << 8 |
            2 * level / 64), canvas.Pixel(2, 1)); // transparent padding
    }
    EXPECT_EQ(0, memcmp(original.data(), canvas.indexed->pixels, original.size()));
    // A nonuniform special effect must preserve the existing indexed result.
    SDL_SetPaletteColors(canvas.indexed->format->palette, canvas.base, 0, 256);
    SDL_Color changed = {1, 2, 3, 255};
    SDL_SetPaletteColors(canvas.indexed->format->palette, &changed, 7, 1);
    canvas.Compose();
    EXPECT_EQ(0x010203u, canvas.Pixel(1, 1));
}

TEST(PortraitColors, CopiesRestoreCoverageAndSameIndexDrawingErasesIt) {
    PortraitCanvas canvas;
    SDL_Rect area = {1, 1, 2, 2};
    SDL_Surface *saved = SDL_CreateRGBSurface(0, 2, 2, 8, 0, 0, 0, 0);
    SDL_SetPaletteColors(saved->format->palette, canvas.base, 0, 256);
    ASSERT_EQ(0, VIDEO_CopySurface(canvas.indexed, &area, saved, nullptr));
    // Identical index writes must still cover the portrait (no equality heuristic).
    const BYTE rle[] = {1, 0, 1, 0, 1, 7};
    PAL_RLEBlitToSurface(rle, canvas.indexed, PAL_XY(1, 1));
    canvas.Compose();
    EXPECT_EQ(0x070302u, canvas.Pixel(1, 1));
    ASSERT_EQ(0, VIDEO_CopySurface(saved, nullptr, canvas.indexed, &area));
    canvas.Compose();
    EXPECT_EQ(0xf8a068u, canvas.Pixel(1, 1));
    VIDEO_FillRect(canvas.indexed, &area, 7);
    canvas.Compose();
    EXPECT_EQ(0x070302u, canvas.Pixel(1, 2));
    // Clipped fill must clear only the covered target pixels.
    VIDEO_CopySurface(saved, nullptr, canvas.indexed, &area);
    SDL_Rect clip = {1, 1, 1, 1};
    SDL_SetClipRect(canvas.indexed, &clip);
    VIDEO_FillRect(canvas.indexed, nullptr, 7);
    SDL_SetClipRect(canvas.indexed, nullptr);
    canvas.Compose();
    EXPECT_EQ(0x070302u, canvas.Pixel(1, 1));
    EXPECT_EQ(0xf8a068u, canvas.Pixel(2, 2));
    VIDEO_ClearPortraits(canvas.indexed);
    canvas.Compose();
    EXPECT_EQ(0x070302u, canvas.Pixel(2, 2));
    VIDEO_FreeSurface(saved);
}

TEST(PortraitColors, ClippedPortraitPlacementAndFullReset) {
    PortraitCanvas canvas;
    const BYTE pixels[] = {1, 1, 1, 1};
    VIDEO_SetPortrait(canvas.indexed, pixels, 2, 2, PAL_XY(-1, -1), canvas.colors);
    canvas.Compose();
    EXPECT_EQ(0xf8a068u, canvas.Pixel(0, 0));
    VIDEO_ClearPortraits(canvas.indexed);
    canvas.Compose();
    EXPECT_EQ(0x070302u, canvas.Pixel(0, 0));
    EXPECT_EQ(0x070302u, canvas.Pixel(1, 1));
}
#endif

// Run from the repository root. These fixtures need no proprietary game data.
class DescriptionLayout : public testing::Test {
protected:
    EVENTOBJECT *events;
    SCRIPTENTRY scripts[3];

    void SetUp() override {
        memset(scripts, 0, sizeof(scripts));
        scripts[1].wOperation = 0xffff;
        scripts[1].rgwOperand[0] = 1;
        memset(gpGlobals, 0, sizeof(*gpGlobals));
        // Autoscript forms an event pointer even for description flags/index 0.
        events = (EVENTOBJECT *)calloc(PAL_ITEM_DESC_BOTTOM + 1, sizeof(EVENTOBJECT));
        ASSERT_NE(nullptr, events);
        gpGlobals->g.lprgEventObject = events + 1;
        gpGlobals->g.lprgScriptEntry = scripts;
        gpScreen = SDL_CreateRGBSurface(0, 320, 200, 8, 0, 0, 0, 0);
        ASSERT_NE(nullptr, gpScreen);
        PAL_LoadConfig(FALSE);
    }

    void TearDown() override {
        PAL_FreeObjectDesc(gpGlobals->lpObjectDesc);
        gpGlobals->lpObjectDesc = nullptr;
        PAL_FreeText();
        PAL_FreeFont();
        PAL_FreeConfig();
        SDL_FreeSurface(gpScreen);
        gpScreen = nullptr;
        free(events);
        memset(gpGlobals, 0, sizeof(*gpGlobals));
    }

    void Load(const char *filename) {
        PAL_FreeText();
        PAL_FreeConfig();
        PAL_LoadConfig(FALSE);
        gConfig.fIsWIN95 = TRUE;
        gConfig.pszMsgFile = strdup(filename);
        ASSERT_EQ(0, PAL_InitText());
        ASSERT_EQ(0, PAL_InitFont(&gConfig));
    }

    std::vector<BYTE> Render(WORD flags) {
        SDL_FillRect(gpScreen, nullptr, 0);
        EXPECT_EQ(2, PAL_RunAutoScript(1, flags));
        BYTE *pixels = (BYTE *)gpScreen->pixels;
        return std::vector<BYTE>(pixels, pixels + gpScreen->pitch * gpScreen->h);
    }

    size_t Ink(const std::vector<BYTE>& pixels) {
        size_t count = 0;
        for (BYTE pixel : pixels) count += pixel != 0;
        return count;
    }
};

TEST_F(DescriptionLayout, LegacyDefaultsAndJapaneseSLFRenderWithoutItemRegression) {
    Load("tests/fixtures/description-legacy.slf");
    ASSERT_FALSE(HasFatalFailure());
    EXPECT_EQ(PAL_XY(5, 0), gConfig.ScreenLayout.MagicMPDescLines);
    EXPECT_EQ(PAL_XY(45, 14), gConfig.ScreenLayout.MagicMPSlashPos);
    EXPECT_EQ(PAL_XY(15, 14), gConfig.ScreenLayout.MagicMPNeededPos);
    EXPECT_EQ(PAL_XY(50, 14), gConfig.ScreenLayout.MagicMPCurrentPos);
    EXPECT_EQ(PAL_XY(102, 0), gConfig.ScreenLayout.MagicDescMsgPos);
    const auto legacyMagic = Render(0);
    const auto legacyItem = Render(PAL_ITEM_DESC_BOTTOM);

    Load("tests/fixtures/description-japanese-layout.slf");
    ASSERT_FALSE(HasFatalFailure());
    EXPECT_EQ(PAL_XY(3, 0), gConfig.ScreenLayout.MagicMPDescLines);
    EXPECT_EQ(PAL_XY(30, 14), gConfig.ScreenLayout.MagicMPSlashPos);
    EXPECT_EQ(PAL_XY(5, 14), gConfig.ScreenLayout.MagicMPNeededPos);
    EXPECT_EQ(PAL_XY(31, 14), gConfig.ScreenLayout.MagicMPCurrentPos);
    EXPECT_EQ(PAL_XY(70, 0), gConfig.ScreenLayout.MagicDescMsgPos);
    const auto japaneseMagic = Render(0);
    const auto japaneseItem = Render(PAL_ITEM_DESC_BOTTOM);

    // The real autoscript + font renderer exposes the previously clipped tail.
    EXPECT_GT(Ink(japaneseMagic), Ink(legacyMagic));
    EXPECT_GT(Ink(legacyMagic), 0u);
    EXPECT_EQ(legacyItem, japaneseItem);
    EXPECT_EQ(Ink(japaneseMagic), Ink(japaneseItem));
}

TEST_F(DescriptionLayout, ResourceTargetRejectsBothCrossVersionDirectionsBeforeLoading) {
    const char *paths[] = {"tests/fixtures/description-dos-version.slf",
                          "tests/fixtures/description-japanese-layout.slf"};
    for (int target = 0; target < 2; ++target) {
        PAL_FreeObjectDesc(gpGlobals->lpObjectDesc);
        gpGlobals->lpObjectDesc = nullptr;
        PAL_FreeText();
        PAL_FreeConfig();
        PAL_LoadConfig(FALSE);
        gConfig.fIsWIN95 = !target;
        gConfig.pszMsgFile = strdup(paths[target]);
        EXPECT_EQ(-1, PAL_InitText());
        EXPECT_EQ(nullptr, g_TextLib.lpMsgBuf);
        EXPECT_EQ(nullptr, gpGlobals->lpObjectDesc);
        gConfig.fIsWIN95 = target;
        ASSERT_EQ(0, PAL_InitText());
        if (!target) {
            const int id = PAL_GetMsgNum(0, 0, 0);
            ASSERT_GT(id, 0);
            EXPECT_STREQ(L"Locked door", PAL_GetMsg(id));
            EXPECT_STREQ(L"First*Second", PAL_GetObjectDesc(gpGlobals->lpObjectDesc, 266));
            EXPECT_EQ(nullptr, PAL_GetObjectDesc(gpGlobals->lpObjectDesc, 106));
        }
    }
}
