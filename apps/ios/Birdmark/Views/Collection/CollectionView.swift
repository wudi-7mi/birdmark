import SwiftUI

struct CollectionView: View {
    @State private var entries: [CollectionEntry] = []
    @State private var isLoading = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            Group {
                if isLoading && entries.isEmpty {
                    ProgressView("加载我的图鉴")
                } else if let errorMessage, entries.isEmpty {
                    LoadingStateView(
                        title: "图鉴加载失败",
                        message: errorMessage,
                        systemImage: "exclamationmark.triangle",
                        retryTitle: "重试",
                        retryAction: { Task { await loadCollection() } }
                    )
                } else if entries.isEmpty {
                    LoadingStateView(
                        title: "图鉴为空",
                        message: "确认上传照片中的鸟类后，物种会进入我的图鉴。",
                        systemImage: "leaf"
                    )
                } else {
                    List(entries) { entry in
                        HStack(spacing: 12) {
                            RemoteImageView(
                                url: APIClient.shared.mediaURL(from: entry.cropUrl ?? entry.thumbUrl),
                                size: CGSize(width: 68, height: 68)
                            )

                            VStack(alignment: .leading, spacing: 4) {
                                Text(entry.displayName)
                                    .font(.headline)
                                    .lineLimit(1)
                                if let scientificName = entry.scientificName {
                                    Text(scientificName)
                                        .font(.subheadline)
                                        .foregroundStyle(.secondary)
                                        .lineLimit(1)
                                }
                                Text("\(entry.observationCount ?? 0) 次观察")
                                    .font(.caption)
                                    .foregroundStyle(.secondary)
                            }
                        }
                        .padding(.vertical, 4)
                    }
                    .listStyle(.plain)
                    .refreshable {
                        await loadCollection()
                    }
                }
            }
            .navigationTitle("我的图鉴")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await loadCollection() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(isLoading)
                }
            }
            .task {
                if entries.isEmpty {
                    await loadCollection()
                }
            }
        }
    }

    private func loadCollection() async {
        isLoading = true
        errorMessage = nil
        do {
            let response: CollectionListResponse = try await APIClient.shared.get("/me/collection")
            entries = response.results
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoading = false
    }
}
