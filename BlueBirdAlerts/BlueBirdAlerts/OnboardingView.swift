import SwiftUI
import AVFoundation
import CoreImage
import CoreImage.CIFilterBuiltins

// MARK: - QR Scanner (AVFoundation UIViewRepresentable)

private struct QRScannerView: UIViewRepresentable {
    var onScanned: (String) -> Void

    func makeCoordinator() -> Coordinator { Coordinator(onScanned: onScanned) }

    func makeUIView(context: Context) -> UIView {
        let view = UIView(frame: .zero)
        view.backgroundColor = .black

        let session = AVCaptureSession()
        context.coordinator.session = session

        guard let device = AVCaptureDevice.default(for: .video),
              let input = try? AVCaptureDeviceInput(device: device),
              session.canAddInput(input) else { return view }
        session.addInput(input)

        let output = AVCaptureMetadataOutput()
        if session.canAddOutput(output) {
            session.addOutput(output)
            output.setMetadataObjectsDelegate(context.coordinator, queue: .main)
            output.metadataObjectTypes = [.qr]
        }

        let preview = AVCaptureVideoPreviewLayer(session: session)
        preview.videoGravity = .resizeAspectFill
        preview.frame = UIScreen.main.bounds
        view.layer.addSublayer(preview)
        context.coordinator.preview = preview

        DispatchQueue.global(qos: .userInitiated).async { session.startRunning() }
        return view
    }

    func updateUIView(_ uiView: UIView, context: Context) {
        DispatchQueue.main.async {
            context.coordinator.preview?.frame = uiView.bounds
        }
    }

    final class Coordinator: NSObject, AVCaptureMetadataOutputObjectsDelegate {
        var onScanned: (String) -> Void
        var session: AVCaptureSession?
        var preview: AVCaptureVideoPreviewLayer?
        private var hasFired = false

        init(onScanned: @escaping (String) -> Void) { self.onScanned = onScanned }

        func metadataOutput(_ output: AVCaptureMetadataOutput, didOutput objects: [AVMetadataObject], from connection: AVCaptureConnection) {
            guard !hasFired,
                  let obj = objects.first as? AVMetadataMachineReadableCodeObject,
                  let value = obj.stringValue else { return }
            hasFired = true
            session?.stopRunning()
            onScanned(value)
        }
    }
}

// MARK: - QR Code Image Generator

private func makeQRImage(from string: String, size: CGFloat = 220) -> UIImage? {
    let filter = CIFilter.qrCodeGenerator()
    filter.message = Data(string.utf8)
    filter.correctionLevel = "M"
    guard let output = filter.outputImage else { return nil }
    let scale = size / output.extent.width
    let scaled = output.transformed(by: CGAffineTransform(scaleX: scale, y: scale))
    let context = CIContext()
    guard let cgImage = context.createCGImage(scaled, from: scaled.extent) else { return nil }
    return UIImage(cgImage: cgImage)
}

// MARK: - Onboarding step enum

private enum OnboardingStep {
    case enterCode
    case scanQR
    case codeValidated(role: String, roleLabel: String, title: String?, tenantSlug: String, tenantName: String)
    case createAccount(role: String, tenantSlug: String, tenantName: String)
    case success
}

// MARK: - OnboardingView

struct OnboardingView: View {
    @EnvironmentObject private var appState: AppState
    @Environment(\.dismiss) private var dismiss

    @State private var step: OnboardingStep = .enterCode
    @State private var codeText = ""
    @State private var tenantSlugText = ""
    @State private var nameText = ""
    @State private var usernameText = ""
    @State private var passwordText = ""
    @State private var confirmPasswordText = ""
    @State private var showPassword = false
    @State private var isBusy = false
    @State private var errorMessage: String?
    @State private var cameraPermission: AVAuthorizationStatus = .notDetermined

    private var api: APIClient {
        APIClient(baseURL: Config.backendBaseURL, apiKey: Config.backendApiKey)
    }

    var body: some View {
        NavigationStack {
            ZStack {
                LinearGradient(
                    colors: [DSColor.background, DSColor.backgroundDeep],
                    startPoint: .top,
                    endPoint: .bottom
                )
                .ignoresSafeArea()

                ScrollView {
                    VStack(spacing: 22) {
                        headerView
                        stepContent
                    }
                    .padding(20)
                }
                .scrollDismissesKeyboard(.interactively)
            }
            .navigationTitle("Get Started")
            .navigationBarTitleDisplayMode(.inline)
            .toolbar {
                ToolbarItem(placement: .cancellationAction) {
                    Button("Cancel") { dismiss() }
                        .foregroundStyle(DSColor.primary)
                }
            }
        }
    }

    // MARK: - Header

    private var headerView: some View {
        VStack(spacing: 6) {
            Image(systemName: "person.badge.plus")
                .font(.system(size: 40))
                .foregroundStyle(DSColor.primary)
            Text("Account Setup")
                .font(.title2.weight(.bold))
                .foregroundStyle(DSColor.textPrimary)
            Text("Enter your invite code to create your account")
                .font(.subheadline)
                .foregroundStyle(DSColor.textSecondary)
                .multilineTextAlignment(.center)
        }
        .padding(.top, 8)
    }

    // MARK: - Step Content

    @ViewBuilder
    private var stepContent: some View {
        switch step {
        case .enterCode:
            enterCodeStep
        case .scanQR:
            scanQRStep
        case .codeValidated(let role, let roleLabel, let title, let tenantSlug, let tenantName):
            codeValidatedStep(role: role, roleLabel: roleLabel, title: title, tenantSlug: tenantSlug, tenantName: tenantName)
        case .createAccount(let role, let tenantSlug, let tenantName):
            createAccountStep(role: role, tenantSlug: tenantSlug, tenantName: tenantName)
        case .success:
            successStep
        }
    }

    // MARK: - Enter Code Step

    private var enterCodeStep: some View {
        VStack(spacing: 16) {
            CardView {
                SectionContainer("District & Invite Code") {
                    TextInput(text: $tenantSlugText, placeholder: "District code (e.g. nen)")
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    Text("Enter the district code provided by your administrator.")
                        .font(.caption)
                        .foregroundStyle(DSColor.textSecondary)
                    TextInput(text: $codeText, placeholder: "Enter your 8-character invite code")
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.characters)
                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(DSColor.danger)
                    }
                }
            }

            PrimaryButton(
                isBusy ? "Checking..." : "Validate Code",
                isLoading: isBusy,
                isEnabled: !isBusy && codeText.trimmingCharacters(in: .whitespaces).count >= 4
            ) {
                Task { await validateCode() }
            }

            Button {
                requestCameraAndScan()
            } label: {
                HStack(spacing: 8) {
                    Image(systemName: "qrcode.viewfinder")
                    Text("Scan QR Code Instead")
                }
                .font(.footnote.weight(.semibold))
                .foregroundStyle(DSColor.primary.opacity(0.85))
                .frame(maxWidth: .infinity)
                .padding(.vertical, 12)
            }
        }
    }

    // MARK: - QR Scan Step

    private var scanQRStep: some View {
        VStack(spacing: 16) {
            ZStack {
                QRScannerView { scanned in
                    handleScannedQR(scanned)
                }
                .frame(height: 300)
                .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

                RoundedRectangle(cornerRadius: 16, style: .continuous)
                    .stroke(DSColor.primary, lineWidth: 2)
                    .frame(height: 300)
            }

            Text("Point your camera at a BlueBird invite QR code")
                .font(.footnote)
                .foregroundStyle(DSColor.textSecondary)
                .multilineTextAlignment(.center)

            if let errorMessage {
                Text(errorMessage)
                    .font(.footnote)
                    .foregroundStyle(DSColor.danger)
            }

            Button("Enter Code Manually Instead") {
                step = .enterCode
                errorMessage = nil
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(DSColor.primary.opacity(0.85))
        }
    }

    // MARK: - Code Validated Step

    private func codeValidatedStep(role: String, roleLabel: String, title: String?, tenantSlug: String, tenantName: String) -> some View {
        VStack(spacing: 16) {
            CardView {
                VStack(alignment: .leading, spacing: 12) {
                    HStack(spacing: 10) {
                        Image(systemName: "checkmark.seal.fill")
                            .foregroundStyle(DSColor.success)
                        Text("Code Verified")
                            .font(.headline)
                            .foregroundStyle(DSColor.textPrimary)
                    }
                    Divider()
                    infoRow("School", value: tenantName)
                    infoRow("Your Role", value: roleLabel)
                    if let title { infoRow("Title", value: title) }
                }
                .padding(4)
            }

            PrimaryButton("Create My Account") {
                step = .createAccount(role: role, tenantSlug: tenantSlug, tenantName: tenantName)
                errorMessage = nil
            }

            Button("Try a Different Code") {
                step = .enterCode
                codeText = ""
                tenantSlugText = ""
                errorMessage = nil
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(DSColor.textSecondary)
        }
    }

    // MARK: - Create Account Step

    private func createAccountStep(role: String, tenantSlug: String, tenantName: String) -> some View {
        VStack(spacing: 16) {
            CardView {
                SectionContainer("Your Details") {
                    TextInput(text: $nameText, placeholder: "Full name")
                    TextInput(text: $usernameText, placeholder: "Username (for login)")
                        .autocorrectionDisabled()
                        .textInputAutocapitalization(.never)
                    passwordFieldView(binding: $passwordText, placeholder: "Password (min 8 characters)")
                    passwordFieldView(binding: $confirmPasswordText, placeholder: "Confirm password")
                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(DSColor.danger)
                    }
                }
            }

            PrimaryButton(
                isBusy ? "Creating Account..." : "Create Account",
                isLoading: isBusy,
                isEnabled: !isBusy && !nameText.isEmpty && !usernameText.isEmpty && passwordText.count >= 8
            ) {
                Task { await createAccount(role: role, tenantSlug: tenantSlug) }
            }
        }
    }

    // MARK: - Success Step

    private var successStep: some View {
        VStack(spacing: 20) {
            Image(systemName: "checkmark.circle.fill")
                .font(.system(size: 64))
                .foregroundStyle(DSColor.success)

            Text("Account Created!")
                .font(.title2.weight(.bold))
                .foregroundStyle(DSColor.textPrimary)

            Text("Your account is ready. Sign in with your username and password on the login screen.")
                .font(.subheadline)
                .foregroundStyle(DSColor.textSecondary)
                .multilineTextAlignment(.center)

            PrimaryButton("Done") {
                dismiss()
            }
        }
        .padding(.top, 20)
    }

    // MARK: - Helpers

    private func infoRow(_ label: String, value: String) -> some View {
        HStack {
            Text(label)
                .font(.footnote)
                .foregroundStyle(DSColor.textSecondary)
            Spacer()
            Text(value)
                .font(.footnote.weight(.semibold))
                .foregroundStyle(DSColor.textPrimary)
        }
    }

    private func passwordFieldView(binding: Binding<String>, placeholder: String) -> some View {
        SecureField("", text: binding, prompt: Text(placeholder).foregroundStyle(DSColor.textSecondary))
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled()
            .foregroundStyle(.white)
            .padding(.horizontal, 14)
            .padding(.vertical, 12)
            .background(DSColor.inputBackground)
            .clipShape(RoundedRectangle(cornerRadius: DSRadius.input, style: .continuous))
    }

    // MARK: - Actions

    private func requestCameraAndScan() {
        switch AVCaptureDevice.authorizationStatus(for: .video) {
        case .authorized:
            step = .scanQR
        case .notDetermined:
            AVCaptureDevice.requestAccess(for: .video) { granted in
                DispatchQueue.main.async {
                    step = granted ? .scanQR : .enterCode
                    if !granted { errorMessage = "Camera access is required to scan QR codes." }
                }
            }
        default:
            errorMessage = "Camera access is required. Enable it in Settings."
        }
    }

    private func handleScannedQR(_ raw: String) {
        guard let data = raw.data(using: .utf8),
              let json = try? JSONSerialization.jsonObject(with: data) as? [String: String],
              let code = json["code"],
              let tenantSlug = json["tenant_slug"] else {
            errorMessage = "Invalid QR code format."
            step = .enterCode
            return
        }
        codeText = code
        Task { await validateCodeWith(code: code, tenantSlug: tenantSlug) }
    }

    private func validateCode() async {
        let code = codeText.trimmingCharacters(in: .whitespaces).uppercased()
        let tenantSlug = tenantSlugText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !code.isEmpty else { return }
        await validateCodeWith(code: code, tenantSlug: tenantSlug)
    }

    private func validateCodeWith(code: String, tenantSlug: String) async {
        guard !code.isEmpty else { return }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        if tenantSlug.isEmpty {
            // No district code → try as a district admin setup code
            do {
                let result = try await api.validateSetupCode(code: code)
                if result.valid, let slug = result.tenantSlug, let name = result.tenantName {
                    step = .codeValidated(
                        role: "district_admin",
                        roleLabel: "District Admin",
                        title: nil,
                        tenantSlug: slug,
                        tenantName: name
                    )
                    return
                }
            } catch {}
            errorMessage = "Could not validate code. Enter your district code above if you have an invite code."
            return
        }

        // Regular invite code — validate against the specified district
        do {
            let result = try await api.validateInviteCode(code: code, tenantSlug: tenantSlug)
            if result.valid {
                step = .codeValidated(
                    role: result.role ?? "",
                    roleLabel: result.roleLabel ?? result.role ?? "",
                    title: result.title,
                    tenantSlug: result.tenantSlug ?? tenantSlug,
                    tenantName: result.tenantName ?? tenantSlug
                )
            } else {
                errorMessage = result.error ?? "Code is invalid, expired, or already used."
            }
        } catch {
            errorMessage = "Could not validate code: \(error.localizedDescription)"
        }
    }

    private func createAccount(role: String, tenantSlug: String) async {
        let name = nameText.trimmingCharacters(in: .whitespaces)
        let username = usernameText.trimmingCharacters(in: .whitespaces).lowercased()
        guard !name.isEmpty, !username.isEmpty else {
            errorMessage = "Name and username are required."
            return
        }
        guard passwordText == confirmPasswordText else {
            errorMessage = "Passwords do not match."
            return
        }
        guard passwordText.count >= 8 else {
            errorMessage = "Password must be at least 8 characters."
            return
        }
        isBusy = true
        errorMessage = nil
        defer { isBusy = false }

        do {
            let code = codeText.trimmingCharacters(in: .whitespaces).uppercased()
            let result = try await api.createAccountFromCode(
                code: code,
                tenantSlug: tenantSlug,
                name: name,
                loginName: username,
                password: passwordText
            )
            if result.valid {
                step = .success
            } else {
                errorMessage = result.error ?? "Could not create account."
            }
        } catch {
            errorMessage = "Account creation failed: \(error.localizedDescription)"
        }
    }
}
