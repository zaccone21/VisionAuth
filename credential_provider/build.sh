#!/bin/sh
# Builds the credential provider DLL, a test variant and the test harness with MinGW-w64 (WinLibs).
# Usage: sh credential_provider/build.sh [--test]
set -e
cd "$(dirname "$0")"
if ! command -v g++ >/dev/null 2>&1; then
    PATH="$(ls -d "$LOCALAPPDATA"/Microsoft/WinGet/Packages/BrechtSanders.WinLibs*/mingw64/bin 2>/dev/null | head -1):$PATH"
fi
FLAGS="-std=c++17 -O2 -Wall -Wextra -fno-exceptions -static -static-libgcc -static-libstdc++ -DUNICODE -D_UNICODE"
LIBS="-lole32 -luuid -lsecur32 -ladvapi32 -lshlwapi -lgdi32 -lgdiplus"
mkdir -p build
g++ $FLAGS -shared -o build/VisionAuthCredentialProvider.dll VisionAuthCredentialProvider.cpp island.cpp VisionAuthCredentialProvider.def $LIBS
g++ $FLAGS -municode -o build/island_preview.exe island_preview.cpp island.cpp $LIBS
echo "built build/VisionAuthCredentialProvider.dll and build/island_preview.exe"
if [ "$1" = "--test" ]; then
    # Test variants use their own pipe name, so they never reach an installed service
    T="-DVISIONAUTH_TEST_PIPE"
    g++ $FLAGS -shared $T -DVISIONAUTH_ALLOW_ANY_PIPE_SERVER -o build/VisionAuthCredentialProvider_test.dll VisionAuthCredentialProvider.cpp island.cpp VisionAuthCredentialProvider.def $LIBS
    g++ $FLAGS -shared $T -o build/VisionAuthCredentialProvider_sidcheck.dll VisionAuthCredentialProvider.cpp island.cpp VisionAuthCredentialProvider.def $LIBS
    g++ $FLAGS $T -municode -o build/test_harness.exe test_harness.cpp island.cpp $LIBS
    # Any pipe server: the tile follows the service and logs on
    ./build/test_harness.exe build/VisionAuthCredentialProvider_test.dll 1
    # Real SYSTEM check: a server run by a normal user is ignored
    ./build/test_harness.exe build/VisionAuthCredentialProvider_sidcheck.dll 0
fi
