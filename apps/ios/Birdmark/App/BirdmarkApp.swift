import SwiftUI

@main
struct BirdmarkApp: App {
    @StateObject private var authStore = AuthStore()

    var body: some Scene {
        WindowGroup {
            RootView()
                .environmentObject(authStore)
                .task {
                    await authStore.restoreSession()
                }
        }
    }
}
