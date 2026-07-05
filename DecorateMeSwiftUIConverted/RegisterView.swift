import SwiftUI

struct RegisterView: View {
    var onBackToLogin: () -> Void

    @State private var username = ""
    @State private var phone = ""
    @State private var email = ""
    @State private var age = ""
    @State private var password = ""
    @State private var confirmPassword = ""
    @State private var verificationCode = ""

    @State private var showDialog = false
    @State private var dialogMessage = ""
    @State private var dialogIcon = "✦"
    @State private var dialogIconColor = Color(red: 0.96, green: 0.82, blue: 0.70)
    @State private var showVerificationPage = false
    @State private var registerSuccess = false

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

            if showVerificationPage {
                VerificationMailView(
                    email: email,
                    verificationCode: $verificationCode,
                    onVerify: verifyCodeAction,
                    onResend: resendCodeAction,
                    onBack: {
                        withAnimation(.easeInOut(duration: 0.25)) {
                            showVerificationPage = false
                        }
                    }
                )
            } else {
                ScrollView(showsIndicators: true) {
                    VStack {
                        VStack(spacing: 34) {
                            VStack(spacing: 16) {
                                Text("建立帳號")
                                    .font(.system(size: 42, weight: .regular, design: .serif))
                                    .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))

                                Text("Create your beauty profile")
                                    .font(.system(size: 14, weight: .light, design: .rounded))
                                    .tracking(5)
                                    .foregroundStyle(Color(red: 0.62, green: 0.42, blue: 0.39))
                            }

                            ZStack(alignment: .bottomTrailing) {
                                Circle()
                                    .fill(Color.white.opacity(0.18))
                                    .frame(width: 150, height: 150)
                                    .overlay(
                                        Circle()
                                            .stroke(Color(red: 0.72, green: 0.49, blue: 0.45).opacity(0.22), lineWidth: 1.3)
                                    )

                                Text("👤")
                                    .font(.system(size: 62))
                                    .frame(width: 150, height: 150)

                                Text("📷")
                                    .font(.system(size: 24))
                                    .frame(width: 48, height: 48)
                                    .background(Color.white.opacity(0.34), in: Circle())
                                    .offset(x: -10, y: -12)
                            }
                            .padding(.top, 30)

                            VStack(spacing: 28) {
                                LuxuryTextField(
                                    title: "使用者名稱",
                                    placeholder: "你的名字",
                                    text: $username
                                )

                                LuxuryTextField(
                                    title: "電話號碼",
                                    placeholder: "0912345678",
                                    text: $phone
                                )

                                LuxuryTextField(
                                    title: "電子郵件",
                                    placeholder: "your@email.com",
                                    text: $email
                                )

                                LuxuryTextField(
                                    title: "年齡",
                                    placeholder: "20",
                                    text: $age
                                )

                                LuxuryTextField(
                                    title: "密碼",
                                    placeholder: "••••••••",
                                    text: $password,
                                    secure: true
                                )

                                LuxuryTextField(
                                    title: "確認密碼",
                                    placeholder: "••••••••",
                                    text: $confirmPassword,
                                    secure: true
                                )
                            }
                            .padding(.top, 8)

                            Button {
                                registerAction()
                            } label: {
                                LuxuryButtonText("註    冊")
                            }
                            .padding(.top, 18)

                            Button("已有帳號？返回登入") {
                                withAnimation(.easeInOut(duration: 0.25)) {
                                    onBackToLogin()
                                }
                            }
                            .font(.system(size: 15, weight: .light))
                            .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))
                            .padding(.bottom, 14)
                        }
                        .padding(.horizontal, 34)
                        .padding(.top, 62)
                        .padding(.bottom, 42)
                        .frame(maxWidth: .infinity)
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
                        .padding(.vertical, 34)
                    }
                }
            }

            if showDialog {
                RegisterDialog(message: dialogMessage, icon: dialogIcon, iconColor: dialogIconColor) {
                    withAnimation(.easeInOut(duration: 0.2)) {
                        showDialog = false
                    }

                    if registerSuccess {
                        onBackToLogin()
                    }
                }
            }
        }
    }

    private func registerAction() {
        if username.isEmpty ||
            phone.isEmpty ||
            email.isEmpty ||
            age.isEmpty ||
            password.isEmpty ||
            confirmPassword.isEmpty {
            showRegisterDialog(message: "請完整填寫所有欄位")
            return
        }

        if password != confirmPassword {
            showRegisterDialog(message: "兩次輸入的密碼不一致")
            return
        }

        withAnimation(.easeInOut(duration: 0.25)) {
            showVerificationPage = true
        }
    }

    private func verifyCodeAction() {
        if verificationCode.count < 4 {
            showRegisterDialog(message: "驗證碼至少 4 碼")
            return
        }

        registerSuccess = true
        showSuccessDialog(message: "帳號已成功建立")
    }

    private func resendCodeAction() {
        showRegisterDialog(message: "驗證碼已重新發送")
    }

    private func showRegisterDialog(message: String) {
        registerSuccess = false
        dialogMessage = message
        dialogIcon = "✦"
        dialogIconColor = Color(red: 0.96, green: 0.82, blue: 0.70)
        withAnimation(.easeInOut(duration: 0.2)) {
            showDialog = true
        }
    }

    private func showSuccessDialog(message: String) {
        dialogMessage = message
        dialogIcon = "√"
        dialogIconColor = Color(red: 0.82, green: 0.90, blue: 0.78)
        withAnimation(.easeInOut(duration: 0.2)) {
            showDialog = true
        }
    }
}

struct VerificationMailView: View {
    let email: String
    @Binding var verificationCode: String
    var onVerify: () -> Void
    var onResend: () -> Void
    var onBack: () -> Void

    var body: some View {
        VStack {
            VStack(spacing: 38) {
                VStack(spacing: 18) {
                    Text("驗證信箱")
                        .font(.system(size: 46, weight: .regular, design: .serif))
                        .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))

                    VStack(spacing: 8) {
                        Text("已將驗證碼發送至")
                            .font(.system(size: 17, weight: .light))
                            .tracking(2)
                            .foregroundStyle(Color(red: 0.58, green: 0.41, blue: 0.39))

                        Text(email)
                            .font(.system(size: 18, weight: .light, design: .monospaced))
                            .tracking(3)
                            .foregroundStyle(Color(red: 0.48, green: 0.31, blue: 0.30))
                    }
                }
                .padding(.top, 80)

                VStack(alignment: .leading, spacing: 20) {
                    Text("驗證碼")
                        .font(.system(size: 18, weight: .light))
                        .tracking(4)
                        .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))

                    TextField("請輸入驗證碼", text: $verificationCode)
                        .font(.system(size: 26, weight: .light))
                        .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))
                        .keyboardType(.numberPad)
                        .textContentType(.oneTimeCode)
                        .padding(.vertical, 8)
                    

                    Rectangle()
                        .fill(Color(red: 0.70, green: 0.43, blue: 0.39).opacity(0.35))
                        .frame(height: 1)
                }
                .padding(.horizontal, 58)
                .padding(.top, 24)

                VStack(spacing: 24) {
                    Button {
                    
                        onVerify()
                    } label: {
                        
                        LuxuryButtonText("驗    證")
                    }

                    Button {
                        onResend()
                    } label: {
                        LuxuryButtonText("重新發送驗證碼")
                    }

                    Button("回上一頁") {
                        onBack()
                    }
                    .font(.system(size: 17, weight: .light))
                    .foregroundStyle(Color(red: 0.70, green: 0.43, blue: 0.39))
                    .padding(.top, 10)
                }
                .padding(.horizontal, 58)
                .padding(.top, 18)

                Spacer()
            }
            .frame(maxWidth: .infinity)
            .frame(height: 820)
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
            .padding(.vertical, 34)
        }
    }
}

struct RegisterDialog: View {
    let message: String
    var icon: String = "✦"
    var iconColor: Color = Color(red: 0.96, green: 0.82, blue: 0.70)
    var onClose: () -> Void

    var body: some View {
        ZStack {
            Color.black.opacity(0.28)
                .ignoresSafeArea()

            VStack(spacing: 26) {
                HStack {
                    Spacer()

                    Button {
                        onClose()
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
                    .fill(iconColor)
                    .frame(width: 82, height: 82)
                    .overlay(
                        Text(icon)
                            .font(.system(size: 38, weight: .light, design: .serif))
                            .foregroundStyle(Color(red: 0.48, green: 0.25, blue: 0.22))
                    )
                    .overlay(Circle().stroke(Color.white.opacity(0.9), lineWidth: 1.5))

                Text(message)
                    .font(.system(size: 25, weight: .regular, design: .serif))
                    .multilineTextAlignment(.center)
                    .foregroundStyle(Color(red: 0.22, green: 0.15, blue: 0.16))

                Button {
                    onClose()
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
            .padding(.horizontal, 38)
        }
        .transition(.opacity)
    }
}
