import PhotosUI
import SwiftUI
import UIKit

struct UploadView: View {
    @State private var navigationPath = NavigationPath()
    @State private var uploadMode: UploadMode = .automatic
    @State private var selectedItem: PhotosPickerItem?
    @State private var imageData: Data?
    @State private var previewImage: UIImage?
    @State private var isShowingManualEditor = false
    @State private var isUploading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack(path: $navigationPath) {
            ScrollView {
                VStack(alignment: .leading, spacing: 18) {
                    if let previewImage {
                        SelectedPhotoHeader(selectedItem: $selectedItem, isDisabled: isUploading)

                        Picker("识别方式", selection: $uploadMode) {
                            ForEach(UploadMode.allCases) { mode in
                                Text(mode.title).tag(mode)
                            }
                        }
                        .pickerStyle(.segmented)
                        .disabled(isUploading)

                        PhotosPicker(selection: $selectedItem, matching: .images) {
                            PhotoSelectionArea(previewImage: previewImage)
                        }
                        .buttonStyle(.plain)
                        .disabled(isUploading)
                    } else {
                        PhotosPicker(selection: $selectedItem, matching: .images) {
                            PhotoSelectionArea(previewImage: nil)
                        }
                        .buttonStyle(.plain)
                        .disabled(isUploading)
                    }

                    if let errorMessage {
                        Text(errorMessage)
                            .foregroundStyle(.red)
                    }

                    if previewImage != nil {
                        Button {
                            if uploadMode == .manual {
                                isShowingManualEditor = true
                            } else {
                                Task { await uploadAutomatic() }
                            }
                        } label: {
                            HStack {
                                if isUploading {
                                    ProgressView()
                                }
                                Text(isUploading ? uploadMode.progressTitle : uploadMode.actionTitle)
                            }
                            .frame(maxWidth: .infinity)
                        }
                        .buttonStyle(.borderedProminent)
                        .disabled(!canSubmit || isUploading)
                    }
                }
                .padding()
            }
            .navigationTitle("上传")
            .navigationDestination(for: Int.self) { photoID in
                PhotoDetailView(photoID: photoID)
            }
            .onChange(of: selectedItem) { _, newItem in
                Task {
                    await loadSelectedImage(from: newItem)
                }
            }
            .onChange(of: uploadMode) { _, _ in
                errorMessage = nil
            }
            .fullScreenCover(isPresented: $isShowingManualEditor) {
                if let previewImage {
                    ManualBoxEditorView(
                        image: previewImage,
                        pixelSize: selectedImagePixelSize,
                        onCancel: {
                            isShowingManualEditor = false
                        },
                        onConfirm: { request in
                            try await uploadManual(request: request)
                        }
                    )
                }
            }
        }
    }

    private var canSubmit: Bool {
        imageData != nil
    }

    private var selectedImagePixelSize: CGSize? {
        guard let previewImage else {
            return nil
        }
        return CGSize(
            width: previewImage.size.width * previewImage.scale,
            height: previewImage.size.height * previewImage.scale
        )
    }

    private func loadSelectedImage(from item: PhotosPickerItem?) async {
        errorMessage = nil
        guard let item else {
            imageData = nil
            previewImage = nil
            return
        }

        do {
            guard let data = try await item.loadTransferable(type: Data.self) else {
                throw APIError.transport("无法读取所选图片")
            }
            imageData = data
            previewImage = UIImage(data: data)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func uploadAutomatic() async {
        guard let imageData else {
            return
        }
        isUploading = true
        defer { isUploading = false }
        errorMessage = nil
        do {
            let response = try await APIClient.shared.uploadPhoto(
                imageData: imageData,
                autoAnalyze: true
            )
            navigationPath.append(response.photo.id)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func uploadManual(request: ManualObservationRequest) async throws {
        guard let imageData else {
            throw APIError.transport("无法读取所选图片")
        }

        let response = try await APIClient.shared.uploadPhoto(
            imageData: imageData,
            autoAnalyze: false
        )
        let _: ObservationResponse = try await APIClient.shared.createManualObservation(
            photoID: response.photo.id,
            request: request
        )
        isShowingManualEditor = false
        navigationPath.append(response.photo.id)
    }
}

private enum UploadMode: String, CaseIterable, Identifiable {
    case automatic
    case manual

    var id: String {
        rawValue
    }

    var title: String {
        switch self {
        case .automatic:
            return "自动框选"
        case .manual:
            return "手动框选"
        }
    }

    var actionTitle: String {
        switch self {
        case .automatic:
            return "上传并识别"
        case .manual:
            return "框选并识别"
        }
    }

    var progressTitle: String {
        switch self {
        case .automatic:
            return "上传识别中"
        case .manual:
            return "选区识别中"
        }
    }
}

private struct SelectedPhotoHeader: View {
    @Binding var selectedItem: PhotosPickerItem?
    let isDisabled: Bool

    var body: some View {
        HStack {
            Text("已选择照片")
                .font(.headline)
            Spacer()
            PhotosPicker(selection: $selectedItem, matching: .images) {
                Label("更换", systemImage: "photo.on.rectangle")
            }
            .buttonStyle(.bordered)
            .disabled(isDisabled)
        }
    }
}

private struct PhotoSelectionArea: View {
    let previewImage: UIImage?

    var body: some View {
        ZStack {
            RoundedRectangle(cornerRadius: 12)
                .fill(.background)

            RoundedRectangle(cornerRadius: 12)
                .stroke(
                    .secondary.opacity(0.55),
                    style: StrokeStyle(lineWidth: 1.5, dash: [8, 6])
                )

            if let previewImage {
                Image(uiImage: previewImage)
                    .resizable()
                    .scaledToFit()
                    .padding(10)
            } else {
                VStack(spacing: 12) {
                    Image(systemName: "photo.badge.plus")
                        .font(.system(size: 42, weight: .regular))
                        .foregroundStyle(.secondary)

                    Text("选择照片")
                        .font(.headline)
                        .foregroundStyle(.primary)

                    Text("点击此区域从系统相册选择")
                        .font(.subheadline)
                        .foregroundStyle(.secondary)
                }
                .multilineTextAlignment(.center)
                .padding()
            }
        }
        .frame(maxWidth: .infinity)
        .frame(height: 320)
        .contentShape(RoundedRectangle(cornerRadius: 12))
    }
}
