import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var state: AppState
    @State private var email = ""
    @State private var password = ""

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [
                    Color(red: 0.96, green: 0.88, blue: 0.85),
                    Color(red: 0.93, green: 0.78, blue: 0.74)
                ],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            VStack {
                Spacer(minLength: 34)

                VStack(spacing: 36) {
                    VStack(spacing: 30) {
                        VStack(spacing: 16) {
                            Text("裝識你的美")
                                .font(.system(size: 42, weight: .regular, design: .serif))
                                .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))

                            Text("Log in to continue your beauty journey")
                                .font(.system(size: 14, weight: .light, design: .rounded))
                                .tracking(5)
                                .foregroundStyle(Color(red: 0.62, green: 0.42, blue: 0.39))
                        }

                        LuxuryTextField(
                            title: "電子郵件",
                            placeholder: "your@email.com",
                            text: $email
                        )
                    }
                    .padding(.top, 48)
                    .offset(y: 14)

                    LuxuryTextField(
                        title: "密碼",
                        placeholder: "••••••••",
                        text: $password,
                        secure: true
                    )
                    .padding(.top, 18)

                    VStack(spacing: 18) {
                        Button {
                            state.login(name: email.isEmpty ? "會員" : email, guest: false)
                        } label: {
                            LuxuryButtonText("登    入")
                        }

                        Button {
                            state.login(name: "訪客", guest: true)
                        } label: {
                            LuxuryButtonText("訪客登入")
                        }
                    }
                    .padding(.top, 22)

                    VStack(spacing: 24) {
                        Button("忘記密碼？") { }
                        Button("還沒有帳號？立即註冊") { }
                    }
                    .font(.system(size: 15, weight: .light))
                    .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))
                    .padding(.top, 8)

                    Spacer(minLength: 26)
                }
                .padding(.horizontal, 42)
                .frame(maxWidth: .infinity)
                .frame(height: 650)
                .background(
                    RoundedRectangle(cornerRadius: 34, style: .continuous)
                        .fill(Color.white.opacity(0.28))
                        .blur(radius: 0.2)
                )
                .overlay(
                    RoundedRectangle(cornerRadius: 34, style: .continuous)
                        .stroke(Color.white.opacity(0.78), lineWidth: 1.4)
                )
                .shadow(color: Color(red: 0.30, green: 0.15, blue: 0.12).opacity(0.15), radius: 34, x: 0, y: 20)
                .padding(.horizontal, 16)

                Spacer(minLength: 34)
            }
        }
    }
}

struct LuxuryTextField: View {
    let title: String
    let placeholder: String
    @Binding var text: String
    var secure: Bool = false

    var body: some View {
        VStack(alignment: .leading, spacing: 16) {
            Text(title)
                .font(.system(size: 15, weight: .light))
                .tracking(3)
                .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))

            Group {
                if secure {
                    SecureField(placeholder, text: $text)
                } else {
                    TextField(placeholder, text: $text)
                        .keyboardType(.emailAddress)
                        .textInputAutocapitalization(.never)
                }
            }
            .font(.system(size: 22, weight: .light, design: .serif))
            .foregroundStyle(Color(red: 0.30, green: 0.20, blue: 0.20))
            .tint(Color(red: 0.70, green: 0.43, blue: 0.39))
            .textFieldStyle(.plain)
            .padding(.bottom, 14)
            .overlay(alignment: .bottom) {
                Rectangle()
                    .fill(Color(red: 0.72, green: 0.49, blue: 0.45).opacity(0.45))
                    .frame(height: 1)
            }
        }
    }
}

struct LuxuryButtonText: View {
    let title: String

    init(_ title: String) {
        self.title = title
    }

    var body: some View {
        Text(title)
            .font(.system(size: 18, weight: .regular))
            .foregroundStyle(Color(red: 0.30, green: 0.20, blue: 0.20))
            .frame(maxWidth: .infinity)
            .frame(height: 58)
            .background(
                Capsule()
                    .fill(
                        LinearGradient(
                            colors: [
                                Color.white.opacity(0.72),
                                Color(red: 0.98, green: 0.82, blue: 0.72).opacity(0.62)
                            ],
                            startPoint: .topLeading,
                            endPoint: .bottomTrailing
                        )
                    )
            )
            .overlay(
                Capsule()
                    .stroke(Color.white.opacity(0.9), lineWidth: 1.2)
            )
            .shadow(color: Color(red: 0.55, green: 0.30, blue: 0.22).opacity(0.22), radius: 18, x: 0, y: 10)
    }
}
