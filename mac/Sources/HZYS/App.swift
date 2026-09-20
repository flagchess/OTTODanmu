import SwiftUI

/// 收集三个选项各自的矩形（拖动玻璃药丸时要用它算位置）
struct TabFramesKey: PreferenceKey {
    static let defaultValue: [String: CGRect] = [:]

    static func reduce(value: inout [String: CGRect], nextValue: () -> [String: CGRect]) {
        value.merge(nextValue()) { _, new in new }
    }
}

/// 调试用：设了 HZYS_DEBUG 就把拖动事件写到 stderr
func debugLog(_ text: String) {
    guard ProcessInfo.processInfo.environment["HZYS_DEBUG"] != nil else { return }
    FileHandle.standardError.write(Data(("[drag] " + text + "\n").utf8))
}

@main
struct HZYSApp: App {
    @NSApplicationDelegateAdaptor(AppDelegate.self) private var delegate
    @StateObject private var engine = EngineClient()

    var body: some Scene {
        WindowGroup {
            ContentView(engine: engine)
                // 窗口标题用引擎给的标题：和经典界面是同一个字符串
                // （layout.WINDOW_TITLE = "电棍棍活字 ver.<版本>"）
                .navigationTitle(engine.title)
                .onAppear {
                    AppDelegate.onQuit = { engine.stop() }
                    engine.start()
                    // 从终端/脚本直接起可执行文件时窗口默认在后台，这里主动置顶
                    NSApp.activate(ignoringOtherApps: true)
                    DispatchQueue.main.asyncAfter(deadline: .now() + 0.6) {
                        NSApp.activate(ignoringOtherApps: true)
                    }
                }
        }
        .windowResizability(.contentMinSize)
        .defaultSize(width: 560, height: 880)  // 和网页版一致
        .commands {
            CommandGroup(replacing: .newItem) {}
        }
    }
}

/// 退出时把引擎进程一起收掉，别留下孤儿进程。
@MainActor
final class AppDelegate: NSObject, NSApplicationDelegate {
    static var onQuit: (() -> Void)?

    func applicationWillTerminate(_ notification: Notification) {
        AppDelegate.onQuit?()
    }

    func applicationDidFinishLaunching(_ notification: Notification) {
        NSApp.activate(ignoringOtherApps: true)
    }
}

struct ContentView: View {
    @ObservedObject var engine: EngineClient
    // 药丸当前的位置/宽度、三个选项各自的位置、拖动中的预览目标
    @State private var pillRect: CGRect?
    @State private var tabFrames: [String: CGRect] = [:]
    @State private var previewId: String?

    private var isLive: Bool { engine.page == "live" }
    /// 直播页勾了「隐藏日志」就不显示日志区（非直播页显示输入框，和网页版一致）
    private var hideLog: Bool { (engine.values["ishidemsgon"] as? Bool) ?? false }
    private var currentPage: PageInfo? {
        engine.pages.first { $0.id == engine.page }
    }

    var body: some View {
        VStack(spacing: 12) {
            // 顺序和网页版一致：输出/输入卡片 -> 页签栏 -> 当前页内容
            if isLive {
                if !hideLog {
                    outputArea(title: engine.outputTitle + "（日志）")
                }
            } else {
                inputArea
            }
            tabBar
            if let page = currentPage {
                PageView(page: page, engine: engine)
            }
            actionBar
            statusBar
        }
        .sheet(item: $engine.dictionarySheet) { info in
            DictionarySheet(engine: engine, info: info)
        }
        .sheet(item: $engine.aboutSheet) { info in
            AboutSheet(engine: engine, title: info.title, text: info.text)
        }
        .sheet(isPresented: $engine.loginSheet) {
            LoginSheet(engine: engine)
        }
        .padding(16)
        .frame(minWidth: 520, minHeight: 700)
        .alert(item: $engine.alert) { info in
            Alert(
                title: Text(info.title),
                message: Text(info.text),
                dismissButton: .default(Text("好"))
            )
        }
    }

    // MARK: - 可拖的玻璃分段控件

    private var tabBar: some View {
        HStack(spacing: 10) {
            segmentedControl
            Spacer()
            Button(secondaryTitle) { engine.call("action", [secondaryAction]) }
                .buttonStyle(.glass)
                .disabled(!engine.connected)
            Button(primaryTitle) {
                engine.call("action", [engine.running ? "stopLive" : primaryAction])
            }
            .buttonStyle(.glassProminent)
            .disabled(!engine.connected || engine.busy)
        }
    }

    private var segmentedControl: some View {
        // 三个选项决定控件尺寸，轨道是背景，玻璃是覆盖层（overlay 不参与布局，
        // 否则药丸的 frame 会把整条控件撑大）
        HStack(spacing: 2) {
            ForEach(engine.pageTitles, id: \.id) { item in
                let active = (previewId ?? engine.page) == item.id
                Text(item.title)
                    .font(.system(size: 13, weight: .medium))
                    .foregroundStyle(active ? Color.primary : Color.secondary)
                    .padding(.horizontal, 12)
                    .padding(.vertical, 4)
                    .background {
                        GeometryReader { geo in
                            Color.clear.preference(
                                key: TabFramesKey.self,
                                value: [item.id: geo.frame(in: .named(tabSpace))]
                            )
                        }
                    }
                    .contentShape(.capsule)
            }
        }
        .padding(2)
        .background {
            // 轨道 + 那块玻璃，都在文字**下面**：
            // 玻璃放文字上面的话，它的背景模糊会把字糊掉
            ZStack(alignment: .topLeading) {
                Capsule().fill(.regularMaterial)
                if let rect = pillRect {
                    Color.clear
                        .frame(width: max(rect.width, 1), height: max(rect.height, 1))
                        .glassEffect(.regular.interactive(), in: .capsule)
                        .offset(x: rect.minX, y: rect.minY)
                }
            }
            .allowsHitTesting(false)  // 手势由整条控件接管
        }
        .coordinateSpace(name: tabSpace)
        .onPreferenceChange(TabFramesKey.self) { frames in
            tabFrames = frames
            if previewId == nil {
                pillRect = frames[engine.page]
            }
        }
        .onChange(of: engine.page) { _, _ in
            withAnimation(.bouncy(duration: 0.35)) {
                pillRect = tabFrames[engine.page]
            }
        }
        .gesture(
            DragGesture(minimumDistance: 0)
                .onChanged { value in handleDrag(value.location) }
                .onEnded { _ in
                    let target = previewId ?? engine.page
                    previewId = nil
                    withAnimation(.bouncy(duration: 0.35)) {
                        pillRect = tabFrames[target]
                    }
                    if target != engine.page {
                        engine.call("selectPage", [target])
                    }
                }
        )
    }

    private var tabSpace: String { "hzysTabs" }

    /// 拖动中：玻璃"保持形状滑到指针所在的选项"，不拉长。
    /// （之前做成两个矩形取并集，会横跨整条控件——既不还原生也不好看。）
    private func handleDrag(_ point: CGPoint) {
        guard !tabFrames.isEmpty else { return }

        // 只比 x：这是横向拖动，而且 SwiftUI 给的手势坐标和 GeometryReader 量的
        // 矩形未必在同一个坐标空间里（实测 y 对不上），比 y 会永远命中不了
        if let hit = tabFrames.first(where: {
            point.x >= $0.value.minX - 6 && point.x <= $0.value.maxX + 6
        }) {
            guard hit.key != previewId else { return }
            previewId = hit.key
            withAnimation(.bouncy(duration: 0.25)) {
                pillRect = hit.value
            }
            return
        }

        // 指针落在两项之间的缝里：就近吸附，别让玻璃停在半路
        if let nearest = tabFrames.min(by: {
            abs($0.value.midX - point.x) < abs($1.value.midX - point.x)
        }), nearest.key != previewId {
            previewId = nearest.key
            withAnimation(.bouncy(duration: 0.25)) {
                pillRect = nearest.value
            }
        }
    }

    // MARK: - 顶部输出/输入卡片

    private var inputArea: some View {
        card(title: engine.outputTitle) {
            TextEditor(text: Binding(
                get: { engine.input },
                set: { newValue in
                    engine.input = newValue
                    engine.call("inputChanged", [newValue])
                }
            ))
            .font(.system(size: 13))
            .scrollContentBackground(.hidden)
            .overlay(alignment: .topLeading) {
                if engine.input.isEmpty {
                    Text(engine.placeholder)
                        .foregroundStyle(.tertiary)
                        .allowsHitTesting(false)
                }
            }
            .frame(height: 120)
        }
    }

    private func outputArea(title: String) -> some View {
        card(title: title) {
            ScrollView {
                Text(engine.log.isEmpty ? "（还没有输出）" : engine.log)
                    .font(.system(size: 12, design: .monospaced))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(minHeight: 120, maxHeight: 220)
        }
    }

    private func card<Content: View>(
        title: String, @ViewBuilder content: () -> Content
    ) -> some View {
        VStack(alignment: .leading, spacing: 8) {
            Text(title).font(.system(size: 13, weight: .semibold))
            content()
        }
        .frame(maxWidth: .infinity, alignment: .leading)
        .padding(12)
        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 10))
    }

    private var actionBar: some View {
        HStack(spacing: 10) {
            Text(engine.connected ? "引擎已连接" : "引擎未连接")
                .font(.caption)
                .foregroundStyle(engine.connected ? Color.secondary : Color.red)
            Spacer()
            if !engine.connected {
                Button("重新连接") { engine.start() }.buttonStyle(.glass)
            }
        }
    }

    private var statusBar: some View {
        HStack {
            Text("\(engine.title) \(engine.version)")
            Spacer()
            if engine.dirty { Text("设置未保存").foregroundStyle(.orange) }
        }
        .font(.caption)
        .foregroundStyle(.secondary)
    }

    // 按钮文字跟着页面走，和 layout.py 里那套一致
    private var primaryAction: String {
        if engine.page == "settings" { return "saveSettings" }
        return engine.page == "live" ? "startLive" : "play"
    }
    private var primaryTitle: String {
        if engine.running { return "停止" }
        if engine.page == "settings" { return "保存" }
        return engine.page == "live" ? "启动" : "播放"
    }
    private var secondaryAction: String {
        if engine.page == "live" { return "relogin" }
        return engine.page == "settings" ? "resetSettings" : "export"
    }
    private var secondaryTitle: String {
        if engine.page == "live" { return "登录" }
        return engine.page == "settings" ? "恢复默认" : "导出"
    }
}
