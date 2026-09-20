import AppKit
import Foundation

// 界面自测驱动：按 HZYS_UITEST 里的步骤，走和按钮完全相同的调用路径，
// 把每一步的结果写进 HZYS_UITEST_OUT 指定的文件。
//
// 这台机器不给辅助功能权限，模拟点击会被系统拦掉，所以"替用户点按钮"
// 没法用外部脚本做；改成让界面自己按同样的路子触发一遍，就能验证
// 「控件 -> 引擎 -> 回应」整条链路，也方便把各个界面截图下来。
//
// 步骤写法（逗号分隔）：
//     page:settings                  切页
//     input:大家好啊                 填输入框
//     toggle:isgifton                拨开关（自动取反）
//     slider:pitchMultOption:1.5     拖滑块
//     entry:numOfThreads:3           改输入框
//     dict:1                         打开词典面板
//     about                          打开关于面板
//     login                          走一次扫码登录
//     export                         点导出（自测模式下保存框自动回答）
//     dump                           拉一次引擎状态并记下来

@MainActor
final class UITestRunner {
    private let engine: EngineClient
    private let steps: [String]
    private let outPath: String?
    private let hold: Bool
    private var report: [String] = []

    init(engine: EngineClient) {
        self.engine = engine
        let env = ProcessInfo.processInfo.environment
        steps = (env["HZYS_UITEST"] ?? "")
            .split(separator: ",")
            .map { $0.trimmingCharacters(in: .whitespaces) }
            .filter { !$0.isEmpty }
        outPath = env["HZYS_UITEST_OUT"]
        hold = env["HZYS_UITEST_HOLD"] != nil
    }

    static var isEnabled: Bool {
        let value = ProcessInfo.processInfo.environment["HZYS_UITEST"] ?? ""
        return !value.isEmpty
    }

    func start() {
        Task { await run() }
    }

    private func run() async {
        record("engine connected: \(engine.connected)")
        // 等结构和初始状态都到齐（pages 和 values 是分两步填的）
        for _ in 0..<40 where engine.pages.isEmpty || engine.values.isEmpty {
            try? await Task.sleep(nanoseconds: 250_000_000)
        }
        record("pages: \(engine.pages.map { $0.id }.joined(separator: ","))")

        for step in steps {
            await execute(step)
            try? await Task.sleep(nanoseconds: 1_000_000_000)
        }
        await dump("final")
        write()
        if !hold {
            engine.stop()
            NSApp.terminate(nil)
        }
    }

    private func execute(_ step: String) async {
        let parts = step.split(separator: ":").map(String.init)
        guard let verb = parts.first else { return }
        switch verb {
        case "page" where parts.count > 1:
            engine.call("selectPage", [parts[1]])
            try? await Task.sleep(nanoseconds: 700_000_000)
            record("page -> \(parts[1])，引擎回报 page=\(engine.page)")
        case "input" where parts.count > 1:
            engine.input = parts[1]
            engine.call("inputChanged", [parts[1]])
            try? await Task.sleep(nanoseconds: 300_000_000)
            await dump("input 之后")
        case "toggle" where parts.count > 1:
            let name = parts[1]
            let next = !((engine.values[name] as? Bool) ?? false)
            engine.call("setValue", [name, next])
            try? await Task.sleep(nanoseconds: 500_000_000)
            await dump("toggle \(name) -> \(next)")
        case "slider" where parts.count > 2:
            let name = parts[1]
            let value = Double(parts[2]) ?? 1.0
            engine.call("setValue", [name, value])
            try? await Task.sleep(nanoseconds: 500_000_000)
            await dump("slider \(name) -> \(value)")
        case "entry" where parts.count > 2:
            engine.call("setEditorValue", [parts[1], parts[2]])
            try? await Task.sleep(nanoseconds: 500_000_000)
            await dump("entry \(parts[1]) -> \(parts[2])")
        case "dict" where parts.count > 1:
            engine.openDictionary(Int(parts[1]) ?? 1)
            try? await Task.sleep(nanoseconds: 700_000_000)
            record("dict sheet: \(engine.dictionarySheet?.title ?? "nil")")
        case "about":
            engine.showAbout()
            try? await Task.sleep(nanoseconds: 1_200_000_000)
            record("about sheet: \(engine.aboutSheet?.title ?? "nil")")
        case "login":
            engine.call("action", ["relogin"])
            try? await Task.sleep(nanoseconds: 3_000_000_000)
            record("login sheet: \(engine.loginSheet)，状态: \(engine.loginStatus)")
        case "export":
            engine.call("action", ["export"])
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            record("export 提示: \(engine.alert?.title ?? "（无）")")
        case "checkUpdate":
            engine.checkUpdate()
            try? await Task.sleep(nanoseconds: 4_000_000_000)
            record("检查更新提示: \(engine.alert?.title ?? "（无）")")
        case "saveSettings":
            engine.call("action", ["saveSettings"])
            try? await Task.sleep(nanoseconds: 1_000_000_000)
            record("保存设置后 dirty=\(engine.dirty)")
        case "dump":
            await dump("dump")
        default:
            record("跳过不认识的步骤: \(step)")
        }
    }

    private func dump(_ label: String) async {
        engine.call("getState")
        try? await Task.sleep(nanoseconds: 400_000_000)
        let values = engine.values.map { "\($0.key)=\($0.value)" }
            .sorted().joined(separator: " ")
        let entries = engine.entries.map { "\($0.key)=\($0.value)" }
            .sorted().joined(separator: " ")
        record(
            "[\(label)] page=\(engine.page) dirty=\(engine.dirty) "
                + "input=\(engine.input.isEmpty ? "空" : engine.input)\n"
                + "        窗口层级: \(NSApp.windows.map { $0.level.rawValue }.max() ?? 0)"
                + "（3 = 浮在最上层）\n"
                + "        values: \(values)\n"
                + "        entries: \(entries)"
        )
    }

    private func record(_ line: String) {
        report.append(line)
        FileHandle.standardError.write(Data((line + "\n").utf8))
    }

    private func write() {
        guard let path = outPath else { return }
        let text = report.joined(separator: "\n") + "\n"
        try? text.write(toFile: path, atomically: true, encoding: .utf8)
    }
}
