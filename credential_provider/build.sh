#!/bin/sh
# Builds the credential provider DLL, a test variant and the test harness with MinGW-w64 (WinLibs).
# Usage: sh credential_provider/build.sh [--test]
set -e
cd "$(dirname "$0")"
if ! command -v g++ >/dev/null 2>&1; then
    PATH="$(ls -d "$LOCALAPPDATA"/Microsoft/WinGet/Packages/BrechtSanders.WinLibs*/mingw64/bin 2>/dev/null | head -1):$PATH"
fi
FLAGS="-std=c++17 -O2 -Wall -Wextra -fno-exceptions -static -static-libgcc -static-libstdc++ -DUNICODE -D_UNICODE"
LIBS="-lole32 -luuid -lsecur32 -ladvapi32 -lshlwapi -lgdi32"
mkdir -p build
g++ $FLAGS -shared -o build/VisionAuthCredentialProvider.dll VisionAuthCredentialProvider.cpp VisionAuthCredentialProvider.def $LIBS
echo "built build/VisionAuthCredentialProvider.dll"
if [ "$1" = "--test" ]; then
    g++ $FLAGS -shared -DVISIONAUTH_ALLOW_ANY_PIPE_SERVER -o build/VisionAuthCredentialProvider_test.dll VisionAuthCredentialProvider.cpp VisionAuthCredentialProvider.def $LIBS
    g++ $FLAGS -municode -o build/test_harness.exe test_harness.cpp $LIBS
    ./build/test_harness.exe build/VisionAuthCredentialProvider_test.dll 1
    ./build/test_harness.exe build/VisionAuthCredentialProvider.dll 0
fi
