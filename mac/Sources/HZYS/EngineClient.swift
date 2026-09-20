import AppKit
import Combine
import Foundation

/// 和 hzys 引擎（`python main.py --engine`）对话的客户端。
///
/// 协议：每行一个 JSON。引擎发事件（output / state / info …），
/// 也会反过来请求界面做事（弹保存框之类），我们用同样的 id 回过去。
@MainActor
final class EngineClient: ObservableObject {
    @Published var title = "电棍棍活字"
    @Published var version = ""
    @Published var log = ""
    @Published var input = ""
    @Published var page = "local"
    @Published var running = false
    @Published var busy = false
    @Published var dirty = false
    @Published var values: [String: Any] = [:]
    @Published var paths: [String: String] = [:]
    @Published var entries: [String: String] = [:]
    @Published var pageTitles: [(id: String, title: String)] = []
    @Published var pages: [PageInfo] = []
    @Published var buttons: [String: String] = [:]
    @Published var outputTitle = "弹幕输出"
    @Published var placeholder = ""
    @Published var dictionaries: [DictionaryInfo] = []
    @Published var connected = false
    @Published var alert: AlertInfo?
    // 子界面
    @Published var dictionarySheet: DictionaryInfo?
    @Published var aboutSheet: AboutInfo?
    @Published var loginSheet = false
    @Published var loginImage: Data?
    @Published var loginStatus = ""

    struct AboutInfo: Identifiable {
        let id = UUID()
        let title: String
        let text: String
    }

    struct AlertInfo: Identifiable {
        let id = UUID()
        let title: String
        let text: String
        let warning: Bool
    }

    private var process: Process?
    private var engineLaunch: EngineLaunch?
    private var stdinHandle: FileHandle?
    private var nextId = 1
    private var pending: [Int: (Any?) -> Void] = [:]
    private let logLimit = 400
    private var testRunner: UITestRunner?

    // ---------------- 启动 / 退出 ----------------

    func start() {
        guard process == nil else { return }
        guard let launch = Self.locateEngine() else {
            alert = AlertInfo(
                title: "找不到引擎",
                text: "没找到引擎。打包运行时它是同一个 .app 里的主程序；"
                    + "源码运行时需要项目里的 .venv，"
                    + "也可以用环境变量 HZYS_PYTHON 指定解释器。",
                warning: true
            )
            return
        }
        engineLaunch = launch

        let task = Process()
        task.executableURL = URL(fileURLWithPath: launch.executable)
        task.arguments = launch.arguments
        task.environment = Self.cleanEnvironment()
        if let root = launch.projectRoot {
            task.currentDirectoryURL = URL(fileURLWithPath: root)
        }

        let input = Pipe()
        let output = Pipe()
        let errors = Pipe()
        task.standardInput = input
        task.standardOutput = output
        task.standardError = errors
        stdinHandle = input.fileHandleForWriting

        output.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty else { return }
            for line in String(decoding: data, as: UTF8.self).split(separator: "\n") {
                // 只把 String 丢进主线程（它是 Sendable 的），JSON 解析在主线程做
                let text = String(line)
                Task { @MainActor in self.handleLine(text) }
            }
        }
        errors.fileHandleForReading.readabilityHandler = { handle in
            let data = handle.availableData
            guard !data.isEmpty, let text = String(data: data, encoding: .utf8)
            else { return }
            // 引擎的调试日志（stderr）只打到终端，不进界面
            FileHandle.standardError.write(text.data(using: .utf8) ?? Data())
        }
        task.terminationHandler = { _ in
            Task { @MainActor in
                self.connected = false
                self.process = nil
                self.stdinHandle = nil
            }
        }

        do {
            try task.run()
            process = task
            connected = true
            // 自测模式：界面自己按步骤触发一遍（见 UITest.swift）
            if UITestRunner.isEnabled, testRunner == nil {
                let runner = UITestRunner(engine: self)
                testRunner = runner
                runner.start()
            }
        } catch {
            alert = AlertInfo(
                title: "启动引擎失败", text: error.localizedDescription, warning: true
            )
        }
    }

    func stop() {
        send(["type": "quit"])
        process?.terminate()
        process = nil
        stdinHandle = nil
        connected = false
    }

    /// 换回经典界面（tk）：把当前进程整个换成同一个 .app 里的主程序。
    ///
    /// 用 execv 而不是"再开一个程序"：进程号不变、Dock 上还是这个 app，
    /// 也不会有一小段时间两个界面同时开着（那样会抢音频设备和 settings.json）。
    func switchToClassicUi() {
        guard let launch = engineLaunch ?? Self.locateEngine() else {
            alert = AlertInfo(
                title: "切换界面失败", text: "找不到经典界面的入口。", warning: true
            )
            return
        }

        // 先把引擎停掉：换过去之后新进程会自己起一份
        send(["type": "quit"])
        process?.terminate()
        process = nil
        stdinHandle = nil
        connected = false

        var arguments = [launch.executable]
        if let root = launch.projectRoot {
            // 源码运行：同一个解释器再跑一次 main.py，只是不带 --engine
            arguments.append("main.py")
            FileManager.default.changeCurrentDirectoryPath(root)
        }
        // execv 成功就不返回了；返回说明没换成，把引擎重新拉起来
        var argv = arguments.map { strdup($0) }
        argv.append(nil)
        execv(launch.executable, &argv)
        alert = AlertInfo(
            title: "切换界面失败", text: "没能启动经典界面。", warning: true
        )
        start()
    }

    /// 引擎怎么起：可执行文件 + 参数 + 工作目录。
    ///
    /// 打包在一起时（一个 .app 里两套界面）引擎就是 bundle 里那个主程序，
    /// 加个 --engine 就从"经典界面"变成"只发协议、不开窗口"的引擎；
    /// 源码运行时才是 .venv/bin/python + main.py。
    struct EngineLaunch {
        let executable: String
        let arguments: [String]
        let projectRoot: String?
    }

    /// 找引擎（打包就找同 bundle 的主程序，源码运行就找 .venv）。
    private static func locateEngine() -> EngineLaunch? {
        let manager = FileManager.default

        // 打包在一起：bundle 的主程序就在自己旁边（Contents/MacOS/）
        if let bundled = bundledMainExecutable() {
            return EngineLaunch(
                executable: bundled, arguments: ["--engine"], projectRoot: nil
            )
        }

        // 可执行文件在 HZYS.app/Contents/MacOS/HZYS（或 .build/release/HZYS）
        var root = URL(fileURLWithPath: CommandLine.arguments[0])
            .resolvingSymlinksInPath()
        for _ in 0..<8 {
            root.deleteLastPathComponent()
            if manager.fileExists(atPath: root.appendingPathComponent("main.py").path) {
                break
            }
        }
        let projectRoot = root.path
        let python: String
        if let override = ProcessInfo.processInfo.environment["HZYS_PYTHON"],
           manager.isExecutableFile(atPath: override) {
            python = override
        } else {
            python = firstExistingPython(in: projectRoot) ?? ""
        }
        guard !python.isEmpty else { return nil }
        return EngineLaunch(
            executable: python,
            arguments: ["main.py", "--engine"],
            projectRoot: projectRoot
        )
    }

    /// bundle 里那个主程序（它同时也是经典界面）。
    private static func bundledMainExecutable() -> String? {
        guard let executable = Bundle.main.executableURL,
              let name = Bundle.main.object(
                  forInfoDictionaryKey: "CFBundleExecutable"
              ) as? String
        else { return nil }
        let candidate = executable.deletingLastPathComponent()
            .appendingPathComponent(name)
        guard candidate.path != executable.path,
              FileManager.default.isExecutableFile(atPath: candidate.path)
        else { return nil }
        return candidate.path
    }

    private static func firstExistingPython(in projectRoot: String) -> String? {
        let manager = FileManager.default
        let venv = projectRoot + "/.venv/bin/python"
        if manager.isExecutableFile(atPath: venv) { return venv }
        for candidate in ["/usr/local/bin/python3", "/opt/homebrew/bin/python3",
                          "/usr/bin/python3"] {
            if manager.isExecutableFile(atPath: candidate) { return candidate }
        }
        return nil
    }

    /// 起引擎时把 PyInstaller 留下的环境变量摘掉。
    ///
    /// 打包后的引擎也是 PyInstaller 程序，带着上一个进程的 `_PYI_*` 会以为
    /// 自己是"已经解过包的子进程"，跑起来会缺模块或者画不出界面。
    private static func cleanEnvironment() -> [String: String] {
        ProcessInfo.processInfo.environment.filter { key, _ in
            !key.hasPrefix("_PYI_") && key != "_MEIPASS2"
        }
    }

    // ---------------- 发送 ----------------

    private func send(_ payload: [String: Any]) {
        guard let handle = stdinHandle,
              let data = try? JSONSerialization.data(withJSONObject: payload)
        else { return }
        var line = data
        line.append(0x0A)
        try? handle.write(contentsOf: line)
    }

    func call(_ method: String, _ args: [Any] = []) {
        send(["type": "call", "id": nextId, "method": method, "args": args])
        nextId += 1
    }

    /// 需要引擎回答的调用（暂时只有超时兜底，返回值用不到就忽略）。
    private func ask(_ method: String, _ args: [Any], done: @escaping (Any?) -> Void) {
        let id = nextId
        nextId += 1
        pending[id] = done
        send(["type": "call", "id": id, "method": method, "args": args])
    }

    // ---------------- 收到 ----------------

    private func handleLine(_ line: String) {
        guard let data = line.data(using: .utf8),
              let message = try? JSONSerialization.jsonObject(with: data)
                as? [String: Any]
        else { return }
        handle(message)
    }

    private func handle(_ message: [String: Any]) {
        switch message["type"] as? String {
        case "event":
            handleEvent(name: message["name"] as? String ?? "", message)
        case "call":
            handleCall(message)
        case "return", "error":
            let id = message["id"] as? Int ?? -1
            pending.removeValue(forKey: id)?(message["result"])
        default:
            break
        }
    }

    private func handleEvent(name: String, _ message: [String: Any]) {
        switch name {
        case "ready":
            title = message["title"] as? String ?? title
            version = message["version"] as? String ?? ""
            if let layout = message["layout"] as? [String: Any] {
                applyLayout(layout)
            }
            applyState(message["state"] as? [String: Any])
            // 调试用：HZYS_START_PAGE=live|settings 可以直接打开某一页（方便截图/对比）
            if let startPage = ProcessInfo.processInfo.environment["HZYS_START_PAGE"],
               !startPage.isEmpty {
                call("selectPage", [startPage])
            }
        case "state":
            applyState(message["state"] as? [String: Any])
        case "output":
            append(message["text"] as? String ?? "")
        case "value":
            if let name = message["var"] as? String, let value = message["value"] {
                values[name] = value
            }
        case "dirty":
            dirty = message["dirty"] as? Bool ?? false
        case "info":
            alert = AlertInfo(
                title: message["title"] as? String ?? "",
                text: message["text"] as? String ?? "",
                warning: false
            )
        case "warning":
            alert = AlertInfo(
                title: message["title"] as? String ?? "",
                text: message["text"] as? String ?? "",
                warning: true
            )
        case "switchUi":
            // 引擎请我们换界面（用户在原生界面里关掉了「新版效果」）
            if message["target"] as? String == "classic" {
                switchToClassicUi()
            }
        case "login":
            loginStatus = message["status"] as? String ?? ""
            if let image = message["image"] as? String,
               let comma = image.firstIndex(of: ",") {
                loginImage = Data(
                    base64Encoded: String(image[image.index(after: comma)...])
                )
            }
            loginSheet = true
        default:
            break
        }
    }

    private func applyState(_ state: [String: Any]?) {
        guard let state else { return }
        page = state["page"] as? String ?? page
        running = state["running"] as? Bool ?? running
        busy = state["busy"] as? Bool ?? busy
        dirty = state["dirty"] as? Bool ?? dirty
        if let values = state["values"] as? [String: Any] { self.values = values }
        if let paths = state["paths"] as? [String: String] { self.paths = paths }
        if let entries = state["entries"] as? [String: String] { self.entries = entries }
        applyWindowOptions()
    }

    /// 解析引擎发来的结构（和网页界面用的是同一份 layout.buildPages()）。
    private func applyLayout(_ layout: [String: Any]) {
        if let data = try? JSONSerialization.data(withJSONObject: layout) {
            let decoder = JSONDecoder()
            if let decoded = try? decoder.decode(LayoutPayload.self, from: data) {
                pages = decoded.pages
                buttons = decoded.buttons
                outputTitle = decoded.outputTitle
                placeholder = decoded.placeholder
                dictionaries = decoded.dictionaries
                pageTitles = decoded.pages.map { (id: $0.id, title: $0.title) }
            }
        }
    }

    private struct LayoutPayload: Codable {
        let pages: [PageInfo]
        let buttons: [String: String]
        let outputTitle: String
        let placeholder: String
        let dictionaries: [DictionaryInfo]
    }

    /// 置顶弹幕输出：勾上就让窗口浮在最上层（和网页后端一个意思）。
    private func applyWindowOptions() {
        let onTop = (values["istipWindowon"] as? Bool) ?? false
        for window in NSApp.windows {
            window.level = onTop ? .floating : .normal
        }
    }

    // ---------------- 子界面（关于 / 词典 / 更新）----------------

    func showAbout() {
        ask("getAbout", []) { result in
            guard let info = result as? [String: Any] else { return }
            self.aboutSheet = AboutInfo(
                title: info["title"] as? String ?? "关于",
                text: info["text"] as? String ?? ""
            )
        }
    }

    func checkUpdate() { call("checkUpdate") }
    func openAuthor() { call("openAuthor") }
    func openReleases() { call("openReleases") }

    func openDictionary(_ mode: Int) {
        dictionarySheet = dictionaries.first { $0.mode == mode }
    }

    func loadDictionary(_ mode: Int, done: @escaping ([[String]]) -> Void) {
        ask("getDictionary", [mode]) { result in
            guard let info = result as? [String: Any],
                  let rows = info["rows"] as? [[Any]]
            else {
                done([])
                return
            }
            done(rows.map { row in
                let name = row.first as? String ?? ""
                let value = row.count > 1 ? (row[1] as? String ?? "") : ""
                return [name, value]
            })
        }
    }

    func saveDictionary(mode: Int, rows: [[String]]) {
        ask("saveDictionary", [mode, rows]) { result in
            if let info = result as? [String: Any], (info["ok"] as? Bool) == true {
                self.dictionarySheet = nil
            }
        }
    }

    private func append(_ text: String) {
        log += text
        let lines = log.split(separator: "\n", omittingEmptySubsequences: false)
        if lines.count > logLimit {
            log = lines.suffix(logLimit).joined(separator: "\n")
        }
    }

    // ---------------- 引擎反过来请求界面 ----------------

    private func handleCall(_ message: [String: Any]) {
        let id = message["id"] as? Int ?? -1
        let method = message["method"] as? String ?? ""
        let args = message["args"] as? [Any] ?? []

        func reply(_ result: Any?) {
            send(["type": "return", "id": id, "result": result ?? NSNull()])
        }

        switch method {
        case "askSaveFileName":
            let title = args.first as? String ?? "保存"
            let defaultName = args.count > 1 ? (args[1] as? String ?? "") : ""
            // 自测模式：不弹框，直接回答一个固定路径
            if let auto = ProcessInfo.processInfo.environment["HZYS_AUTOSAVE"] {
                reply(auto.isEmpty ? defaultName : auto)
                return
            }
            let panel = NSSavePanel()
            panel.title = title
            panel.nameFieldStringValue = defaultName
            panel.canCreateDirectories = true
            reply(panel.runModal() == .OK ? panel.url?.path : "")
        case "askYesNo":
            if ProcessInfo.processInfo.environment["HZYS_AUTOYES"] != nil {
                reply(true)
                return
            }
            let box = NSAlert()
            box.messageText = args.first as? String ?? ""
            box.informativeText = args.count > 1 ? (args[1] as? String ?? "") : ""
            box.addButton(withTitle: "好")
            box.addButton(withTitle: "取消")
            reply(box.runModal() == .alertFirstButtonReturn)
        case "pickFolder", "pickFile":
            let panel = NSOpenPanel()
            panel.canChooseDirectories = (method == "pickFolder")
            panel.canChooseFiles = (method == "pickFile")
            panel.allowsMultipleSelection = false
            reply(panel.runModal() == .OK ? panel.url?.path : "")
        default:
            reply(nil)
        }
    }
}
