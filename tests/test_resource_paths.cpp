#include <gtest/gtest.h>
#include <string>
#include <vector>
#include <cstdio>

extern "C" {
#include "main.h"
}

#ifdef _WIN32
#include "../win32/resource.h"
#include "../adplug/fprovide.h"

void SaveSettings(HWND window, BOOL writeFile);
void ResetControls(HWND window);

namespace {
std::string Encode(const std::wstring& value, UINT codepage = CP_UTF8) {
    int count = WideCharToMultiByte(codepage, 0, value.c_str(), -1, nullptr, 0, nullptr, nullptr);
    std::vector<char> result(count);
    if (count) WideCharToMultiByte(codepage, 0, value.c_str(), -1, result.data(), count, nullptr, nullptr);
    return count ? std::string(result.data()) : std::string();
}

class ResourcePaths : public testing::Test {
protected:
    std::wstring root, previous;
    std::vector<std::wstring> files, directories;

    void SetUp() override {
        wchar_t cwd[MAX_PATH], temp[MAX_PATH];
        ASSERT_TRUE(GetCurrentDirectoryW(MAX_PATH, cwd));
        previous = cwd;
        const wchar_t *parent = _wgetenv(L"SDLPAL_PATH_TEST_ROOT");
        if (!parent) {
            ASSERT_TRUE(GetTempPathW(MAX_PATH, temp));
            parent = temp;
        }
        static int serial = 0;
        root = std::wstring(parent) + L"/path-" + std::to_wstring(GetCurrentProcessId()) +
            L"-" + std::to_wstring(++serial);
        ASSERT_TRUE(CreateDirectoryW(root.c_str(), nullptr));
        ASSERT_TRUE(SetCurrentDirectoryW(root.c_str()));
        PAL_LoadConfig(FALSE);
    }

    void TearDown() override {
        PAL_FreeConfig();
        SetCurrentDirectoryW(previous.c_str());
        for (auto it = files.rbegin(); it != files.rend(); ++it) DeleteFileW(it->c_str());
        for (auto it = directories.rbegin(); it != directories.rend(); ++it) RemoveDirectoryW(it->c_str());
        RemoveDirectoryW(root.c_str());
    }

    std::wstring Directory(const std::wstring& name) {
        std::wstring path = root + L"/" + name;
        EXPECT_TRUE(CreateDirectoryW(path.c_str(), nullptr));
        directories.push_back(path);
        return path;
    }

    std::wstring File(const std::wstring& directory, const std::wstring& name, const char *text = "resource") {
        const auto path = directory + L"/" + name;
        files.push_back(path);
        FILE *file = _wfopen(path.c_str(), L"wb");
        EXPECT_NE(nullptr, file);
        if (file) { fwrite(text, 1, strlen(text), file); fclose(file); }
        return path;
    }

    void ExpectContents(FILE *file, const char *text = "resource") {
        ASSERT_NE(nullptr, file);
        char bytes[64] = {};
        size_t count = fread(bytes, 1, sizeof(bytes), file);
        fclose(file);
        EXPECT_EQ(std::string(text), std::string(bytes, count));
    }
};
}

TEST_F(ResourcePaths, Utf8GameDirectoryAndAbsoluteNames) {
    const auto directory = Directory(L"中文资源-仙剑98-\U0001f431");
    const auto file = File(directory, L"对白.dat");
    const auto path = Encode(directory), filename = Encode(file);
    free(gConfig.pszGamePath); gConfig.pszGamePath = strdup(path.c_str());
    ExpectContents(UTIL_OpenFile(u8"对白.dat"));
    ExpectContents(UTIL_OpenFile(filename.c_str()));
    ExpectContents(UTIL_OpenRequiredFile(filename.c_str()));
    ExpectContents(UTIL_OpenFileAtPath(path.c_str(), u8"对白.dat"));
    auto backslashes = path;
    for (char& c : backslashes) if (c == '/') c = '\\';
    ExpectContents(UTIL_OpenFileAtPath((backslashes + "\\").c_str(), u8"对白.dat"));
    EXPECT_EQ(nullptr, UTIL_OpenFile("missing.dat"));
    EXPECT_EQ(nullptr, UTIL_OpenFileAtPath(nullptr, "missing.dat"));
}

TEST_F(ResourcePaths, WriteAppendUpdateAndRequiredCwdFallback) {
    const auto directory = Directory(L"中文存档");
    const auto path = Encode(directory);
    files.push_back(directory + L"/1.rpg");
    FILE *file = UTIL_OpenFileAtPathForMode(path.c_str(), "1.rpg", "wb");
    ASSERT_NE(nullptr, file); fputs("save", file); fclose(file);
    file = UTIL_OpenFileAtPathForMode(path.c_str(), "1.rpg", "ab");
    ASSERT_NE(nullptr, file); fputs("!", file); fclose(file);
    file = UTIL_OpenFileAtPathForMode(path.c_str(), "1.rpg", "r+b");
    ASSERT_NE(nullptr, file); fputc('S', file); fclose(file);
    ExpectContents(UTIL_OpenFileAtPath(path.c_str(), "1.rpg"), "Save!");
    File(root, L"后备.dat", "fallback");
    free(gConfig.pszGamePath); gConfig.pszGamePath = strdup(path.c_str());
    ExpectContents(UTIL_OpenRequiredFile(u8"后备.dat"), "fallback");
}

TEST_F(ResourcePaths, LegacyAcpConfigAndUtf8ConfigPreserveBytes) {
    const auto directory = Directory(L"中文资源");
    File(directory, L"FBP.MKF");
    const auto utf8 = Encode(directory);
    const auto acp = Encode(directory, CP_ACP);
    const int count = MultiByteToWideChar(CP_ACP, 0, acp.c_str(), -1, nullptr, 0);
    std::vector<wchar_t> native(count);
    ASSERT_GT(count, 0);
    ASSERT_TRUE(MultiByteToWideChar(CP_ACP, 0, acp.c_str(), -1, native.data(), count));
    const bool acpRepresentable = directory == native.data();
    // Legacy fallback is meaningful only if this system's ACP represents the
    // fixture. UTF-8 is always tested, including on non-Chinese Windows hosts.
    for (int encoding = 0; encoding < 2; ++encoding) {
        if (encoding == 1 && !acpRepresentable) continue;
        const auto& path = encoding == 0 ? utf8 : acp;
        wchar_t *wide = UTIL_PathToWide(path.c_str());
        const bool exact = wide && directory == wide;
        free(wide);
        ASSERT_TRUE(exact);
        File(root, L"sdlpal.cfg", ("GamePath=" + path + "\n").c_str());
        PAL_FreeConfig(); PAL_LoadConfig(TRUE);
        EXPECT_EQ(path, gConfig.pszGamePath);
        ExpectContents(UTIL_OpenFile("fbp.mkf"));
        ASSERT_TRUE(PAL_SaveConfig());
        PAL_FreeConfig(); PAL_LoadConfig(TRUE);
        EXPECT_EQ(path, gConfig.pszGamePath);
        ExpectContents(UTIL_OpenFile("FBP.MKF"));
    }
}

TEST_F(ResourcePaths, Utf8ConfigOver512BytesAndAbsolutePrefix) {
    // Fits traditional Windows character limits but exceeds the old config
    // line and _splitpath_s byte buffers. This is not a long-path/UNC test.
    ASSERT_LT(root.size(), 244u);
    const size_t length = 244 - root.size();
    ASSERT_GT(length, 130u);
    const auto directory = Directory(std::wstring(length, L'中'));
    const auto path = Encode(directory);
    ASSERT_GT(path.size(), 512u);
    ASSERT_LT(directory.size(), size_t(MAX_PATH));
    const auto file = File(directory, L"a.dat");
    EXPECT_TRUE(UTIL_IsAbsolutePath(Encode(file).c_str()));
    EXPECT_FALSE(UTIL_IsAbsolutePath("C:relative.dat"));
    EXPECT_FALSE(UTIL_IsAbsolutePath(""));
    EXPECT_FALSE(UTIL_IsAbsolutePath(nullptr));
    free(gConfig.pszGamePath); gConfig.pszGamePath = strdup(path.c_str());
    free(gConfig.pszSavePath); gConfig.pszSavePath = strdup(path.c_str());
    free(gConfig.pszShaderPath); gConfig.pszShaderPath = nullptr;
    files.push_back(root + L"/sdlpal.cfg");
    ASSERT_TRUE(PAL_SaveConfig());
    PAL_FreeConfig(); PAL_LoadConfig(TRUE);
    EXPECT_EQ(path, gConfig.pszGamePath);
    EXPECT_EQ(path, gConfig.pszSavePath);
    ExpectContents(UTIL_OpenFile(Encode(file).c_str()));
    // Loading defaults ShaderPath to GamePath. Replacing only GamePath in the
    // settings must safely save the previous, long ShaderPath as well.
    EXPECT_EQ(path, gConfig.pszShaderPath);
    const auto replacement = Encode(root);
    free(gConfig.pszGamePath); gConfig.pszGamePath = strdup(replacement.c_str());
    ASSERT_TRUE(PAL_SaveConfig());
    PAL_FreeConfig(); PAL_LoadConfig(TRUE);
    EXPECT_EQ(replacement, gConfig.pszGamePath);
    EXPECT_EQ(path, gConfig.pszShaderPath);
    EXPECT_EQ(path, gConfig.pszSavePath);
}

TEST_F(ResourcePaths, NativeSettingsGamePathRoundtripWithoutVisibleWindow) {
    const auto directory = Directory(L"中文目录-\U0001f431");
    HWND parent = CreateWindowW(L"STATIC", L"test", 0, 0, 0, 1, 1, nullptr, nullptr, nullptr, nullptr);
    ASSERT_NE(nullptr, parent);
    HWND edit = CreateWindowW(L"EDIT", directory.c_str(), WS_CHILD, 0, 0, 1, 1, parent,
                               (HMENU)(INT_PTR)IDC_GAMEPATH, nullptr, nullptr);
    ASSERT_NE(nullptr, edit);
    SaveSettings(parent, FALSE);
    EXPECT_EQ(Encode(directory), gConfig.pszGamePath);
    SetWindowTextW(edit, L"");
    ResetControls(parent);
    wchar_t actual[MAX_PATH] = {};
    GetWindowTextW(edit, actual, MAX_PATH);
    EXPECT_EQ(directory, actual);
    DestroyWindow(parent);
}

TEST_F(ResourcePaths, RixProviderAndSdlReadIdenticalBytes) {
    const auto directory = Directory(L"中文音乐-\U0001f431");
    const auto filename = Encode(File(directory, L"MUS.MKF"));
    CProvider_Filesystem provider;
    binistream *stream = provider.open(filename);
    ASSERT_NE(nullptr, stream);
    std::string actual;
    for (int i = 0; i < 8; ++i) actual.push_back((char)stream->readInt(1));
    provider.close(stream);
    EXPECT_EQ("resource", actual);
    SDL_RWops *sdl = SDL_RWFromFile(filename.c_str(), "rb");
    ASSERT_NE(nullptr, sdl);
    char bytes[8];
    EXPECT_EQ(8u, SDL_RWread(sdl, bytes, 1, sizeof(bytes)));
    SDL_RWclose(sdl);
    EXPECT_EQ("resource", std::string(bytes, sizeof(bytes)));
}
#endif
