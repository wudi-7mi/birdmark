import Foundation
import SwiftUI

@MainActor
final class AuthStore: ObservableObject {
    enum SessionState: Equatable {
        case restoring
        case signedOut
        case signedIn
    }

    @Published private(set) var state: SessionState = .restoring
    @Published private(set) var currentUser: BirdmarkUser?
    @Published var errorMessage: String?

    private let keychain = KeychainStore()
    private let apiClient = APIClient.shared

    func restoreSession() async {
        guard state == .restoring else {
            return
        }

        guard let token = keychain.read() else {
            state = .signedOut
            return
        }

        apiClient.accessToken = token
        do {
            let response: CurrentUserResponse = try await apiClient.get("/auth/me")
            currentUser = response.user
            state = .signedIn
        } catch {
            keychain.delete()
            apiClient.accessToken = nil
            currentUser = nil
            state = .signedOut
        }
    }

    func login(identifier: String, password: String) async {
        errorMessage = nil
        do {
            let response: AuthResponse = try await apiClient.postJSON(
                "/auth/login",
                body: LoginRequest(identifier: identifier, password: password)
            )
            try apply(authResponse: response)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func register(email: String, username: String, displayName: String, password: String) async {
        errorMessage = nil
        do {
            let response: AuthResponse = try await apiClient.postJSON(
                "/auth/register",
                body: RegisterRequest(
                    email: email,
                    username: username,
                    password: password,
                    displayName: displayName
                )
            )
            try apply(authResponse: response)
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    func logout() async {
        let _: StatusResponse? = try? await apiClient.postEmpty("/auth/logout")
        keychain.delete()
        apiClient.accessToken = nil
        currentUser = nil
        state = .signedOut
    }

    private func apply(authResponse: AuthResponse) throws {
        try keychain.save(authResponse.accessToken)
        apiClient.accessToken = authResponse.accessToken
        currentUser = authResponse.user
        state = .signedIn
    }
}
