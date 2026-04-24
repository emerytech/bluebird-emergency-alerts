import SwiftUI

struct LoginView: View {
    @EnvironmentObject private var appState: AppState
    @State private var schoolCode = ""
    @State private var username = ""
    @State private var password = ""
    @State private var isSubmitting = false
    @State private var errorMessage: String?
    @State private var schoolOptions: [SchoolCatalogItem] = []
    @State private var schoolLoadHint = "Enter your school code (for example: nn) and sign in."

    var body: some View {
        ZStack {
            LinearGradient(
                colors: [Color(red: 0.93, green: 0.96, blue: 1.0), Color(red: 0.86, green: 0.91, blue: 1.0)],
                startPoint: .top,
                endPoint: .bottom
            )
            .ignoresSafeArea()

            ScrollView {
                VStack(spacing: 16) {
                    VStack(spacing: 8) {
                        Image("BlueBirdLogo")
                            .resizable()
                            .scaledToFit()
                            .frame(width: 82, height: 82)
                        Text("BlueBird Alerts")
                            .font(.system(size: 32, weight: .bold))
                        Text("School safety login")
                            .font(.subheadline)
                            .foregroundStyle(.secondary)
                    }
                    .padding(.top, 24)

                    VStack(alignment: .leading, spacing: 12) {
                        Text("School code or URL")
                            .font(.caption)
                            .foregroundStyle(.secondary)
                        TextField("nn", text: $schoolCode)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled(true)
                            .textFieldStyle(.roundedBorder)
                        if !schoolOptions.isEmpty {
                            Menu("Pick from school list") {
                                ForEach(schoolOptions) { school in
                                    Button("\(school.name) (\(school.slug))") {
                                        schoolCode = school.slug
                                    }
                                }
                            }
                            .font(.footnote.weight(.semibold))
                        }
                        Text(schoolLoadHint)
                            .font(.footnote)
                            .foregroundStyle(.secondary)
                    }
                    .padding()
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

                    VStack(spacing: 10) {
                        TextField("Username", text: $username)
                            .textInputAutocapitalization(.never)
                            .autocorrectionDisabled(true)
                            .textFieldStyle(.roundedBorder)
                        SecureField("Password", text: $password)
                            .textFieldStyle(.roundedBorder)
                    }
                    .padding()
                    .background(Color.white)
                    .clipShape(RoundedRectangle(cornerRadius: 16, style: .continuous))

                    if let errorMessage {
                        Text(errorMessage)
                            .font(.footnote)
                            .foregroundStyle(.red)
                            .frame(maxWidth: .infinity, alignment: .leading)
                    }

                    Button {
                        Task { await submitLogin() }
                    } label: {
                        Text(isSubmitting ? "Signing In..." : "Sign In")
                            .frame(maxWidth: .infinity, minHeight: 52)
                    }
                    .buttonStyle(.borderedProminent)
                    .tint(Color(red: 0.11, green: 0.37, blue: 0.89))
                    .disabled(isSubmitting)
                }
                .padding(20)
            }
        }
        .task {
            await loadSchools()
        }
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
            appState.completeLogin(
                userID: user.userID,
                name: user.name,
                role: user.role,
                loginName: user.loginName,
                canDeactivateAlarm: user.canDeactivateAlarm,
                serverURL: serverURL
            )
        } catch {
            errorMessage = error.localizedDescription
        }
    }

    private func normalizeServerURL(input: String) -> URL? {
        let trimmed = input.trimmingCharacters(in: .whitespacesAndNewlines).trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        if trimmed.isEmpty { return nil }

        if trimmed.hasPrefix("http://") || trimmed.hasPrefix("https://") {
            return URL(string: trimmed)
        }

        if trimmed.contains(".") || trimmed.contains("/") {
            return URL(string: "https://\(trimmed)")
        }

        let base = Config.backendBaseURL.absoluteString.trimmingCharacters(in: CharacterSet(charactersIn: "/"))
        return URL(string: "\(base)/\(trimmed.lowercased())")
    }
}
