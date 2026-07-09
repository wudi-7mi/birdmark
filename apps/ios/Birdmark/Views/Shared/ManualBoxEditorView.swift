import SwiftUI
import UIKit

struct ManualBoxEditorView: View {
    let image: UIImage
    let pixelSize: CGSize?
    let onCancel: () -> Void
    let onConfirm: (ManualObservationRequest) async throws -> Void

    @State private var selectionRect: CGRect?
    @State private var containerSize: CGSize = .zero
    @State private var zoomScale: CGFloat = 1
    @State private var baseZoomScale: CGFloat = 1
    @State private var isSubmitting = false
    @State private var errorMessage: String?

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            GeometryReader { geometry in
                let size = geometry.size
                let imageRect = displayedImageRect(in: size)
                let visibleImageRect = imageRect.intersection(CGRect(origin: .zero, size: size))
                let editBounds = visibleImageRect.isNull ? CGRect(origin: .zero, size: size) : visibleImageRect

                ZStack(alignment: .topLeading) {
                    Image(uiImage: image)
                        .resizable()
                        .frame(width: baseImageRect(in: size).width, height: baseImageRect(in: size).height)
                        .scaleEffect(zoomScale)
                        .position(x: baseImageRect(in: size).midX, y: baseImageRect(in: size).midY)

                    EditableCropBox(
                        rect: $selectionRect,
                        bounds: editBounds,
                        minSize: 48
                    )
                }
                .frame(maxWidth: .infinity, maxHeight: .infinity)
                .contentShape(Rectangle())
                .simultaneousGesture(
                    MagnificationGesture()
                        .onChanged { value in
                            zoomScale = (baseZoomScale * value).clamped(to: 1...4)
                            clampSelection(to: editBounds)
                        }
                        .onEnded { _ in
                            baseZoomScale = zoomScale
                            clampSelection(to: editBounds)
                        }
                )
                .onAppear {
                    containerSize = size
                    ensureDefaultSelection(in: editBounds)
                }
                .onChange(of: size) { _, newSize in
                    containerSize = newSize
                    let newImageRect = displayedImageRect(in: newSize)
                    let newVisibleImageRect = newImageRect.intersection(CGRect(origin: .zero, size: newSize))
                    let newEditBounds = newVisibleImageRect.isNull ? CGRect(origin: .zero, size: newSize) : newVisibleImageRect
                    ensureDefaultSelection(in: newEditBounds)
                    clampSelection(to: newEditBounds)
                }
            }

            VStack(spacing: 0) {
                HStack {
                    FloatingEditorButton(systemImage: "xmark", action: onCancel)
                        .disabled(isSubmitting)

                    Spacer()

                    Button {
                        Task { await submit() }
                    } label: {
                        ZStack {
                            Circle()
                                .fill(.ultraThinMaterial)
                                .frame(width: 46, height: 46)
                            if isSubmitting {
                                ProgressView()
                                    .tint(.white)
                            } else {
                                Image(systemName: "checkmark")
                                    .font(.headline.weight(.semibold))
                                    .foregroundStyle(.white)
                            }
                        }
                    }
                    .buttonStyle(.plain)
                    .disabled(isSubmitting || manualObservationRequest == nil)
                    .opacity(manualObservationRequest == nil ? 0.45 : 1)
                }
                .padding(.horizontal, 18)
                .padding(.top, 14)

                Spacer()

                if let errorMessage {
                    Text(errorMessage)
                        .font(.subheadline)
                        .foregroundStyle(.white)
                        .padding(.horizontal, 14)
                        .padding(.vertical, 10)
                        .background(.ultraThinMaterial, in: RoundedRectangle(cornerRadius: 8))
                        .padding(.horizontal)
                        .padding(.bottom, 18)
                }
            }
        }
    }

    private var resolvedPixelSize: CGSize {
        if let pixelSize, pixelSize.width > 0, pixelSize.height > 0 {
            return pixelSize
        }
        return CGSize(
            width: image.size.width * image.scale,
            height: image.size.height * image.scale
        )
    }

    private var imageAspectRatio: CGFloat {
        guard image.size.height > 0 else {
            return 4.0 / 3.0
        }
        return image.size.width / image.size.height
    }

    private var manualObservationRequest: ManualObservationRequest? {
        guard
            let rect = selectionRect?.standardized,
            rect.width >= 16,
            rect.height >= 16,
            containerSize.width > 0,
            containerSize.height > 0
        else {
            return nil
        }

        let imageRect = displayedImageRect(in: containerSize)
        guard imageRect.width > 0, imageRect.height > 0 else {
            return nil
        }

        let width = Int(resolvedPixelSize.width.rounded())
        let height = Int(resolvedPixelSize.height.rounded())
        guard width > 0, height > 0 else {
            return nil
        }

        let x1 = clamp(Int(((rect.minX - imageRect.minX) / imageRect.width * CGFloat(width)).rounded()), min: 0, max: width)
        let y1 = clamp(Int(((rect.minY - imageRect.minY) / imageRect.height * CGFloat(height)).rounded()), min: 0, max: height)
        let x2 = clamp(Int(((rect.maxX - imageRect.minX) / imageRect.width * CGFloat(width)).rounded()), min: 0, max: width)
        let y2 = clamp(Int(((rect.maxY - imageRect.minY) / imageRect.height * CGFloat(height)).rounded()), min: 0, max: height)

        guard x2 - x1 >= 10, y2 - y1 >= 10 else {
            return nil
        }

        return ManualObservationRequest(
            bboxX1: x1,
            bboxY1: y1,
            bboxX2: x2,
            bboxY2: y2,
            topK: 5
        )
    }

    private func submit() async {
        guard let request = manualObservationRequest else {
            return
        }

        isSubmitting = true
        errorMessage = nil
        do {
            try await onConfirm(request)
        } catch {
            errorMessage = error.localizedDescription
            isSubmitting = false
        }
    }

    private func baseImageRect(in size: CGSize) -> CGRect {
        guard size.width > 0, size.height > 0, imageAspectRatio > 0 else {
            return .zero
        }

        let containerAspectRatio = size.width / size.height
        if containerAspectRatio > imageAspectRatio {
            let height = size.height
            let width = height * imageAspectRatio
            return CGRect(x: (size.width - width) / 2, y: 0, width: width, height: height)
        }

        let width = size.width
        let height = width / imageAspectRatio
        return CGRect(x: 0, y: (size.height - height) / 2, width: width, height: height)
    }

    private func displayedImageRect(in size: CGSize) -> CGRect {
        let baseRect = baseImageRect(in: size)
        let scaledSize = CGSize(width: baseRect.width * zoomScale, height: baseRect.height * zoomScale)
        return CGRect(
            x: baseRect.midX - scaledSize.width / 2,
            y: baseRect.midY - scaledSize.height / 2,
            width: scaledSize.width,
            height: scaledSize.height
        )
    }

    private func ensureDefaultSelection(in bounds: CGRect) {
        guard selectionRect == nil, bounds.width > 0, bounds.height > 0 else {
            return
        }

        let side = min(bounds.width, bounds.height) * 0.46
        let width = max(80, side)
        let height = max(80, side)
        selectionRect = CGRect(
            x: bounds.midX - width / 2,
            y: bounds.midY - height / 2,
            width: min(width, bounds.width),
            height: min(height, bounds.height)
        )
    }

    private func clampSelection(to bounds: CGRect) {
        guard let rect = selectionRect else {
            return
        }
        selectionRect = rect.clamped(to: bounds, minSize: 48)
    }

    private func clamp(_ value: Int, min minimum: Int, max maximum: Int) -> Int {
        Swift.max(minimum, Swift.min(maximum, value))
    }
}

struct RemoteManualBoxEditorView: View {
    let imageURL: URL?
    let pixelSize: CGSize?
    let onCancel: () -> Void
    let onConfirm: (ManualObservationRequest) async throws -> Void

    @State private var image: UIImage?
    @State private var errorMessage: String?
    @State private var isLoading = false

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            if let image {
                ManualBoxEditorView(
                    image: image,
                    pixelSize: pixelSize,
                    onCancel: onCancel,
                    onConfirm: onConfirm
                )
            } else {
                VStack(spacing: 14) {
                    if isLoading {
                        ProgressView()
                            .tint(.white)
                    }
                    if let errorMessage {
                        Text(errorMessage)
                            .foregroundStyle(.white)
                            .multilineTextAlignment(.center)
                            .padding(.horizontal)
                    }
                }
            }

            if image == nil {
                VStack {
                    HStack {
                        FloatingEditorButton(systemImage: "xmark", action: onCancel)
                        Spacer()
                    }
                    .padding(.horizontal, 18)
                    .padding(.top, 14)
                    Spacer()
                }
            }
        }
        .task {
            await loadImage()
        }
    }

    private func loadImage() async {
        guard image == nil else {
            return
        }
        guard let imageURL else {
            errorMessage = "图片地址无效"
            return
        }

        isLoading = true
        defer { isLoading = false }
        do {
            let (data, _) = try await URLSession.shared.data(from: imageURL)
            guard let loadedImage = UIImage(data: data) else {
                throw APIError.transport("无法读取图片")
            }
            image = loadedImage
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct FloatingEditorButton: View {
    let systemImage: String
    let action: () -> Void

    var body: some View {
        Button(action: action) {
            ZStack {
                Circle()
                    .fill(.ultraThinMaterial)
                    .frame(width: 46, height: 46)
                Image(systemName: systemImage)
                    .font(.headline.weight(.semibold))
                    .foregroundStyle(.white)
            }
        }
        .buttonStyle(.plain)
    }
}

private struct EditableCropBox: View {
    @Binding var rect: CGRect?
    let bounds: CGRect
    let minSize: CGFloat

    @State private var moveStartRect: CGRect?

    var body: some View {
        if let cropRect = rect?.standardized {
            ZStack(alignment: .topLeading) {
                Rectangle()
                    .fill(.clear)
                    .contentShape(Rectangle())
                    .frame(width: cropRect.width, height: cropRect.height)
                    .overlay {
                        Rectangle()
                            .stroke(.yellow, lineWidth: 2)
                    }
                    .offset(x: cropRect.minX, y: cropRect.minY)
                    .gesture(moveGesture)

                CropHandle(corner: .topLeft, rect: $rect, bounds: bounds, minSize: minSize)
                    .position(x: cropRect.minX, y: cropRect.minY)
                CropHandle(corner: .topRight, rect: $rect, bounds: bounds, minSize: minSize)
                    .position(x: cropRect.maxX, y: cropRect.minY)
                CropHandle(corner: .bottomLeft, rect: $rect, bounds: bounds, minSize: minSize)
                    .position(x: cropRect.minX, y: cropRect.maxY)
                CropHandle(corner: .bottomRight, rect: $rect, bounds: bounds, minSize: minSize)
                    .position(x: cropRect.maxX, y: cropRect.maxY)
            }
        }
    }

    private var moveGesture: some Gesture {
        DragGesture()
            .onChanged { value in
                guard let currentRect = rect?.standardized else {
                    return
                }
                let startRect = moveStartRect ?? currentRect
                moveStartRect = startRect
                rect = startRect
                    .offsetBy(dx: value.translation.width, dy: value.translation.height)
                    .clamped(to: bounds, minSize: minSize)
            }
            .onEnded { _ in
                moveStartRect = nil
            }
    }
}

private enum CropCorner {
    case topLeft
    case topRight
    case bottomLeft
    case bottomRight
}

private struct CropHandle: View {
    let corner: CropCorner
    @Binding var rect: CGRect?
    let bounds: CGRect
    let minSize: CGFloat

    @State private var resizeStartRect: CGRect?

    var body: some View {
        Circle()
            .fill(.yellow)
            .overlay {
                Circle()
                    .stroke(.white, lineWidth: 2)
            }
            .frame(width: 22, height: 22)
            .contentShape(Circle())
            .gesture(
                DragGesture()
                    .onChanged { value in
                        guard let currentRect = rect?.standardized else {
                            return
                        }
                        let startRect = resizeStartRect ?? currentRect
                        resizeStartRect = startRect
                        rect = resizedRect(
                            from: startRect,
                            translation: value.translation
                        ).clamped(to: bounds, minSize: minSize)
                    }
                    .onEnded { _ in
                        resizeStartRect = nil
                    }
            )
    }

    private func resizedRect(from startRect: CGRect, translation: CGSize) -> CGRect {
        var minX = startRect.minX
        var minY = startRect.minY
        var maxX = startRect.maxX
        var maxY = startRect.maxY

        switch corner {
        case .topLeft:
            minX = (startRect.minX + translation.width).clamped(to: bounds.minX...(startRect.maxX - minSize))
            minY = (startRect.minY + translation.height).clamped(to: bounds.minY...(startRect.maxY - minSize))
        case .topRight:
            maxX = (startRect.maxX + translation.width).clamped(to: (startRect.minX + minSize)...bounds.maxX)
            minY = (startRect.minY + translation.height).clamped(to: bounds.minY...(startRect.maxY - minSize))
        case .bottomLeft:
            minX = (startRect.minX + translation.width).clamped(to: bounds.minX...(startRect.maxX - minSize))
            maxY = (startRect.maxY + translation.height).clamped(to: (startRect.minY + minSize)...bounds.maxY)
        case .bottomRight:
            maxX = (startRect.maxX + translation.width).clamped(to: (startRect.minX + minSize)...bounds.maxX)
            maxY = (startRect.maxY + translation.height).clamped(to: (startRect.minY + minSize)...bounds.maxY)
        }

        return CGRect(x: minX, y: minY, width: maxX - minX, height: maxY - minY)
    }
}

private extension CGRect {
    func clamped(to bounds: CGRect, minSize: CGFloat) -> CGRect {
        guard bounds.width > 0, bounds.height > 0 else {
            return self
        }

        let width = Swift.min(Swift.max(self.width, minSize), bounds.width)
        let height = Swift.min(Swift.max(self.height, minSize), bounds.height)
        let minX = bounds.minX
        let minY = bounds.minY
        let maxX = bounds.maxX - width
        let maxY = bounds.maxY - height
        return CGRect(
            x: origin.x.clamped(to: minX...Swift.max(minX, maxX)),
            y: origin.y.clamped(to: minY...Swift.max(minY, maxY)),
            width: width,
            height: height
        )
    }
}

private extension CGFloat {
    func clamped(to range: ClosedRange<CGFloat>) -> CGFloat {
        Swift.max(range.lowerBound, Swift.min(range.upperBound, self))
    }
}
