// swift-tools-version: 6.0
import PackageDescription

// macOS 原生界面（SwiftUI）。它不直接做业务，一切通过 hzys 引擎的
// JSON 行协议来：python main.py --engine
//
//   swift build -c release        # 只编译（源码运行经典界面时会找这个产物，
//                                 #  见 hzys/gui/nativeapp.py 的 DEV_BUILD）
//   bash tools/build-mac-app.sh   # 和经典界面一起打成同一个 .app
let package = Package(
    name: "HZYS",
    platforms: [.macOS("26.0")],
    targets: [
        .executableTarget(name: "HZYS", path: "Sources/HZYS")
    ]
)
