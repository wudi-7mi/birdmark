import SwiftUI

struct PhotoDetailView: View {
    @Environment(\.dismiss) private var dismiss
    @EnvironmentObject private var authStore: AuthStore
    let photoID: Int

    @State private var detail: PhotoDetailResponse?
    @State private var isLoading = false
    @State private var actionObservationID: Int?
    @State private var isBatchCollecting = false
    @State private var isShowingOriginalPhoto = false
    @State private var isShowingCollectionPrompt = false
    @State private var editingObservation: BirdObservation?
    @State private var errorMessage: String?

    var body: some View {
        ScrollView {
            if isLoading && detail == nil {
                ProgressView("加载照片详情")
                    .frame(maxWidth: .infinity, minHeight: 260)
            } else if let errorMessage, detail == nil {
                LoadingStateView(
                    title: "详情加载失败",
                    message: errorMessage,
                    systemImage: "exclamationmark.triangle",
                    retryTitle: "重试",
                    retryAction: { Task { await loadDetail() } }
                )
                .frame(minHeight: 360)
            } else if let detail {
                VStack(alignment: .leading, spacing: 18) {
                    DetectedPhotoView(detail: detail) {
                        isShowingOriginalPhoto = true
                    }

                    VStack(alignment: .leading, spacing: 8) {
                        Text(detail.photo.displayTitle)
                            .font(.title3.weight(.semibold))
                        HStack {
                            Text(detail.photo.uploaderName)
                            Spacer()
                            StatusBadge(text: detail.photo.status ?? "unknown")
                        }
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                    }
                    .padding(.horizontal)

                    ForEach(detail.observations) { observation in
                        ObservationCardView(
                            observation: observation,
                            canEdit: detail.photo.userId == authStore.currentUser?.id,
                            isWorking: actionObservationID == observation.id,
                            toggleCollection: {
                                Task {
                                    await setCollected(
                                        observationID: observation.id,
                                        collected: !observation.isCollected
                                    )
                                }
                            },
                            edit: {
                                editingObservation = observation
                            }
                        )
                    }
                }
                .padding(.vertical)
            }
        }
        .navigationTitle("照片详情")
        .navigationBarTitleDisplayMode(.inline)
        .navigationBarBackButtonHidden(true)
        .toolbar {
            ToolbarItem(placement: .topBarLeading) {
                Button {
                    handleBack()
                } label: {
                    Label("返回", systemImage: "chevron.left")
                }
                .disabled(isBatchCollecting)
            }
            ToolbarItem(placement: .topBarTrailing) {
                Button {
                    Task { await loadDetail() }
                } label: {
                    Image(systemName: "arrow.clockwise")
                }
                .disabled(isLoading)
            }
        }
        .task {
            await loadDetail()
        }
        .alert("操作失败", isPresented: .constant(errorMessage != nil && detail != nil)) {
            Button("确定") {
                errorMessage = nil
            }
        } message: {
            Text(errorMessage ?? "")
        }
        .alert("还没有加入图鉴", isPresented: $isShowingCollectionPrompt) {
            Button("留在此页", role: .cancel) {}
            Button("暂不添加") {
                dismiss()
            }
            Button("添加到图鉴") {
                Task { await collectRemainingAndDismiss() }
            }
        } message: {
            Text("这张照片已有可收藏的鉴定结果，但还没有收藏任何观察。是否将可收藏观察加入我的图鉴？")
        }
        .overlay {
            if isBatchCollecting {
                ProgressView("加入图鉴中")
                    .padding()
                    .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
            }
        }
        .fullScreenCover(isPresented: $isShowingOriginalPhoto) {
            if let detail {
                OriginalPhotoViewerView(
                    imageURL: APIClient.shared.mediaURL(from: detail.photo.originalUrl),
                    onClose: {
                        isShowingOriginalPhoto = false
                    }
                )
            }
        }
        .sheet(item: $editingObservation) { observation in
            IdentificationEditSheet(
                observation: observation,
                isWorking: actionObservationID == observation.id,
                selectPrediction: { index in
                    if await confirm(observationID: observation.id, predictionIndex: index) {
                        editingObservation = nil
                    }
                }
            )
            .presentationDetents([.medium, .large])
            .presentationDragIndicator(.visible)
        }
    }

    private func loadDetail() async {
        isLoading = true
        errorMessage = nil
        do {
            let response: PhotoDetailResponse = try await APIClient.shared.get("/photos/\(photoID)")
            detail = response
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }

    private func confirm(observationID: Int, predictionIndex: Int) async -> Bool {
        actionObservationID = observationID
        defer { actionObservationID = nil }
        do {
            let _: ConfirmObservationResponse = try await APIClient.shared.postJSON(
                "/observations/\(observationID)/confirm",
                body: ConfirmObservationRequest(predictionIndex: predictionIndex)
            )
            await loadDetail()
            return true
        } catch {
            errorMessage = error.localizedDescription
            return false
        }
    }

    private func setCollected(observationID: Int, collected: Bool) async {
        actionObservationID = observationID
        defer { actionObservationID = nil }
        do {
            let action = collected ? "collect" : "uncollect"
            let _: ConfirmObservationResponse = try await APIClient.shared.postEmpty(
                "/observations/\(observationID)/\(action)"
            )
            await loadDetail()
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func handleBack() {
        if shouldPromptBeforeLeaving {
            isShowingCollectionPrompt = true
        } else {
            dismiss()
        }
    }

    private var shouldPromptBeforeLeaving: Bool {
        guard
            let detail,
            detail.photo.userId == authStore.currentUser?.id,
            detail.observations.contains(where: { $0.canBeCollected }),
            !detail.observations.contains(where: { $0.isCollected })
        else {
            return false
        }
        return true
    }

    private func collectRemainingAndDismiss() async {
        guard let detail else {
            dismiss()
            return
        }

        let observationIDs = detail.observations
            .filter { !$0.isCollected && $0.canBeCollected }
            .map(\.id)
        guard !observationIDs.isEmpty else {
            dismiss()
            return
        }

        isBatchCollecting = true
        defer { isBatchCollecting = false }
        do {
            for observationID in observationIDs {
                let _: ConfirmObservationResponse = try await APIClient.shared.postEmpty(
                    "/observations/\(observationID)/collect"
                )
            }
            await loadDetail()
            dismiss()
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct DetectedPhotoView: View {
    let detail: PhotoDetailResponse
    let openOriginal: () -> Void
    private let displayHeight: CGFloat = 360

    var body: some View {
        AsyncImage(url: APIClient.shared.mediaURL(from: detail.photo.originalUrl)) { phase in
            switch phase {
            case .success(let image):
                GeometryReader { geometry in
                    ZStack {
                        image
                            .resizable()
                            .scaledToFill()
                            .frame(width: geometry.size.width, height: geometry.size.height)
                            .blur(radius: 22)
                            .scaleEffect(1.08)
                            .clipped()

                        Rectangle()
                            .fill(.ultraThinMaterial)
                            .opacity(0.28)

                        image
                            .resizable()
                            .scaledToFit()
                            .frame(width: geometry.size.width, height: geometry.size.height)
                            .clipped()

                        DetectionOverlay(photo: detail.photo, observations: detail.observations)
                            .frame(width: geometry.size.width, height: geometry.size.height)
                    }
                }
                .frame(maxWidth: .infinity)
                .frame(height: displayHeight)
            case .empty:
                Rectangle()
                    .fill(.quaternary)
                    .frame(height: displayHeight)
                    .overlay { ProgressView() }
            case .failure:
                Rectangle()
                    .fill(.quaternary)
                    .frame(height: displayHeight)
                    .overlay {
                        Image(systemName: "photo")
                            .font(.largeTitle)
                            .foregroundStyle(.secondary)
                    }
            @unknown default:
                Rectangle()
                    .fill(.quaternary)
                    .frame(height: displayHeight)
            }
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
        .overlay(alignment: .topTrailing) {
            Image(systemName: "arrow.up.left.and.arrow.down.right")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.white)
                .padding(9)
                .background(.ultraThinMaterial, in: Circle())
                .padding(10)
        }
        .contentShape(RoundedRectangle(cornerRadius: 8))
        .onTapGesture(perform: openOriginal)
        .padding(.horizontal)
    }
}

private struct DetectionOverlay: View {
    let photo: BirdmarkPhoto
    let observations: [BirdObservation]

    var body: some View {
        GeometryReader { geometry in
            ForEach(observations) { observation in
                if let rect = rect(for: observation, in: geometry.size) {
                    Rectangle()
                        .stroke(.yellow, lineWidth: 2)
                        .background(.yellow.opacity(0.08))
                        .frame(width: rect.width, height: rect.height)
                        .offset(x: rect.minX, y: rect.minY)
                }
            }
        }
    }

    private func rect(for observation: BirdObservation, in size: CGSize) -> CGRect? {
        guard
            let imageWidth = photo.width,
            let imageHeight = photo.height,
            imageWidth > 0,
            imageHeight > 0,
            let x1 = observation.bboxX1,
            let y1 = observation.bboxY1,
            let x2 = observation.bboxX2,
            let y2 = observation.bboxY2
        else {
            return nil
        }

        let imageRect = aspectFitRect(
            imageSize: CGSize(width: imageWidth, height: imageHeight),
            in: size
        )
        let scaleX = imageRect.width / CGFloat(imageWidth)
        let scaleY = imageRect.height / CGFloat(imageHeight)
        return CGRect(
            x: imageRect.minX + CGFloat(x1) * scaleX,
            y: imageRect.minY + CGFloat(y1) * scaleY,
            width: CGFloat(max(1, x2 - x1)) * scaleX,
            height: CGFloat(max(1, y2 - y1)) * scaleY
        )
    }

    private func aspectFitRect(imageSize: CGSize, in containerSize: CGSize) -> CGRect {
        guard
            imageSize.width > 0,
            imageSize.height > 0,
            containerSize.width > 0,
            containerSize.height > 0
        else {
            return CGRect(origin: .zero, size: containerSize)
        }

        let imageAspectRatio = imageSize.width / imageSize.height
        let containerAspectRatio = containerSize.width / containerSize.height
        if containerAspectRatio > imageAspectRatio {
            let height = containerSize.height
            let width = height * imageAspectRatio
            return CGRect(
                x: (containerSize.width - width) / 2,
                y: 0,
                width: width,
                height: height
            )
        }

        let width = containerSize.width
        let height = width / imageAspectRatio
        return CGRect(
            x: 0,
            y: (containerSize.height - height) / 2,
            width: width,
            height: height
        )
    }
}

private struct ObservationCardView: View {
    let observation: BirdObservation
    let canEdit: Bool
    let isWorking: Bool
    let toggleCollection: () -> Void
    let edit: () -> Void

    var body: some View {
        VStack(alignment: .leading, spacing: 14) {
            HStack(alignment: .top, spacing: 12) {
                ObservationContextPreview(
                    observation: observation,
                    size: CGSize(width: 92, height: 92)
                )

                VStack(alignment: .leading, spacing: 6) {
                    HStack(alignment: .top) {
                        Text("观察 #\(observation.id)")
                            .font(.headline)
                        Spacer()
                        if canEdit {
                            Button {
                                toggleCollection()
                            } label: {
                                if isWorking {
                                    ProgressView()
                                        .controlSize(.small)
                                } else {
                                    Image(systemName: observation.isCollected ? "bookmark.fill" : "bookmark")
                                }
                            }
                            .buttonStyle(.plain)
                            .foregroundStyle(observation.isCollected ? .green : .secondary)
                            .frame(width: 32, height: 32)
                            .contentShape(Rectangle())
                            .disabled(isWorking || (!observation.isCollected && !observation.canBeCollected))
                            .accessibilityLabel(observation.isCollected ? "从图鉴移除" : "加入图鉴")
                        }
                    }
                    if let confidence = observation.detectionConfidence {
                        Text("检测置信度 \(Int((confidence * 100).rounded()))%")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    if let status = observation.identification?.status {
                        Text("鉴定状态：\(status)")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    StatusBadge(text: observation.status ?? "unknown")
                }
            }

            let predictions = observation.identification?.topKResults ?? []
            if predictions.isEmpty {
                Text("暂无 AI 建议")
                    .foregroundStyle(.secondary)
            } else {
                VStack(alignment: .leading, spacing: 8) {
                    ForEach(Array(predictions.prefix(3).enumerated()), id: \.offset) { index, prediction in
                        PredictionRowView(
                            prediction: prediction,
                            index: index
                        )
                    }
                }
            }

            if canEdit {
                Button {
                    edit()
                } label: {
                    Label("修改鉴定", systemImage: "square.and.pencil")
                        .frame(maxWidth: .infinity)
                }
                .buttonStyle(.bordered)
                .disabled(isWorking || predictions.isEmpty)
            }
        }
        .padding()
        .background(.background, in: RoundedRectangle(cornerRadius: 8))
        .overlay(
            RoundedRectangle(cornerRadius: 8)
                .stroke(.quaternary, lineWidth: 1)
        )
        .padding(.horizontal)
    }
}

private struct PredictionRowView: View {
    let prediction: Prediction
    let index: Int

    var body: some View {
        HStack(alignment: .center, spacing: 12) {
            Text("#\(index + 1)")
                .font(.caption.weight(.semibold))
                .foregroundStyle(.secondary)
                .frame(width: 30, alignment: .leading)

            VStack(alignment: .leading, spacing: 2) {
                Text(prediction.scientificDisplayName)
                    .font(.subheadline.weight(.semibold))
                    .italic(prediction.scientificName?.nonEmpty != nil)
                if let secondaryName = prediction.localizedDisplayName {
                    Text(secondaryName)
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }

            Spacer()

            ScoreRingView(value: prediction.scoreValue)
        }
    }
}

private struct ObservationContextPreview: View {
    let observation: BirdObservation
    let size: CGSize

    var body: some View {
        if let contextURL = APIClient.shared.mediaURL(from: observation.contextUrl) {
            ObservationRegionPreview(
                url: contextURL,
                fallbackURL: APIClient.shared.mediaURL(from: observation.cropUrl),
                size: size
            )
        } else {
            ObservationCropPreview(
                url: APIClient.shared.mediaURL(from: observation.cropUrl),
                size: size
            )
        }
    }
}

private struct ObservationRegionPreview: View {
    let url: URL
    let fallbackURL: URL?
    let size: CGSize

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case .empty:
                Rectangle()
                    .fill(.quaternary)
                    .overlay {
                        ProgressView()
                    }
            case .success(let image):
                image
                    .resizable()
                    .scaledToFill()
                    .frame(width: size.width, height: size.height)
                    .clipped()
            case .failure:
                ObservationCropPreview(url: fallbackURL, size: size)
            @unknown default:
                ObservationCropPreview(url: fallbackURL, size: size)
            }
        }
        .frame(width: size.width, height: size.height)
        .background(.black.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.primary.opacity(0.16), lineWidth: 1)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct ObservationCropPreview: View {
    let url: URL?
    let size: CGSize

    var body: some View {
        AsyncImage(url: url) { phase in
            switch phase {
            case .empty:
                Rectangle()
                    .fill(.quaternary)
                    .overlay {
                        ProgressView()
                    }
            case .success(let image):
                image
                    .resizable()
                    .scaledToFit()
                    .padding(4)
            case .failure:
                Rectangle()
                    .fill(.quaternary)
                    .overlay {
                        Image(systemName: "photo")
                            .foregroundStyle(.secondary)
                    }
            @unknown default:
                Rectangle()
                    .fill(.quaternary)
            }
        }
        .frame(width: size.width, height: size.height)
        .background(.black.opacity(0.04), in: RoundedRectangle(cornerRadius: 8))
        .overlay {
            RoundedRectangle(cornerRadius: 8)
                .stroke(.primary.opacity(0.16), lineWidth: 1)
        }
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

private struct IdentificationEditSheet: View {
    let observation: BirdObservation
    let isWorking: Bool
    let selectPrediction: (Int) async -> Void

    var body: some View {
        NavigationStack {
            List {
                Section {
                    HStack(spacing: 12) {
                        ObservationContextPreview(
                            observation: observation,
                            size: CGSize(width: 72, height: 72)
                        )
                        VStack(alignment: .leading, spacing: 4) {
                            Text("观察 #\(observation.id)")
                                .font(.headline)
                            Text("选择一个候选鸟种作为最终鉴定")
                                .font(.subheadline)
                                .foregroundStyle(.secondary)
                        }
                    }
                    .padding(.vertical, 4)
                }

                Section("候选鸟种") {
                    ForEach(Array(predictions.enumerated()), id: \.offset) { index, prediction in
                        Button {
                            Task { await selectPrediction(index) }
                        } label: {
                            HStack(spacing: 12) {
                                VStack(alignment: .leading, spacing: 3) {
                                    Text(prediction.scientificDisplayName)
                                        .font(.body.weight(.semibold))
                                        .italic()
                                        .foregroundStyle(.primary)
                                    if let localizedName = prediction.localizedDisplayName {
                                        Text(localizedName)
                                            .font(.subheadline)
                                            .foregroundStyle(.secondary)
                                    }
                                }
                                Spacer()
                                ScoreRingView(value: prediction.scoreValue)
                            }
                        }
                        .disabled(isWorking)
                    }
                }
            }
            .navigationTitle("修改鉴定")
            .navigationBarTitleDisplayMode(.inline)
            .overlay {
                if isWorking {
                    ProgressView("保存中")
                        .padding()
                        .background(.regularMaterial, in: RoundedRectangle(cornerRadius: 8))
                }
            }
        }
    }

    private var predictions: [Prediction] {
        observation.identification?.topKResults ?? []
    }
}

private struct ScoreRingView: View {
    let value: Double?

    var body: some View {
        ZStack {
            Circle()
                .stroke(.quaternary, lineWidth: 3)
            Circle()
                .trim(from: 0, to: CGFloat(score))
                .stroke(.green, style: StrokeStyle(lineWidth: 3, lineCap: .round))
                .rotationEffect(.degrees(-90))
        }
        .frame(width: 26, height: 26)
        .accessibilityLabel("置信度 \(Int((score * 100).rounded()))%")
    }

    private var score: Double {
        min(1, max(0, value ?? 0))
    }
}

private struct OriginalPhotoViewerView: View {
    let imageURL: URL?
    let onClose: () -> Void

    var body: some View {
        ZStack {
            Color.black.ignoresSafeArea()

            AsyncImage(url: imageURL) { phase in
                switch phase {
                case .success(let image):
                    image
                        .resizable()
                        .scaledToFit()
                        .ignoresSafeArea()
                case .empty:
                    ProgressView()
                        .tint(.white)
                case .failure:
                    Image(systemName: "photo")
                        .font(.largeTitle)
                        .foregroundStyle(.white.secondary)
                @unknown default:
                    EmptyView()
                }
            }

            VStack {
                HStack {
                    Button(action: onClose) {
                        Image(systemName: "xmark")
                            .font(.headline.weight(.semibold))
                            .foregroundStyle(.white)
                            .frame(width: 44, height: 44)
                            .background(.ultraThinMaterial, in: Circle())
                    }
                    .buttonStyle(.plain)
                    Spacer()
                }
                .padding(.horizontal, 18)
                .padding(.top, 14)
                Spacer()
            }
        }
    }
}

private extension BirdmarkPhoto {
    var pixelSize: CGSize? {
        guard
            let width,
            let height,
            width > 0,
            height > 0
        else {
            return nil
        }
        return CGSize(width: width, height: height)
    }
}

private extension Prediction {
    var scientificDisplayName: String {
        scientificName?.nonEmpty ?? label?.nonEmpty ?? "未知物种"
    }

    var localizedDisplayName: String? {
        if let chineseName = chineseName?.nonEmpty {
            return commonName?.nonEmpty.map { "\(chineseName) / \($0)" } ?? chineseName
        }
        return commonName?.nonEmpty
    }

    var scoreValue: Double? {
        score ?? confidence ?? probability ?? similarity
    }
}

private extension String {
    var nonEmpty: String? {
        isEmpty ? nil : self
    }
}
