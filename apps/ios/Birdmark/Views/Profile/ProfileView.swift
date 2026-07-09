import SwiftUI

struct ProfileView: View {
    @EnvironmentObject private var authStore: AuthStore
    @State private var myPhotos: [BirdmarkPhoto] = []
    @State private var isLoadingPhotos = false
    @State private var errorMessage: String?

    var body: some View {
        NavigationStack {
            List {
                if let user = authStore.currentUser {
                    Section("账号") {
                        LabeledContent("昵称", value: user.displayName)
                        LabeledContent("用户名", value: user.username)
                        LabeledContent("邮箱", value: user.email)
                    }
                }

                Section("设置") {
                    NavigationLink {
                        AdvancedSettingsView()
                    } label: {
                        Label("高级设置", systemImage: "gearshape.2")
                    }
                }

                Section("我的上传") {
                    if isLoadingPhotos && myPhotos.isEmpty {
                        ProgressView()
                    } else if myPhotos.isEmpty {
                        Text("暂无上传")
                            .foregroundStyle(.secondary)
                    } else {
                        ForEach(myPhotos) { photo in
                            NavigationLink {
                                PhotoDetailView(photoID: photo.id)
                            } label: {
                                HStack(spacing: 12) {
                                    RemoteImageView(
                                        url: APIClient.shared.mediaURL(from: photo.thumbUrl),
                                        size: CGSize(width: 54, height: 54)
                                    )
                                    VStack(alignment: .leading, spacing: 4) {
                                        Text(photo.displayTitle)
                                            .lineLimit(1)
                                        StatusBadge(text: photo.status ?? "unknown")
                                    }
                                }
                            }
                            .swipeActions {
                                Button(role: .destructive) {
                                    Task { await deletePhoto(photo.id) }
                                } label: {
                                    Label("删除", systemImage: "trash")
                                }
                            }
                        }
                    }
                }

                if let errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(.red)
                    }
                }

                Section {
                    Button(role: .destructive) {
                        Task { await authStore.logout() }
                    } label: {
                        Label("退出登录", systemImage: "rectangle.portrait.and.arrow.right")
                    }
                }
            }
            .navigationTitle("我的")
            .toolbar {
                ToolbarItem(placement: .topBarTrailing) {
                    Button {
                        Task { await loadMyPhotos() }
                    } label: {
                        Image(systemName: "arrow.clockwise")
                    }
                    .disabled(isLoadingPhotos)
                }
            }
            .refreshable {
                await loadMyPhotos()
            }
            .task {
                if myPhotos.isEmpty {
                    await loadMyPhotos()
                }
            }
        }
    }

    private func loadMyPhotos() async {
        isLoadingPhotos = true
        errorMessage = nil
        do {
            let response: MyPhotoListResponse = try await APIClient.shared.get(
                "/me/photos",
                queryItems: [
                    URLQueryItem(name: "limit", value: "50"),
                    URLQueryItem(name: "offset", value: "0")
                ]
            )
            myPhotos = response.results
        } catch {
            errorMessage = error.localizedDescription
        }
        isLoadingPhotos = false
    }

    private func deletePhoto(_ photoID: Int) async {
        do {
            let _: StatusResponse = try await APIClient.shared.delete("/photos/\(photoID)")
            myPhotos.removeAll { $0.id == photoID }
        } catch {
            errorMessage = error.localizedDescription
        }
    }
}

private struct AdvancedSettingsView: View {
    @State private var serverMode: ServerMode
    @State private var customServerURL: String
    @State private var errorMessage: String?
    @State private var savedMessage: String?

    init() {
        let currentURL = AppConfig.apiBaseURLString
        let mode: ServerMode = currentURL == AppConfig.defaultAPIBaseURLString ? .defaultServer : .custom
        _serverMode = State(initialValue: mode)
        _customServerURL = State(initialValue: currentURL)
    }

    var body: some View {
        Form {
            Section("服务器") {
                Picker("服务器", selection: $serverMode) {
                    ForEach(ServerMode.allCases) { mode in
                        Text(mode.title).tag(mode)
                    }
                }
                .pickerStyle(.segmented)

                LabeledContent("当前地址", value: AppConfig.apiBaseURLString)

                if serverMode == .defaultServer {
                    LabeledContent("默认地址", value: AppConfig.defaultAPIBaseURLString)
                } else {
                    TextField("服务器地址", text: $customServerURL)
                        .keyboardType(.URL)
                        .textInputAutocapitalization(.never)
                        .autocorrectionDisabled()
                }
            }

            if let errorMessage {
                Section {
                    Text(errorMessage)
                        .foregroundStyle(.red)
                }
            }

            if let savedMessage {
                Section {
                    Text(savedMessage)
                        .foregroundStyle(.green)
                }
            }

            Section {
                Button {
                    save()
                } label: {
                    Label("保存", systemImage: "checkmark.circle")
                }

                Button {
                    resetDefault()
                } label: {
                    Label("恢复默认服务器", systemImage: "arrow.counterclockwise")
                }
            }
        }
        .navigationTitle("高级设置")
        .navigationBarTitleDisplayMode(.inline)
    }

    private func save() {
        errorMessage = nil
        savedMessage = nil

        switch serverMode {
        case .defaultServer:
            AppConfig.resetAPIBaseURL()
            customServerURL = AppConfig.defaultAPIBaseURLString
        case .custom:
            guard let url = AppConfig.normalizedURL(from: customServerURL), url.scheme != nil, url.host != nil else {
                errorMessage = "服务器地址无效"
                return
            }
            AppConfig.apiBaseURL = url
            customServerURL = AppConfig.apiBaseURLString
        }

        savedMessage = "已保存"
    }

    private func resetDefault() {
        serverMode = .defaultServer
        AppConfig.resetAPIBaseURL()
        customServerURL = AppConfig.defaultAPIBaseURLString
        errorMessage = nil
        savedMessage = "已恢复默认服务器"
    }
}

private enum ServerMode: String, CaseIterable, Identifiable {
    case defaultServer
    case custom

    var id: String {
        rawValue
    }

    var title: String {
        switch self {
        case .defaultServer:
            return "默认"
        case .custom:
            return "自定义"
        }
    }
}
