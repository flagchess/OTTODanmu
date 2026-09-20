import SwiftUI

/// 词典编辑：逐行改、加行、删行，按「保存」写回。结构和网页版弹层一致。
struct DictionarySheet: View {
    @ObservedObject var engine: EngineClient
    let info: DictionaryInfo
    @State private var rows: [[String]] = []
    @State private var loaded = false

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            HStack {
                Text(info.title).font(.system(size: 14, weight: .semibold))
                Spacer()
                Text("\(rows.count) 条").font(.caption).foregroundStyle(.secondary)
            }
            HStack(spacing: 8) {
                Text(info.name).font(.caption).frame(width: 150, alignment: .leading)
                Text(info.value).font(.caption)
                Spacer()
            }
            ScrollView {
                VStack(spacing: 6) {
                    ForEach(rows.indices, id: \.self) { index in
                        HStack(spacing: 6) {
                            TextField(info.name, text: Binding(
                                get: { rows[index][0] },
                                set: { rows[index][0] = $0 }
                            ))
                            .textFieldStyle(.roundedBorder)
                            TextField(info.value, text: Binding(
                                get: { rows[index][1] },
                                set: { rows[index][1] = $0 }
                            ))
                            .textFieldStyle(.roundedBorder)
                            Button {
                                rows.remove(at: index)
                            } label: {
                                Image(systemName: "trash")
                            }
                            .buttonStyle(.glass)
                            .controlSize(.small)
                        }
                    }
                }
            }
            .frame(minHeight: 260)

            HStack {
                Button(engine.buttons["dictAdd"] ?? "添加") {
                    rows.append(["", ""])
                }
                .buttonStyle(.glass)
                Spacer()
                Button(engine.buttons["dictCancel"] ?? "取消") { engine.dictionarySheet = nil }
                    .buttonStyle(.glass)
                Button(engine.buttons["dictSave"] ?? "保存") {
                    engine.saveDictionary(mode: info.mode, rows: rows)
                }
                .buttonStyle(.glassProminent)
            }
        }
        .padding(16)
        .frame(minWidth: 520, minHeight: 420)
        .onAppear {
            guard !loaded else { return }
            loaded = true
            engine.loadDictionary(info.mode) { loaded in
                rows = loaded
            }
        }
    }
}

/// 关于/更多：内容和网页版弹层一样，来自 update.getupdateinfo()
struct AboutSheet: View {
    @ObservedObject var engine: EngineClient
    let title: String
    let text: String

    var body: some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(title).font(.system(size: 14, weight: .semibold))
            ScrollView {
                Text(text)
                    .font(.system(size: 12))
                    .textSelection(.enabled)
                    .frame(maxWidth: .infinity, alignment: .leading)
            }
            .frame(minHeight: 300)
            HStack {
                Button(engine.buttons["aboutAuthor"] ?? "作者主页") { engine.openAuthor() }
                    .buttonStyle(.glass)
                Button(engine.buttons["aboutUpdate"] ?? "打开更新页") { engine.openReleases() }
                    .buttonStyle(.glass)
                Spacer()
                Button(engine.buttons["aboutClose"] ?? "关闭") { engine.aboutSheet = nil }
                    .buttonStyle(.glassProminent)
            }
        }
        .padding(16)
        .frame(minWidth: 520, minHeight: 460)
    }
}

/// 扫码登录：引擎把二维码推过来（base64 PNG），这里显示并更新状态
struct LoginSheet: View {
    @ObservedObject var engine: EngineClient

    var body: some View {
        VStack(spacing: 12) {
            Text("扫码登录").font(.system(size: 14, weight: .semibold))
            if let image = engine.loginImage,
               let nsImage = NSImage(data: image) {
                Image(nsImage: nsImage)
                    .interpolation(.none)
                    .resizable()
                    .frame(width: 210, height: 210)
                    .padding(8)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 8))
            } else {
                ProgressView().frame(width: 210, height: 210)
            }
            Text(engine.loginStatus.isEmpty ? "正在获取二维码…" : engine.loginStatus)
                .font(.system(size: 12))
                .foregroundStyle(.secondary)
            HStack {
                Button(engine.buttons["重新获取二维码"] ?? "重新获取二维码") {
                    engine.call("action", ["relogin"])
                }
                .buttonStyle(.glass)
                Spacer()
                Button("关闭") { engine.loginSheet = false }
                    .buttonStyle(.glassProminent)
            }
        }
        .padding(16)
        .frame(minWidth: 300)
    }
}
