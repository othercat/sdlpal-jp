// Included by render_evidence.cpp only. Calls the real synchronous effect
// functions and observes their uploaded frame; never emulates the effects.
namespace portrait_effects {
FILE *metadata = nullptr, *frames = nullptr;
std::string current, directory;
int sequence = 0, frame = 0, backupFrames = 0;
SDL_Surface *baseScene = nullptr, *initial = nullptr;

void Capture() {
    if (current.empty()) return;
#if SDL_VERSION_ATLEAST(2,0,0)
    Require(gpScreenReal->w == 320 && gpScreenReal->h == 200 &&
        gpScreenReal->format->BytesPerPixel == 4, "Unexpected effect framebuffer");
#else
    Require(gpScreenReal->w == 640 && gpScreenReal->h == 400 &&
        gpScreenReal->format->BytesPerPixel == 1, "Unexpected SDL1 framebuffer");
#endif
    SDL_Surface *indexed = frame < backupFrames ? gpScreenBak : gpScreen;
    fprintf(metadata, "%s,%d,%d\n", current.c_str(), frame, sequence);
    for (int y = 0; y < 200; ++y)
        Require(fwrite((BYTE *)indexed->pixels + y * indexed->pitch, 1, 320, frames) == 320,
            "Cannot write effect indices");
    for (int i = 0; i < 256; ++i) {
        SDL_Color c = indexed->format->palette->colors[i];
        const BYTE rgb[] = {c.r, c.g, c.b};
        Require(fwrite(rgb, 1, 3, frames) == 3, "Cannot write effect palette");
    }
    std::vector<BYTE> rgb(320 * 200 * 3);
    for (int y = 0; y < 200; ++y)
        for (int x = 0; x < 320; ++x) {
#if SDL_VERSION_ATLEAST(2,0,0)
            Uint32 c = ((Uint32 *)((BYTE *)gpScreenReal->pixels + y * gpScreenReal->pitch))[x];
#else
            Uint32 c = ((BYTE *)gpScreenReal->pixels)[y * 2 * gpScreenReal->pitch + x * 2];
#endif
            SDL_GetRGB(c, gpScreenReal->format, &rgb[(y*320+x)*3],
                &rgb[(y*320+x)*3+1], &rgb[(y*320+x)*3+2]);
        }
    Require(fwrite(rgb.data(), 1, rgb.size(), frames) == rgb.size(), "Cannot write effect RGB");
    // Read the real SDL texture at representative intermediate frames as well.
    if (frame == 0 || frame == 15 || frame == 31 || frame == 71 || frame == 95) {
#if SDL_VERSION_ATLEAST(2,0,0)
        SDL_Surface *gpu = SDL_CreateRGBSurface(0, 640, 400, 32, 0xff0000, 0xff00, 0xff, 0);
        Require(gpu && SDL_RenderReadPixels(gpRenderer, nullptr, SDL_PIXELFORMAT_RGB888,
            gpu->pixels, gpu->pitch) == 0, "Cannot read effect target");
#else
        SDL_Surface *gpu = gpScreenReal;
#endif
        Require(SDL_SaveBMP(gpu, (directory + "/" + current + "-" +
            std::to_string(frame) + "-640.bmp").c_str()) == 0, "Cannot save effect target");
#if SDL_VERSION_ATLEAST(2,0,0)
        SDL_FreeSurface(gpu);
#endif
    }
    ++frame; ++sequence;
}

void Start(const char *name, int backup = 0) {
    current = name; frame = 0; backupFrames = backup;
    g_bRenderPaused = FALSE;
}
void Stop() { current.clear(); g_bRenderPaused = TRUE; }

void Reset(bool night = true, WORD face = 55, bool lower = false) {
    Stop();
    gpGlobals->wNumPalette = 0; gpGlobals->fNightPalette = night;
    gpGlobals->wScreenWave = 0; gpGlobals->sWaveProgression = 0;
    PAL_SetPalette(0, night);
#if !SDL_VERSION_ATLEAST(2,0,0)
    // SDL1 copies palette values; unlike SDL2 these fixture surfaces do not
    // share gpPalette. Keep their indices unchanged when restoring the scene.
    VIDEO_UpdateSurfacePalette(baseScene);
    VIDEO_UpdateSurfacePalette(initial);
#endif
    VIDEO_CopyEntireSurface(baseScene, gpScreen);
    PAL_ClearDialog(FALSE);
    if (face) PAL_StartDialog(lower ? kDialogLower : kDialogUpper, 0, face, FALSE);
    // Real translated text and font, outside both portrait rectangles.
    if (!lower) {
        g_TextLib.fUserSkip = TRUE;
        for (int i = 0; i < 2; ++i) {
            // The reviewed Win/DOS correspondence is in dos-map.json.
            const int msg = PAL_GetMsgNum(gConfig.fIsWIN95 ? 1317 : 1898, 2, i);
            Require(msg > 0, "Missing effect dialogue text");
            PAL_ShowDialogText(PAL_GetMsg(msg));
        }
    }
}

void Run(const std::string& output) {
    directory = output;
    metadata = fopen((directory + "/effects.csv").c_str(), "w");
    frames = fopen((directory + "/effects.bin").c_str(), "wb");
    Require(metadata && frames, "Cannot open effect evidence files");
    fprintf(metadata, "effect,frame,sequence\n");
    PrepareInn();
    baseScene = VIDEO_CreateCompatibleSurface(gpScreen);
    initial = VIDEO_CreateCompatibleSurface(gpScreen);
    VIDEO_CopyEntireSurface(gpScreen, baseScene);
    // Cover all 256 indices without replacing the actual inn/dialogue view.
    for (int y = 192; y < 200; ++y)
        for (int x = 0; x < 320; ++x)
            ((BYTE *)baseScene->pixels)[y * baseScene->pitch + x] = x & 255;
#if SDL_VERSION_ATLEAST(2,0,0)
    SDL_Texture *oldTexture = gpTexture, *oldTarget = SDL_GetRenderTarget(gpRenderer);
    SDL_Texture *target = nullptr;
    // GLSL owns its multipass targets. Observe its actual window backbuffer.
    if (!gConfig.fEnableGLSL) {
        target = SDL_CreateTexture(gpRenderer, SDL_PIXELFORMAT_ARGB8888,
            SDL_TEXTUREACCESS_TARGET, 640, 400);
        Require(target && SDL_SetRenderTarget(gpRenderer, target) == 0, "Cannot create effect target");
        gpTexture = nullptr; VIDEO_Resize(640, 400);
    }
#endif
    VIDEO_TestFrameHook = Capture;

    Reset(); Start("initial"); VIDEO_UpdateScreen(nullptr); Stop();
    Start("color-to"); PAL_ColorFade(0, 0x7f, FALSE); Stop();
    Start("color-from"); PAL_ColorFade(0, 0x7f, TRUE); Stop();
    Reset(); Start("red"); PAL_FadeToRed(); Stop();
    Start("red-to-black"); PAL_FadeOut(1); Stop();
    Start("black-to-palette5"); PAL_FadeIn(5, FALSE, 1); Stop();
    Reset(); Start("night-to-day"); PAL_PaletteFade(0, FALSE, FALSE); Stop();
    gpGlobals->fNightPalette = FALSE;
    Start("day-to-night"); PAL_PaletteFade(0, TRUE, FALSE); Stop();
    Reset(); g_bRenderPaused = TRUE; PAL_FadeToRed();
    Start("red-to-night"); PAL_PaletteFade(0, TRUE, FALSE); Stop();

    Reset(); VIDEO_CopyEntireSurface(gpScreen, initial);
    Start("wave");
    gpGlobals->wScreenWave = 64;
    for (int i = 0; i < 32; ++i) {
        VIDEO_CopyEntireSurface(initial, gpScreen);
        PAL_ApplyWave(gpScreen); VIDEO_UpdateScreen(nullptr);
    }
    Stop(); gpGlobals->wScreenWave = 0;

    Reset(); Start("shake");
    VIDEO_ShakeScreen(2, 3);
    VIDEO_UpdateScreen(nullptr); VIDEO_UpdateScreen(nullptr);
    Stop();

    for (int effect = 0; effect < 3; ++effect) {
        Reset(); VIDEO_BackupScreen(gpScreen);
        Reset(true, 70, true);
        Start(effect == 0 ? "switch" : effect == 1 ? "dissolve" : "dissolve-shake",
            effect == 0 ? 6 : 72);
        if (effect == 0) VIDEO_SwitchScreen(0);
        else {
            if (effect == 2) VIDEO_ShakeScreen(72, 3);
            VIDEO_FadeScreen(0);
        }
        Stop();
    }
    Reset(true, 70, true); Start("target"); VIDEO_UpdateScreen(nullptr); Stop();
    Reset(); Start("fbp"); PAL_ShowFBP(1, 1); Stop();

    Reset(); VIDEO_BackupScreen(gpScreen);
    Reset(true, 70, true);
    memset(&g_Battle, 0, sizeof(g_Battle));
    g_Battle.lpSceneBuf = VIDEO_CreateCompatibleSurface(gpScreen);
    VIDEO_CopyEntireSurface(gpScreen, g_Battle.lpSceneBuf);
    g_Battle.fEnemyCleared = TRUE;
    g_Battle.UI.state = kBattleUIWait;
    PAL_ClearKeyState();
    Start("battle"); PAL_BattleFadeScene(); Stop();
    VIDEO_FreeSurface(g_Battle.lpSceneBuf); g_Battle.lpSceneBuf = nullptr;

    // Full scene redraw must remove the portrait throughout scene fades.
    Reset(); Start("scene-out"); PAL_SceneFade(0, TRUE, -32); Stop();
    Start("scene-in"); PAL_SceneFade(0, TRUE, 32); Stop();
    VIDEO_TestFrameHook = nullptr;
    Require(fclose(frames) == 0 && fclose(metadata) == 0, "Cannot close effect evidence");
#if SDL_VERSION_ATLEAST(2,0,0)
    if (!gConfig.fEnableGLSL) {
        SDL_DestroyTexture(gpTexture); gpTexture = oldTexture;
        SDL_SetRenderTarget(gpRenderer, oldTarget); SDL_DestroyTexture(target);
    }
#endif
    VIDEO_FreeSurface(initial); VIDEO_FreeSurface(baseScene); PAL_FreeResources();
    printf("Effect frames: %d; hidden source renderer, no gameplay/input\n", sequence);
}
}
void DrawPortraitEffects(const std::string& directory) { portrait_effects::Run(directory); }
