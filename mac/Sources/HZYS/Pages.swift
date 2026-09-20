import SwiftUI

// 引擎发过来的页面结构（和网页界面渲染的是同一份 layout.buildPages()）

struct PageInfo: Codable, Identifiable {
    let id: String
    let title: String
    let cards: [CardInfo]
}

struct CardInfo: Codable, Identifiable {
    var id: String { title }
    let title: String
    let rows: [RowInfo]
}

struct SwitchItem: Codable, Identifiable {
    var id: String { name }
    let name: String
    let text: String
    let `var`: String
}

struct RowInfo: Codable, Identifiable {
    // 注意：这里必须是 let（带默认值的 let 不参与解码），
    // 写成 var 的话合成解码器会要求 JSON 里也有 "id"，整包解析就失败了
    let id = UUID()
    let kind: String
    // ("row", ...)
    var items: [SwitchItem]?
    // slider
    var label: String?
    var `var`: String?
    var min: Double?
    var max: Double?
    var step: Double?
    var digits: Int?
    // path
    var title: String?
    var option: String?
    var editor: Int?
    var choose: String?
    var editText: String?
    // footer
    var text: String?
}

struct DictionaryInfo: Codable, Identifiable {
    var id: Int { mode }
    let mode: Int
    let title: String
    let name: String
    let value: String
    let valueRequired: Bool
}

/// 一页的内容：卡片 -> 行 -> 控件，全部由引擎给的结构生成。
///
/// 用 SwiftUI 原生的 Form + Section + LabeledContent（就是系统"设置"那种
/// 分组排版），尺寸、间距、对齐都由系统给，不再自己摆。
struct PageView: View {
    let page: PageInfo
    @ObservedObject var engine: EngineClient

    var body: some View {
        Form {
            ForEach(page.cards) { card in
                Section {
                    ForEach(card.rows) { row in
                        rowView(row)
                    }
                } header: {
                    Text(card.title)
                }
            }
        }
        .formStyle(.grouped)
        .scrollContentBackground(.hidden)  // 底色用窗口自己的，别让表单刷白
    }

    @ViewBuilder
    private func rowView(_ row: RowInfo) -> some View {
        switch row.kind {
        case "row":
            ForEach(row.items ?? []) { item in
                switchRow(item)
            }
        case "slider":
            sliderRow(row)
        case "path":
            pathRow(row)
        case "entry":
            entryRow(row)
        case "footer":
            footerRow(row)
        default:
            EmptyView()
        }
    }

    // 开关：系统 Toggle（macOS 26 上自带 Liquid Glass 的交互反馈）
    private func switchRow(_ item: SwitchItem) -> some View {
        Toggle(item.text, isOn: Binding(
            get: { (engine.values[item.var] as? Bool) ?? false },
            set: { engine.call("setValue", [item.var, $0]) }
        ))
        .toggleStyle(.switch)
    }

    // 滑块：不要给 Slider 传 step —— macOS 26 会因此画一排刻度点；
    // 这里自己按步长取整，行为一样但外观干净
    private func sliderRow(_ row: RowInfo) -> some View {
        let name = row.`var` ?? ""
        let digits = row.digits ?? 1
        let step = row.step ?? 0.1
        let value = (engine.values[name] as? Double) ?? 1.0
        return LabeledContent(row.label ?? "") {
            HStack(spacing: 8) {
                Slider(
                    value: Binding(
                        get: { value },
                        set: { raw in
                            let stepped = (raw / step).rounded() * step
                            engine.call("setValue", [name, stepped])
                        }
                    ),
                    in: (row.min ?? 0)...(row.max ?? 1)
                )
                .frame(minWidth: 160)
                Text(String(format: "%.\(digits)f", value))
                    .font(.system(size: 12, design: .monospaced))
                    .foregroundStyle(.secondary)
                    .frame(width: 46, alignment: .trailing)
            }
        }
    }

    private func pathRow(_ row: RowInfo) -> some View {
        let option = row.option ?? ""
        return LabeledContent(row.title ?? "") {
            HStack(spacing: 6) {
                Text(engine.paths[option] ?? "")
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                    .truncationMode(.middle)
                    .frame(maxWidth: 240, alignment: .trailing)
                Button(row.choose ?? "选择") { engine.call("pickPath", [option]) }
                    .controlSize(.small)
                if let editor = row.editor {
                    Button(row.editText ?? "编辑") { engine.openDictionary(editor) }
                        .controlSize(.small)
                }
            }
        }
    }

    private func entryRow(_ row: RowInfo) -> some View {
        let option = row.option ?? ""
        return LabeledContent(row.title ?? "") {
            TextField("", text: Binding(
                get: { engine.entries[option] ?? "" },
                set: { engine.call("setEditorValue", [option, $0]) }
            ))
            .textFieldStyle(.roundedBorder)
            .frame(width: 110)
        }
    }

    private func footerRow(_ row: RowInfo) -> some View {
        VStack(alignment: .leading, spacing: 10) {
            Text(row.text ?? "")
                .font(.caption)
                .foregroundStyle(.secondary)
                .fixedSize(horizontal: false, vertical: true)
            HStack(spacing: 8) {
                Button(engine.buttons["footerUpdate"] ?? "更新") { engine.checkUpdate() }
                Button(engine.buttons["footerAbout"] ?? "更多…") { engine.showAbout() }
            }
            .controlSize(.small)
        }
    }
}
