import SwiftUI

struct LoadingStateView: View {
    let title: String
    let message: String?
    let systemImage: String
    var retryTitle: String?
    var retryAction: (() -> Void)?

    var body: some View {
        ContentUnavailableView {
            Label(title, systemImage: systemImage)
        } description: {
            if let message {
                Text(message)
            }
        } actions: {
            if let retryTitle, let retryAction {
                Button(retryTitle, action: retryAction)
                    .buttonStyle(.borderedProminent)
            }
        }
    }
}
