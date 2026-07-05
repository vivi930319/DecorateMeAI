import SwiftUI

struct ForgotPasswordView: View {
    var onBackToLogin: () -> Void

    @State private var step: ForgotStep = .email
    @State private var email = ""
    @State private var code = ""
    @State private var newPassword = ""
    @State private var confirmPassword = ""

    @State private var showDialog = false
    @State private var dialogType: ForgotDialogType = .error
    @State private var dialogMessage = ""

    enum ForgotStep {
        case email
        case verify
        case reset
    }

    enum ForgotDialogType {
        case error
        case success
    }

    var body: some View {
        ZStack {
            background

            VStack {
                Spacer(minLength: 34)

                card

                Spacer(minLength: 34)
            }
            .padding(.horizontal, 16)

            if showDialog {
                dialogOverlay
            }
        }
    }

    private var background: some View {
        LinearGradient(
            colors: [
                Color(red: 0.96, green: 0.88, blue: 0.85),
                Color(red: 0.93, green: 0.78, blue: 0.74)
            ],
            startPoint: .top,
            endPoint: .bottom
        )
        .ignoresSafeArea()
    }

    private var card: some View {
        VStack(spacing: 30) {
            header

            switch step {
            case .email:
                emailPage
            case .verify:
                verifyPage
            case .reset:
                resetPage
            }

            Spacer(minLength: 10)

            Button(step == .email ? "返回登入" : "回上一頁") {
                withAnimation(.easeInOut(duration: 0.25)) {
                    if step == .email {
                        onBackToLogin()
                    } else if step == .verify {
                        step = .email
                    } else {
                        step = .verify
                    }
                }
            }
            .font(.system(size: 15, weight: .light))
            .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))
        }
        .padding(.horizontal, 34)
        .padding(.vertical, 42)
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
    }

    private var header: some View {
        VStack(spacing: 16) {
            Text(titleText)
                .font(.system(size: 42, weight: .regular, design: .serif))
                .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))

            Text(subtitleText)
                .font(.system(size: 15, weight: .light, design: .serif))
                .tracking(3)
                .multilineTextAlignment(.center)
                .foregroundStyle(Color(red: 0.62, green: 0.42, blue: 0.39))
                .lineSpacing(5)
        }
    }

    private var titleText: String {
        switch step {
        case .email:
            return "忘記密碼"
        case .verify:
            return "驗證信箱"
        case .reset:
            return "設定新密碼"
        }
    }

    private var subtitleText: String {
        switch step {
        case .email:
            return "輸入信箱以接收驗證碼"
        case .verify:
            return "已將驗證碼發送至\n\(email)"
        case .reset:
            return "為你的帳號建立新的密碼"
        }
    }

    private var emailPage: some View {
        VStack(spacing: 34) {
            LuxuryTextField(
                title: "電子郵件",
                placeholder: "your@email.com",
                text: $email
            )

            Button {
                sendCode()
            } label: {
                LuxuryButtonText("發 送 驗 證 碼")
            }
        }
        .padding(.top, 44)
    }

    private var verifyPage: some View {
        VStack(spacing: 28) {
            LuxuryTextField(
                title: "驗證碼",
                placeholder: "請輸入驗證碼",
                text: $code
            )

            Button {
                verifyCode()
            } label: {
                LuxuryButtonText("驗    證")
            }

            Button("重新發送驗證碼") {
                code = ""
            }
            .font(.system(size: 15, weight: .light))
            .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))
        }
        .padding(.top, 44)
    }

    private var resetPage: some View {
        VStack(spacing: 28) {
            LuxuryTextField(
                title: "新密碼",
                placeholder: "至少 6 碼",
                text: $newPassword,
                secure: true
            )

            LuxuryTextField(
                title: "確認新密碼",
                placeholder: "再次輸入新密碼",
                text: $confirmPassword,
                secure: true
            )

            Button {
                resetPassword()
            } label: {
                LuxuryButtonText("更 新 密 碼")
            }
            .padding(.top, 16)
        }
        .padding(.top, 36)
    }

    private var dialogOverlay: some View {
        ZStack {
            Color.black.opacity(0.28)
                .ignoresSafeArea()
                .blur(radius: 1)

            VStack(spacing: 26) {
                HStack {
                    Spacer()

                    Button {
                        closeDialog()
                    } label: {
                        Text("×")
                            .font(.system(size: 28, weight: .medium))
                            .foregroundStyle(Color(red: 0.48, green: 0.25, blue: 0.22))
                            .frame(width: 54, height: 54)
                            .background(
                                Circle()
                                    .fill(
                                        LinearGradient(
                                            colors: [
                                                Color.white.opacity(0.88),
                                                Color(red: 0.96, green: 0.82, blue: 0.78).opacity(0.72)
                                            ],
                                            startPoint: .top,
                                            endPoint: .bottom
                                        )
                                    )
                            )
                            .overlay(Circle().stroke(Color.white.opacity(0.95), lineWidth: 1.4))
                            .shadow(color: Color.black.opacity(0.15), radius: 12, x: 0, y: 8)
                    }
                }

                Circle()
                    .fill(dialogType == .success ? Color(red: 0.86, green: 0.91, blue: 0.78) : Color(red: 0.96, green: 0.79, blue: 0.76))
                    .frame(width: 82, height: 82)
                    .overlay(
                        Text(dialogType == .success ? "√" : "!")
                            .font(.system(size: 44, weight: .light, design: .serif))
                            .foregroundStyle(dialogType == .success ? Color(red: 0.23, green: 0.50, blue: 0.33) : Color(red: 0.72, green: 0.23, blue: 0.20))
                    )
                    .overlay(Circle().stroke(Color.white.opacity(0.9), lineWidth: 1.5))

                Text(dialogMessage)
                    .font(.system(size: 25, weight: .regular, design: .serif))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))
                    .lineSpacing(6)
                    .padding(.horizontal, 10)

                Button {
                    if dialogType == .success {
                        closeDialog()
                        onBackToLogin()
                    } else {
                        closeDialog()
                    }
                } label: {
                    Text("確 定")
                        .font(.system(size: 19, weight: .regular))
                        .foregroundStyle(Color(red: 0.35, green: 0.20, blue: 0.20))
                        .frame(width: 190, height: 64)
                        .background(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .fill(
                                    LinearGradient(
                                        colors: [
                                            Color.white.opacity(0.86),
                                            Color(red: 0.98, green: 0.83, blue: 0.72).opacity(0.72)
                                        ],
                                        startPoint: .top,
                                        endPoint: .bottom
                                    )
                                )
                        )
                        .overlay(
                            RoundedRectangle(cornerRadius: 16, style: .continuous)
                                .stroke(Color(red: 0.74, green: 0.42, blue: 0.36).opacity(0.65), lineWidth: 3)
                        )
                        .shadow(color: Color.black.opacity(0.12), radius: 14, x: 0, y: 8)
                }
            }
            .padding(.horizontal, 28)
            .padding(.top, 26)
            .padding(.bottom, 42)
            .frame(maxWidth: .infinity)
            .frame(height: 390)
            .background(
                RoundedRectangle(cornerRadius: 34, style: .continuous)
                    .fill(Color(red: 0.84, green: 0.79, blue: 0.76).opacity(0.94))
            )
            .overlay(
                RoundedRectangle(cornerRadius: 34, style: .continuous)
                    .stroke(Color.white.opacity(0.9), lineWidth: 1.5)
            )
            .shadow(color: Color.black.opacity(0.18), radius: 28, x: 0, y: 16)
            .padding(.horizontal, 38)
        }
        .transition(.opacity)
    }

    private func sendCode() {
        let trimmed = email.trimmingCharacters(in: .whitespacesAndNewlines)

        guard !trimmed.isEmpty, trimmed.contains("@"), trimmed.contains(".") else {
            openDialog(.error, "請輸入正確的電子郵件")
            return
        }

        withAnimation(.easeInOut(duration: 0.25)) {
            step = .verify
        }
    }

    private func verifyCode() {
        guard code.count >= 4 else {
            openDialog(.error, "驗證碼至少 4 碼")
            return
        }

        withAnimation(.easeInOut(duration: 0.25)) {
            step = .reset
        }
    }

    private func resetPassword() {
        guard newPassword.count >= 6 else {
            openDialog(.error, "密碼至少 6 碼")
            return
        }

        guard newPassword == confirmPassword else {
            openDialog(.error, "兩次輸入的新密碼不一致")
            return
        }

        openDialog(.success, "密碼已更新，請使用新密碼登入")
    }

    private func openDialog(_ type: ForgotDialogType, _ message: String) {
        dialogType = type
        dialogMessage = message

        withAnimation(.easeInOut(duration: 0.2)) {
            showDialog = true
        }
    }

    private func closeDialog() {
        withAnimation(.easeInOut(duration: 0.2)) {
            showDialog = false
        }
    }
}
