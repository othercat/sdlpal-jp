#include <gtest/gtest.h>
#include <vector>

extern "C" {
#include "main.h"
}

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
