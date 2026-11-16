import AppKit
import SwiftUI
import UniformTypeIdentifiers

private let ink = Color(red: 0.07, green: 0.16, blue: 0.17)
private let muted = Color(red: 0.32, green: 0.40, blue: 0.41)
private let accent = Color(red: 0.00, green: 0.34, blue: 0.30)
private let lineColor = Color(red: 0.86, green: 0.90, blue: 0.89)
private let panel = Color(red: 0.98, green: 0.99, blue: 0.98)
private let issue = Color(red: 0.66, green: 0.20, blue: 0.14)

struct Family: Decodable {
    let width: Int
    let border: Int
    let patterns: [[Int]]
}

struct Vector {
    let x: Double
    let y: Double
    let z: Double

    init(_ x: Double, _ y: Double, _ z: Double) { self.x = x; self.y = y; self.z = z }
    init(_ xyz: [Double]) { self.init(xyz[0], xyz[1], xyz[2]) }
    static func + (lhs: Vector, rhs: Vector) -> Vector {
        Vector(lhs.x + rhs.x, lhs.y + rhs.y, lhs.z + rhs.z)
    }
    static func * (lhs: Vector, rhs: Double) -> Vector {
        Vector(lhs.x * rhs, lhs.y * rhs, lhs.z * rhs)
    }
    func dot(_ rhs: Vector) -> Double { x * rhs.x + y * rhs.y + z * rhs.z }
}

struct Face: Decodable {
    let label: String
    let key: String
    let normal: [Double]
    let right: [Double]
    let up: [Double]
}

struct Catalog: Decodable {
    let faces: [Face]
    let families: [String: Family]

    static let shared: Catalog = {
        guard let file = Bundle.main.url(forResource: "families", withExtension: "json"),
              let data = try? Data(contentsOf: file),
              let catalog = try? JSONDecoder().decode(Catalog.self, from: data) else {
            fatalError("无法读取 AprilTag 码表。")
        }
        return catalog
    }()
}

struct Settings: Encodable {
    let family: String
    let cube: Double
    let size: Double
    let depth: Double
    let ids: [Int?]
}

private enum ExportFormat: String {
    case print3MF = "3mf"
    case step

    var label: String { rawValue.uppercased() }
    var extensions: [String] { self == .step ? ["step", "stp"] : [rawValue] }
}

@main
struct AprilTagCubeApp: App {
    var body: some Scene {
        WindowGroup("AprilTag 方块") {
            Editor()
                .preferredColorScheme(.light)
                .frame(minWidth: 920, minHeight: 660)
        }
        .defaultSize(width: 1080, height: 710)
        .windowResizability(.contentMinSize)
        .commands {
            CommandGroup(replacing: .newItem) { }
        }
    }
}

final class EditorModel: ObservableObject {
    @Published var familyName = "tag36h11"
    @Published var cubeText = "60"
    @Published var sizeText = "50"
    @Published var depthText = "0.8"
    @Published var idText = (0...5).map(String.init)
    @Published var enabled = Array(repeating: true, count: 6)
    @Published var exporting = false
    @Published var saved: URL?
    @Published var exportError: String?
    @Published var yaw = CubeCanvas.initialYaw
    @Published var pitch = CubeCanvas.initialPitch
    @Published var dragOrigin: CGSize?
}

struct Editor: View {
    private let catalog = Catalog.shared
    @StateObject private var model = EditorModel()

    private var family: Family { catalog.families[model.familyName]! }
    private var cube: Double? { decimal(model.cubeText) }
    private var size: Double? { decimal(model.sizeText) }
    private var depth: Double? { decimal(model.depthText) }
    private var ids: [Int?] {
        model.idText.indices.map { index in
            guard model.enabled[index], let id = Int(model.idText[index].trimmingCharacters(in: .whitespaces)),
                  family.patterns.indices.contains(id) else { return nil }
            return id
        }
    }
    private var validation: String? {
        guard let cube, (0.1...100_000).contains(cube) else { return "请输入 0.1 至 100,000 mm 的方块边长。" }
        guard let size, (0.1...cube).contains(size) else { return "码图边长需在 0.1 mm 与方块边长之间。" }
        guard let depth, depth >= 0.001 else { return "嵌入深度至少为 0.001 mm。" }
        let whiteMargin = model.familyName == "tag36h11" ? size / Double(family.width) : 0
        guard depth + 0.001 <= (cube - size) / 2 + whiteMargin else {
            return "嵌入深度过大，请减小码图或嵌入深度。"
        }
        guard model.enabled.contains(true) else { return "至少勾选一个面。" }
        guard !ids.indices.contains(where: { model.enabled[$0] && ids[$0] == nil }) else {
            return "已勾选面的 ID 必须是 0–\(family.patterns.count - 1) 的整数。"
        }
        return nil
    }
    private var ratio: Double {
        guard let cube, let size, cube > 0, size > 0 else { return 0.8 }
        return min(size / cube, 1)
    }

    var body: some View {
        HStack(spacing: 0) {
            VStack(alignment: .leading, spacing: 16) {
                heading
                preview
            }
            .padding(24)
            .frame(maxWidth: .infinity, maxHeight: .infinity)
            .background(panel)

            Rectangle().fill(lineColor).frame(width: 1)

            VStack(spacing: 0) {
                ScrollView {
                    inspector.padding(.horizontal, 21).padding(.vertical, 19)
                }
                Divider().overlay(lineColor)
                exportControls
            }
            .frame(width: 320)
            .background(Color.white)
        }
        .tint(accent)
        .foregroundStyle(ink)
        .alert("导出失败", isPresented: Binding(
            get: { model.exportError != nil }, set: { if !$0 { model.exportError = nil } }
        )) {
            Button("好", role: .cancel) { model.exportError = nil }
        } message: {
            Text(model.exportError ?? "")
        }
    }

    private var heading: some View {
        HStack(spacing: 12) {
            Image(systemName: "cube")
                .font(.system(size: 23, weight: .medium))
                .foregroundStyle(.white)
                .frame(width: 46, height: 46)
                .background(accent, in: RoundedRectangle(cornerRadius: 12))
                .accessibilityHidden(true)
            VStack(alignment: .leading, spacing: 3) {
                Text("AprilTag 方块").font(.system(size: 27, weight: .semibold))
                Text("三维预览").font(.system(size: 12, weight: .medium)).foregroundStyle(muted)
            }
            Spacer()
            Button {
                model.yaw = CubeCanvas.initialYaw
                model.pitch = CubeCanvas.initialPitch
            } label: {
                Label("重置视角", systemImage: "arrow.counterclockwise")
                    .font(.system(size: 12, weight: .medium))
                    .padding(.horizontal, 10).padding(.vertical, 7)
                    .background(Color.white, in: RoundedRectangle(cornerRadius: 7))
                    .overlay(RoundedRectangle(cornerRadius: 7).strokeBorder(lineColor))
            }
            .buttonStyle(.plain)
        }
    }

    private var preview: some View {
        VStack(spacing: 0) {
            CubeCanvas(faces: catalog.faces, family: family, ids: ids, ratio: ratio, yaw: model.yaw, pitch: model.pitch)
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .gesture(DragGesture(minimumDistance: 1).onChanged { value in
                    if model.dragOrigin == nil { model.dragOrigin = CGSize(width: model.yaw, height: model.pitch) }
                    let origin = model.dragOrigin ?? .zero
                    model.yaw = origin.width + value.translation.width * 0.012
                    model.pitch = max(-1.56, min(1.56, origin.height + value.translation.height * 0.009))
                }.onEnded { _ in model.dragOrigin = nil })
                .overlay(alignment: .topLeading) {
                    Label("拖动旋转", systemImage: "hand.draw")
                        .font(.system(size: 12, weight: .medium))
                        .foregroundStyle(muted)
                        .padding(14)
                        .allowsHitTesting(false)
                }
                .accessibilityLabel("AprilTag 方块三维预览")
            Rectangle().fill(lineColor).frame(height: 1)
            HStack(alignment: .top, spacing: 16) {
                measure("方块边长", cube)
                Spacer(minLength: 0)
                measure("码图边长", size)
                Spacer(minLength: 0)
                measure("检测边长", size.map { $0 * Double(family.border) / Double(family.width) })
                    .help("位姿估计所用的尺寸，按检测角点间距计算。")
            }
            .padding(.horizontal, 17)
            .padding(.vertical, 13)
            .background(Color.white)
        }
        .clipShape(RoundedRectangle(cornerRadius: 15))
        .overlay(RoundedRectangle(cornerRadius: 15).strokeBorder(lineColor))
    }

    private func measure(_ label: String, _ value: Double?) -> some View {
        VStack(alignment: .leading, spacing: 5) {
            Text(label).font(.system(size: 11, weight: .medium)).foregroundStyle(muted)
            Text(value.map { "\($0.formatted(.number.precision(.fractionLength(0...4)))) mm" } ?? "—")
                .font(.system(size: 16, weight: .semibold, design: .monospaced))
                .lineLimit(1).minimumScaleFactor(0.75)
        }
    }

    private var inspector: some View {
        VStack(alignment: .leading, spacing: 16) {
            VStack(alignment: .leading, spacing: 10) {
                sectionTitle("模型尺寸")
                dimension("方块边长", text: $model.cubeText)
                dimension("码图边长", text: $model.sizeText)
                dimension("嵌入深度", text: $model.depthText)
                Text("码图边长含码族原有边框。黑色嵌件与白色方块表面齐平。")
                    .font(.system(size: 11)).foregroundStyle(muted)
                    .fixedSize(horizontal: false, vertical: true)
            }

            Divider().overlay(lineColor)

            VStack(alignment: .leading, spacing: 9) {
                sectionTitle("码族与面")
                Picker(selection: $model.familyName) {
                    ForEach(catalog.families.keys.sorted(), id: \.self) { key in
                        Text(key).tag(key)
                    }
                } label: {
                    Text("AprilTag 码族")
                }
                .labelsHidden()
                .frame(maxWidth: .infinity)
                HStack {
                    Text("勾选需要有码的面")
                    Spacer()
                    Text("ID 0–\(family.patterns.count - 1)").monospacedDigit()
                }
                .font(.system(size: 11)).foregroundStyle(muted)
                LazyVGrid(columns: [GridItem(.flexible(), spacing: 8), GridItem(.flexible())], spacing: 8) {
                    ForEach(catalog.faces.indices, id: \.self) { index in
                        faceField(index)
                    }
                }
            }
        }
    }

    private func sectionTitle(_ title: String) -> some View {
        Text(title).font(.system(size: 15, weight: .semibold))
    }

    private func dimension(_ label: String, text: Binding<String>) -> some View {
        HStack {
            Text(label).font(.system(size: 13))
            Spacer()
            TextField(label, text: text)
                .labelsHidden()
                .multilineTextAlignment(.trailing)
                .font(.system(size: 13, design: .monospaced))
                .textFieldStyle(.roundedBorder)
                .frame(width: 94)
            Text("mm").font(.system(size: 11, design: .monospaced)).foregroundStyle(muted)
        }
    }

    private func faceField(_ index: Int) -> some View {
        let name = catalog.faces[index].label
        return HStack(spacing: 6) {
            Toggle(isOn: $model.enabled[index]) {
                Text(name).font(.system(size: 12, weight: .medium))
            }
            .toggleStyle(.checkbox)
            Spacer(minLength: 0)
            TextField("\(name)面 ID", text: $model.idText[index])
                .labelsHidden()
                .multilineTextAlignment(.trailing)
                .font(.system(size: 12, design: .monospaced))
                .textFieldStyle(.roundedBorder)
                .frame(width: 43)
                .disabled(!model.enabled[index])
        }
        .padding(6)
        .background(panel, in: RoundedRectangle(cornerRadius: 6))
        .overlay(RoundedRectangle(cornerRadius: 6).strokeBorder(lineColor))
    }

    private var exportControls: some View {
        VStack(alignment: .leading, spacing: 8) {
            if let validation {
                Label(validation, systemImage: "exclamationmark.circle")
                    .font(.system(size: 11)).foregroundStyle(issue)
                    .fixedSize(horizontal: false, vertical: true)
            } else if let saved = model.saved {
                Button {
                    NSWorkspace.shared.activateFileViewerSelecting([saved])
                } label: {
                    Label("已导出 · 在访达中显示", systemImage: "checkmark.circle.fill")
                        .font(.system(size: 11, weight: .medium))
                        .foregroundStyle(accent)
                }
                .buttonStyle(.plain)
                .help(saved.path)
            }
            HStack(spacing: 10) {
                Button { startExport(.step) } label: {
                    Text("导出 STEP")
                        .font(.system(size: 12, weight: .medium))
                        .padding(.horizontal, 10)
                        .frame(height: 42)
                        .overlay(RoundedRectangle(cornerRadius: 8).strokeBorder(lineColor))
                }
                .buttonStyle(.plain)
                .keyboardShortcut("s", modifiers: [.command, .shift])
                .disabled(validation != nil || model.exporting)
                printExportButton
            }
            let shallowInlay = depth.map { $0 < 0.4 } ?? false
            Text(shallowInlay
                 ? "嵌件太薄时可能被切片省略。常用 0.2 mm 层高可先试 0.8 mm 深度。"
                 : "3MF 可导入 Bambu Studio，为黑白两部分分配耗材。")
                .font(.system(size: 11))
                .foregroundStyle(shallowInlay ? issue : muted)
                .fixedSize(horizontal: false, vertical: true)
        }
        .padding(.horizontal, 21)
        .padding(.vertical, 15)
    }

    private var printExportButton: some View {
        Button { startExport(.print3MF) } label: {
            HStack {
                Spacer()
                if model.exporting {
                    ProgressView().controlSize(.small).tint(.white).padding(.trailing, 2)
                    Text("正在导出…")
                } else {
                    Image(systemName: "arrow.down.to.line")
                    Text("导出打印 3MF")
                }
                Spacer()
            }
            .font(.system(size: 13, weight: .semibold))
            .foregroundStyle(.white)
            .frame(height: 42)
            .background(
                validation != nil || model.exporting ? muted : accent,
                in: RoundedRectangle(cornerRadius: 8)
            )
        }
        .buttonStyle(.plain)
        .keyboardShortcut("s", modifiers: [.command])
        .disabled(validation != nil || model.exporting)
    }

    private func decimal(_ text: String) -> Double? {
        let trimmed = text.trimmingCharacters(in: .whitespaces)
        guard let value = Double(trimmed.replacingOccurrences(of: ",", with: ".")),
              value.isFinite else { return nil }
        return value
    }

    private func startExport(_ format: ExportFormat) {
        guard validation == nil, !model.exporting, let cube, let size, let depth else { return }
        let settings = Settings(family: model.familyName, cube: cube, size: size, depth: depth, ids: ids)
        let dialog = NSSavePanel()
        dialog.title = "导出 \(format.label)"
        dialog.message = "选择 \(format.label) 文件的保存位置。"
        dialog.nameFieldStringValue = "AprilTag_\(model.familyName)_\(cube.formatted(.number.grouping(.never)))mm.\(format.rawValue)"
        dialog.canCreateDirectories = true
        dialog.isExtensionHidden = false
        dialog.directoryURL = Bundle.main.bundleURL.deletingLastPathComponent()
        let contentTypes = format.extensions.compactMap { UTType(filenameExtension: $0) }
        if !contentTypes.isEmpty {
            dialog.allowedContentTypes = contentTypes
            dialog.allowsOtherFileTypes = false
        }
        let accepted: (NSApplication.ModalResponse) -> Void = { response in
            guard response == .OK, var url = dialog.url else { return }
            if !format.extensions.contains(url.pathExtension.lowercased()) {
                url.appendPathExtension(format.rawValue)
                if FileManager.default.fileExists(atPath: url.path) {
                    self.model.exportError = "同名文件已存在。请在保存面板中输入完整文件名以确认替换。"
                    return
                }
            }
            self.model.saved = nil
            self.model.exporting = true
            self.runExport(settings, to: url)
        }
        if let window = NSApp.keyWindow {
            dialog.beginSheetModal(for: window, completionHandler: accepted)
        } else {
            dialog.begin(completionHandler: accepted)
        }
    }

    private func runExport(_ settings: Settings, to url: URL) {
        DispatchQueue.global(qos: .userInitiated).async {
            let outcome = Result {
                let installedPython = FileManager.default.homeDirectoryForCurrentUser
                    .appendingPathComponent("Library/Application Support/AprilTagCube/runtime/bin/python")
                let bundledPython = Bundle.main.resourceURL?.appendingPathComponent("runtime/bin/python3.13")
                let python = bundledPython.flatMap {
                    FileManager.default.isExecutableFile(atPath: $0.path) ? $0 : nil
                } ?? installedPython
                guard FileManager.default.isExecutableFile(atPath: python.path),
                      let script = Bundle.main.url(forResource: "exporter", withExtension: "py") else {
                    throw ExportFailure(message: "找不到 CAD 运行环境，请运行源码文件夹中的安装脚本。")
                }
                let process = Process()
                let input = Pipe()
                let errors = Pipe()
                let data = try JSONEncoder().encode(settings)
                process.executableURL = python
                process.arguments = ["-I", "-B", script.path, url.path]
                process.standardInput = input
                process.standardOutput = FileHandle.nullDevice
                process.standardError = errors
                try process.run()
                try input.fileHandleForWriting.write(contentsOf: data)
                try input.fileHandleForWriting.close()
                let details = errors.fileHandleForReading.readDataToEndOfFile()
                process.waitUntilExit()
                guard process.terminationStatus == 0 else {
                    let message = String(decoding: details, as: UTF8.self)
                        .trimmingCharacters(in: .whitespacesAndNewlines)
                    throw ExportFailure(message: message.isEmpty ? "CAD 进程未完成导出。" : message)
                }
            }
            DispatchQueue.main.async {
                self.model.exporting = false
                switch outcome {
                case .success: self.model.saved = url
                case .failure(let error): self.model.exportError = error.localizedDescription
                }
            }
        }
    }
}

struct ExportFailure: LocalizedError {
    let message: String
    var errorDescription: String? { message }
}

struct CubeCanvas: View {
    static let initialYaw = -0.63
    static let initialPitch = 0.48

    let faces: [Face]
    let family: Family
    let ids: [Int?]
    let ratio: Double
    let yaw: Double
    let pitch: Double

    private let paper = Color(red: 0.93, green: 0.96, blue: 0.95)

    var body: some View {
        Canvas { graphics, size in
            drawGrid(graphics, size)
            let view = Vector(sin(yaw) * cos(pitch), cos(yaw) * cos(pitch), sin(pitch))
            let horizontal = Vector(-cos(yaw), sin(yaw), 0)
            let vertical = Vector(-sin(yaw) * sin(pitch), -cos(yaw) * sin(pitch), cos(pitch))
            let scale = min(size.width, size.height) * 0.43
            let center = CGPoint(x: size.width / 2, y: size.height / 2)
            func project(_ point: Vector) -> CGPoint {
                CGPoint(x: center.x + point.dot(horizontal) * scale,
                        y: center.y - point.dot(vertical) * scale)
            }
            for index in faces.indices {
                let face = faces[index]
                let normal = Vector(face.normal)
                guard normal.dot(view) > 1e-8 else { continue }
                let right = Vector(face.right)
                let up = Vector(face.up)
                func point(_ x: Double, _ y: Double) -> CGPoint {
                    project(normal * 0.5 + right * x + up * y)
                }
                func quad(_ left: Double, _ top: Double, _ right: Double, _ bottom: Double) -> Path {
                    var path = Path()
                    path.addLines([point(left, top), point(right, top), point(right, bottom), point(left, bottom)])
                    path.closeSubpath()
                    return path
                }
                let surface = quad(-0.5, 0.5, 0.5, -0.5)
                let light = Vector(-0.25, 0.62, 0.76)
                let shade = min(1, 0.79 + max(0, normal.dot(light)) * 0.20)
                graphics.fill(surface, with: .color(Color(red: shade, green: shade, blue: shade * 0.996)))
                if let id = ids[index] {
                    let rows = family.patterns[id]
                    let pitch = ratio / Double(family.width)
                    var pattern = Path()
                    for y in rows.indices {
                        var x = 0
                        while x < family.width {
                            guard rows[y] & (1 << x) != 0 else { x += 1; continue }
                            let start = x
                            repeat { x += 1 } while x < family.width && rows[y] & (1 << x) != 0
                            let top = ratio / 2 - Double(y) * pitch
                            pattern.addPath(quad(
                                Double(start) * pitch - ratio / 2, top,
                                Double(x) * pitch - ratio / 2, top - pitch
                            ))
                        }
                    }
                    graphics.fill(pattern, with: .color(Color(white: 0.035 + (1 - shade) * 0.09)))
                }
                graphics.stroke(surface, with: .color(ink.opacity(0.30)), lineWidth: 1)
            }
        }
        .background(paper)
    }

    private func drawGrid(_ graphics: GraphicsContext, _ size: CGSize) {
        let spacing = 24.0
        let center = CGPoint(x: size.width / 2, y: size.height / 2)
        var grid = Path()
        for x in stride(from: center.x.truncatingRemainder(dividingBy: spacing), to: size.width, by: spacing) {
            grid.move(to: CGPoint(x: x, y: 0))
            grid.addLine(to: CGPoint(x: x, y: size.height))
        }
        for y in stride(from: center.y.truncatingRemainder(dividingBy: spacing), to: size.height, by: spacing) {
            grid.move(to: CGPoint(x: 0, y: y))
            grid.addLine(to: CGPoint(x: size.width, y: y))
        }
        graphics.stroke(grid, with: .color(accent.opacity(0.075)), lineWidth: 0.75)
    }
}
