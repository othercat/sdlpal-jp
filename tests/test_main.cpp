
#include <gtest/gtest.h>
#include <cstring>

int RenderEvidence(int argc, char **argv);
int ConfigRoundtripEvidence(int argc, char **argv);

extern "C"
int testmain(int argc, char *argv[]) {
    if (argc > 1 && strcmp(argv[1], "--render-evidence") == 0)
        return RenderEvidence(argc, argv);
    if (argc > 1 && strcmp(argv[1], "--config-roundtrip-evidence") == 0)
        return ConfigRoundtripEvidence(argc, argv);
    testing::InitGoogleTest(&argc, argv);
    return RUN_ALL_TESTS();
}
