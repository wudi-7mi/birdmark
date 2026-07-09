import SwiftUI

struct SharedPhotosView: View {
    @State private var photos: [PhotoDetailResponse] = []
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Group {
                if isLoading && photos.isEmpty {
                    ProgressView("加载共享相册")
                } else if let errorMessage, photos.isEmpty {
                    LoadingStateView(
                        title: "相册加载失败",
                        message: errorMessage,
                        systemImage: "exclamationmark.triangle",
                        retryTitle: "重试",
                        retryAction: { Task { await loadPhotos() } }
                    )
                } else if photos.isEmpty {
                    LoadingStateView(
                        title: "暂无照片",
                        message: "登录用户上传的照片会显示在这里。",
                        systemImage: "photo.on.rectangle"
                    )
                } else {
                    List(photos) { detail in
                        NavigationLink(value: detail.photo.id) {
                            PhotoRowView(detail: detail)
                        }
                    }
                    .listStyle(.plain)
                    .refreshable {
                        await loadPhotos()
                    }
                }
            }
            .navigationTitle("共享相册")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await loadPhotos() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(isLoading)
                }
            }
            .navigationDestination(for: Int.self) { photoID in
                PhotoDetailView(photoID: photoID)
            }
            .task {
                if photos.isEmpty {
                    await loadPhotos()
                }
            }
        }
    }

    private func loadPhotos() async {
        isLoading = true
        errorMessage = nil
        do {
            let response: PhotoListResponse = try await APIClient.shared.get(
                "/photos",
                queryItems: [
                    URLQueryItem(name: "limit", value: "50"),
                    URLQueryItem(name: "offset", value: "0")
                ]
            )
            photos = response.results
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}

private struct PhotoRowView: View {
    let detail: PhotoDetailResponse

    var body: some View {
        HStack(spacing: 12) {
            RemoteImageView(url: APIClient.shared.mediaURL(from: detail.photo.thumbUrl), size: CGSize(width: 78, height: 78))

            VStack(alignment: .leading, spacing: 6) {
                Text(detail.photo.displayTitle)
                    .font(.headline)
                    .lineLimit(1)
                Text(detail.photo.uploaderName)
                    .font(.subheadline)
                    .foregroundStyle(.secondary)
                    .lineLimit(1)
                HStack(spacing: 8) {
                    StatusBadge(text: detail.photo.status ?? "unknown")
                    Text("\(detail.observations.count) 条观察")
                        .font(.caption)
                        .foregroundStyle(.secondary)
                }
            }
        }
        .padding(.vertical, 4)
    }
}

struct RemoteImageView: View {
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
                    .scaledToFill()
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
        .clipShape(RoundedRectangle(cornerRadius: 8))
    }
}

struct StatusBadge: View {
    let text: String

    var body: some View {
        Text(displayText)
            .font(.caption.weight(.semibold))
            .padding(.horizontal, 8)
            .padding(.vertical, 4)
            .background(color.opacity(0.16), in: Capsule())
            .foregroundStyle(color)
    }

    private var displayText: String {
        switch text {
        case "ready":
            return "完成"
        case "processing":
            return "识别中"
        case "failed":
            return "失败"
        case "deleted":
            return "已删除"
        default:
            return text
        }
    }

    private var color: Color {
        switch text {
        case "ready":
            return .green
        case "processing":
            return .orange
        case "failed":
            return .red
        default:
            return .secondary
        }
    }
}
