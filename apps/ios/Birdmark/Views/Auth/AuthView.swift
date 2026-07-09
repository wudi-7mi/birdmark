import SwiftUI

struct AuthView: View {
    @EnvironmentObject private var authStore: AuthStore
    @State private var mode: AuthMode = .login
    @State private var identifier = ""
    @State private var email = ""
    @State private var username = ""
    @State private var displayName = ""
    @State private var password = ""
    @State private var isSubmitting = false

    var body: some View {
        NavigationStack {
            Form {
                Section {
                    Picker("模式", selection: $mode) {
                        Text("登录").tag(AuthMode.login)
                        Text("注册").tag(AuthMode.register)
                    }
                    .pickerStyle(.segmented)
                }

                Section {
                    if mode == .login {
                        TextField("邮箱或用户名", text: $identifier)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                    } else {
                        TextField("邮箱", text: $email)
                            .textContentType(.emailAddress)
                            .keyboardType(.emailAddress)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        TextField("用户名", text: $username)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled()
                        TextField("昵称", text: $displayName)
                    }

                    SecureField("密码", text: $password)
                        .textContentType(mode == .login ? .password : .newPassword)
                }

                if let errorMessage = authStore.errorMessage {
                    Section {
                        Text(errorMessage)
                            .foregroundStyle(.red)
                    }
                }

                Section {
                    Button {
                        submit()
                    } label: {
                        HStack {
                            if isSubmitting {
                                ProgressView()
                            }
                            Text(mode == .login ? "登录" : "注册并登录")
                        }
                    }
                    .disabled(isSubmitting || !canSubmit)
                }
            }
            .navigationTitle("Birdmark")
        }
    }

    private var canSubmit: Bool {
        switch mode {
        case .login:
            return !identifier.isEmpty && !password.isEmpty
        case .register:
            return !email.isEmpty && !username.isEmpty && !displayName.isEmpty && password.count >= 8
        }
    }

    private func submit() {
        isSubmitting = true
        Task {
            switch mode {
            case .login:
                await authStore.login(identifier: identifier, password: password)
            case .register:
                await authStore.register(
                    email: email,
                    username: username,
                    displayName: displayName,
                    password: password
                )
            }
            isSubmitting = false
        }
    }
}

private enum AuthMode {
    case login
    case register
}
