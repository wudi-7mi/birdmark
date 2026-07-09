import SwiftUI

struct RootView: View {
    @EnvironmentObject private var authStore: AuthStore

    var body: some View {
        Group {
            switch authStore.state {
            case .restoring:
                VStack(spacing: 14) {
                    ProgressView()
                    Text("正在恢复登录")
                        .foregroundStyle(.secondary)
                }
            case .signedOut:
                AuthView()
            case .signedIn:
                MainTabView()
            }
        }
        .animation(.easeInOut(duration: 0.2), value: authStore.state)
    }
}
