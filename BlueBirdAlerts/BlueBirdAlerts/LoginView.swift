import SwiftUI
import UIKit

struct LoginView: View {
    @EnvironmentObject private var appState: AppState
    @State private var schoolCode = ""
    @State private var username = ""
    @State private var password = ""
    @State private var showPassword = false
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @State private var schoolOptions: [SchoolCatalogItem] = []
    @State private var schoolLoadHint = "Enter your school code (for example: nn) and sign in."
    @State private var selectedSchoolName = ""
    @State private var keyboardHeight: CGFloat = 0
    @State private var animateIntro = false

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [DSColor.background, DSColor.backgroundDeep],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 22) {
                    VStack(spacing: 6) {
                        Image("BlueBirdLogo")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 84, height: 84)
                        Text("BlueBird Alerts")
                            .font(.system(size: 32, weight: .bold))
                            .foregroundStyle(DSColor.textPrimary)
                            .shadow(color: .black.opacity(0.08), radius: 1.5, x: 0, y: 1)
                        Text("School safety login")
                            .font(.subheadline)
                            .foregroundStyle(DSColor.textSecondary)
                    }
                    .padding(.top, 14)
                    .opacity(animateIntro ? 1 : 0.0)
                    .offset(y: animateIntro ? 0 : 5)
                    .animation(.easeOut(duration: 0.28), value: animateIntro)

                    CardView {
                        SectionContainer("School code or URL") {
                            TextInput(
                                text: $schoolCode,
                                placeholder: "Enter school code or URL (e.g. nn)"
                            )
                            if !schoolOptions.isEmpty {
                                Menu {
                                    ForEach(schoolOptions) { school in
                                        Button("\(school.name) (\(school.slug))") {
                                            schoolCode = school.slug
                                            selectedSchoolName = school.name
                                        }
                                    }
                                } label: {
                                    HStack(spacing: 8) {
                                        Image(systemName: "building.2")
                                        Text("Pick from school list")
                                            .underline()
                                        Spacer()
                                        Image(systemName: "chevron.right")
                                    }
                                    .font(.footnote.weight(.semibold))
                                    .foregroundStyle(DSColor.primary)
                                    .padding(.horizontal, 14)
                                    .padding(.vertical, 12)
                                    .frame(maxWidth: .infinity, alignment: .leading)
                                    .background(DSColor.background)
                                    .clipShape(RoundedRectangle(cornerRadius: 12, style: .continuous))
                                }
                            }
                            Text(schoolLoadHint)
                                .font(.footnote)
                                .foregroundStyle(DSColor.textSecondary)
                        }
                    }

                    CardView {
                        SectionContainer("Credentials") {
                            TextInput(text: $username, placeholder: "Username")
                            passwordField
                        }
                    }

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(DSColor.danger)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    PrimaryButton(
                        isSubmitting ? "Signing In..." : "Sign In",
                        isLoading: isSubmitting,
                        isEnabled: !isSubmitting
                    ) {
                        Task { await submitLogin() }
                    }
                }
                .padding(20)
                .padding(.bottom, max(0, keyboardHeight - 44))
            }
            .scrollDismissesKeyboard(.interactively)
        }
        .task {
            await loadSchools()
            animateIntro = true
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillShowNotification)) { note in
            guard let frame = note.userInfo?[UIResponder.keyboardFrameEndUserInfoKey] as? CGRect else { return }
            withAnimation(.easeOut(duration: 0.22)) {
                keyboardHeight = frame.height
            }
        }
        .onReceive(NotificationCenter.default.publisher(for: UIResponder.keyboardWillHideNotification)) { _ in
            withAnimation(.easeOut(duration: 0.22)) {
                keyboardHeight = 0
            }
        }
    }

    private var passwordField: some View {
        HStack(spacing: 10) {
            Group {
                if showPassword {
                    TextField(
                        "",
                        text: $password,
                        prompt: Text("Password").foregroundStyle(DSColor.textSecondary)
                    )
                } else {
                    SecureField(
                        "",
                        text: $password,
                        prompt: Text("Password").foregroundStyle(DSColor.textSecondary)
                    )
                }
            }
            .textInputAutocapitalization(.never)
            .autocorrectionDisabled(true)
            .foregroundStyle(.white)

            Button(showPassword ? "Hide" : "Show") {
                showPassword.toggle()
            }
            .font(.footnote.weight(.semibold))
            .foregroundStyle(DSColor.primary.opacity(0.85))
        }
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(DSColor.inputBackground)
        .overlay(
            RoundedRectangle(cornerRadius: DSRadius.input, style: .continuous)
                .stroke(DSColor.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: DSRadius.input, style: .continuous))
    }

    private func loadSchools() async {
        let client = APIClient(baseURL: Config.backendBaseURL, apiKey: Config.backendApiKey)
        do {
            let response = try await client.listSchools()
            schoolOptions = response.schools
            if response.schools.isEmpty {
                schoolLoadHint = "No schools found on backend yet. Enter school code manually."
            } else {
                schoolLoadHint = "Choose a school from the list or enter your school code manually."
            }
        } catch {
            schoolLoadHint = "Could not load school list. You can still enter school code manually."
        }
    }

    private func submitLogin() async {
        let trimmedUser = username.trimmingCharacters(in: .whitespacesAndNewlines).lowercased()
        let trimmedPassword = password.trimmingCharacters(in: .whitespacesAndNewlines)
        guard !trimmedUser.isEmpty, !trimmedPassword.isEmpty else {
            errorMessage = "Enter your username and password."
            return
        }
        guard let serverURL = normalizeServerURL(input: schoolCode) else {
            errorMessage = "Enter your school code (or full school URL)."
            return
        }

        isSubmitting = true
        defer { isSubmitting = false }
        errorMessage = nil

        do {
            let client = APIClient(baseURL: serverURL, apiKey: Config.backendApiKey)
            let user = try await client.login(username: trimmedUser, password: trimmedPassword)
            let resolvedSchoolName = resolveSchoolName(forURL: serverURL)
            appState.completeLogin(
                userID: user.userID,
                name: user.name,
                role: user.role,
                loginName: user.loginName,
                canDeactivateAlarm: user.canDeactivateAlarm,
                serverURL: serverURL,
                schoolName: resolvedSchoolName
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func resolveSchoolName(forURL url: URL) -> String {
        // Use the name from the picker selection if the slug still matches.
        let slug = url.pathComponents.last(where: { $0 != "/" }) ?? ""
        if !selectedSchoolName.isEmpty,
           schoolOptions.first(where: { $0.slug == slug })?.slug == slug {
            return selectedSchoolName
        }
        // Fall back to matching the slug against fetched school options.
        if let match = schoolOptions.first(where: { $0.slug == slug }) {
            return match.name
        }
        // Last resort: use the slug itself, title-cased.
        return slug.replacingOccurrences(of: "-", with: " ").capitalized
    }

    private func normalizeServerURL(input: String) -> URL? {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if trimmed.isEmpty { return nil }

        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            guard let raw = URL(string: trimmed) else { return nil }
            return ensureTenantPath(on: raw)
        }

        if trimmed.contains(".") || trimmed.contains("/") {
            guard let raw = URL(string: "https://\(trimmed)") else { return nil }
            return ensureTenantPath(on: raw)
        }

        let base = Config.backendBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return URL(string: "\(base)/\(trimmed.lowercased())")
    }

    private func ensureTenantPath(on url: URL) -> URL {
        guard var comps = URLComponents(url: url, resolvingAgainstBaseURL: false) else {
            return url
        }
        let normalizedPath = comps.path.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if normalizedPath.isEmpty {
            comps.path = "/default"
        }
        return comps.url ?? url
    }
}
