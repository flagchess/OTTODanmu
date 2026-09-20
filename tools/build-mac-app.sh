#!/usr/bin/env bash
# 把程序打成 macOS 的 .app（一个 app 里两套界面）。
#
#   bash tools/build-mac-app.sh
#
# 按"方案 A"打包：音频素材打进 .app 里（只读），配置和词典放用户目录
# （~/Library/Application Support/电棍棍活字/），首次运行自动铺一份出厂词典。
# 用户还是可以在设置页里把素材改成外部目录。
#
# 两套界面装在同一个 bundle 里：
#     Contents/MacOS/电棍棍活字   经典界面（tk），同时也是 --engine 引擎
#     Contents/MacOS/hzys-native  原生界面（SwiftUI）
# 用哪套由 settings.json 的 newUi 决定，设置页里能互相切——切换是 execv
# 换进程，App 身份、Dock 图标都不变（见 hzys/gui/nativeapp.py）。
# 因为不经过网页，这里不装 pywebview：网页界面只在 Windows 上用。
#
# 产物：release/mac-<架构>/<版本>-mac-<架构>.app，例如 2026.9.20-mac-arm64.app
# 名字里不带时间戳：同一个版本重编就是覆盖，目录里不会越攒越多；
# 同目录下别的 *-mac-*.app（以前版本编的）会被顺手删掉。
# 架构取自实际执行打包的 Python（用 x86_64 的 Python 跑就会落到 mac-x86_64）。

set -e

cd "$(dirname "$0")/.."

PYTHON="${PYTHON:-.venv/bin/python}"
if [ ! -x "$PYTHON" ]; then
    PYTHON="python3"
fi

if ! "$PYTHON" -c "import PyInstaller" >/dev/null 2>&1; then
    echo "[打包] 先装 PyInstaller…"
    "$PYTHON" -m pip install pyinstaller
fi

ARCH="$("$PYTHON" -c 'import platform; print(platform.machine())')"
OUT_DIR="release/mac-$ARCH"
mkdir -p "$OUT_DIR" "build/$ARCH"

# 素材和图标用绝对路径：spec 文件生成在 build/ 下，相对路径会按 spec 所在的目录算
ROOT="$PWD"

echo "[打包] 编译原生界面（SwiftUI）…"
if ! command -v swift >/dev/null 2>&1; then
    echo "[打包] 找不到 swift 命令，请先装 Xcode（xcode-select --install 不够，要完整 Xcode）"
    exit 1
fi
(cd mac && swift build -c release)

echo "[打包] 开始（第一次会慢一点）：$ARCH"
"$PYTHON" -m PyInstaller \
    --noconfirm --clean \
    --windowed --onedir \
    --distpath "$OUT_DIR" \
    --workpath "build/$ARCH" \
    --specpath "build/$ARCH" \
    --name "电棍棍活字" \
    --icon "$ROOT/assets/lizi.ico" \
    --add-data "$ROOT/assets:assets" \
    --add-data "$ROOT/data/dictionary.json:defaults" \
    --add-data "$ROOT/data/ysddTable.json:defaults" \
    --add-data "$ROOT/data/keyword.json:defaults" \
    --exclude-module webview \
    --hidden-import PIL.IcoImagePlugin \
    "$ROOT/main.py"

VERSION="$("$PYTHON" -c 'from hzys import __version__; print(__version__)')"
APP="$OUT_DIR/电棍棍活字.app"          # 构建时还用这个名字，最后再改成带版本号的
TARGET="$OUT_DIR/$VERSION-mac-$ARCH.app"

# ---- 把原生界面塞进同一个 bundle ----
cp "mac/.build/release/HZYS" "$APP/Contents/MacOS/hzys-native"
chmod +x "$APP/Contents/MacOS/hzys-native"

# PyInstaller 生成的 Info.plist 里没有版本号和显示名，补上
PLIST="$APP/Contents/Info.plist"
/usr/libexec/PlistBuddy -c "Set :CFBundleIdentifier com.ottodanmu.hzys" "$PLIST" 2>/dev/null ||
    /usr/libexec/PlistBuddy -c "Add :CFBundleIdentifier string com.ottodanmu.hzys" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleShortVersionString $VERSION" "$PLIST" 2>/dev/null ||
    /usr/libexec/PlistBuddy -c "Add :CFBundleShortVersionString string $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleVersion $VERSION" "$PLIST" 2>/dev/null ||
    /usr/libexec/PlistBuddy -c "Add :CFBundleVersion string $VERSION" "$PLIST"
/usr/libexec/PlistBuddy -c "Set :CFBundleDisplayName 电棍棍活字" "$PLIST" 2>/dev/null ||
    /usr/libexec/PlistBuddy -c "Add :CFBundleDisplayName string 电棍棍活字" "$PLIST"

# 先签里面那个可执行文件，再签整个 app（嵌套的二进制不能是没签过的）
codesign --force --sign - "$APP/Contents/MacOS/hzys-native" >/dev/null
codesign --force --sign - "$APP" >/dev/null

# BUNDLE 已经把内容拷进 .app 了，这份 onedir 中间产物留着没用，清掉之后
# release/ 里就只剩成品（下次构建会重新生成）
rm -rf "$OUT_DIR/电棍棍活字"

# 改名成 <版本>-mac-<架构>.app：bundle 里记的是 CFBundleName，改名不影响
# 启动、签名和 App 身份（里面两个可执行文件的位置也都没动）
rm -rf "$TARGET"
mv "$APP" "$TARGET"

# 同一个目录里以前版本的 .app 顺手清掉（只认我们自己的命名）
for old in "$OUT_DIR"/*-mac-*.app; do
    [ -e "$old" ] || continue
    [ "$old" = "$TARGET" ] && continue
    echo "[打包] 清掉旧产物：$(basename "$old")"
    rm -rf "$old"
done

echo
echo "[打包] 完成：$TARGET"
echo "[打包] 里面两套界面：经典（tk）和原生（SwiftUI），设置页的「新版效果」互相切"
echo "[打包] 配置和词典会写到 ~/Library/Application Support/电棍棍活字/"
echo "[打包] 想便携（配置放 .app 旁边）：在旁边放个 data/settings.json，"
echo "        或者设 HZYS_DATA_DIR 指定目录。"
