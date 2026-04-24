import SwiftUI

private struct PressableScaleButtonStyle: ButtonStyle {
    func makeBody(configuration: Configuration) -> some View {
        configuration.label
            .scaleEffect(configuration.isPressed ? 0.985 : 1.0)
            .animation(.easeOut(duration: 0.14), value: configuration.isPressed)
    }
}

struct PrimaryButton: View {
    let title: String
    let isLoading: Bool
    let isEnabled: Bool
    let action: () -> Void

    init(
        _ title: String,
        isLoading: Bool = false,
        isEnabled: Bool = true,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.isLoading = isLoading
        self.isEnabled = isEnabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: DSSpacing.sm) {
                if isLoading {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .tint(.white)
                        .scaleEffect(0.9)
                }
                Text(title)
                    .font(DSTypography.button)
                    .foregroundStyle(.white)
            }
            .frame(maxWidth: .infinity, minHeight: 46)
            .background(
                RoundedRectangle(cornerRadius: DSRadius.button, style: .continuous)
                    .fill(DSColor.primary.opacity(isEnabled ? 1.0 : 0.55))
            )
            .shadow(color: isEnabled ? DSColor.primary.opacity(0.28) : .clear, radius: 8, x: 0, y: 3)
        }
        .buttonStyle(PressableScaleButtonStyle())
        .disabled(!isEnabled)
    }
}

struct DangerButton: View {
    let title: String
    let isLoading: Bool
    let isEnabled: Bool
    let action: () -> Void

    init(
        _ title: String,
        isLoading: Bool = false,
        isEnabled: Bool = true,
        action: @escaping () -> Void
    ) {
        self.title = title
        self.isLoading = isLoading
        self.isEnabled = isEnabled
        self.action = action
    }

    var body: some View {
        Button(action: action) {
            HStack(spacing: DSSpacing.sm) {
                if isLoading {
                    ProgressView()
                        .progressViewStyle(.circular)
                        .tint(.white)
                        .scaleEffect(0.9)
                }
                Text(title)
                    .font(DSTypography.button)
                    .foregroundStyle(.white)
            }
            .frame(maxWidth: .infinity, minHeight: 46)
            .background(
                RoundedRectangle(cornerRadius: DSRadius.button, style: .continuous)
                    .fill(DSColor.danger.opacity(isEnabled ? 1.0 : 0.55))
            )
            .shadow(color: isEnabled ? DSColor.danger.opacity(0.24) : .clear, radius: 8, x: 0, y: 3)
        }
        .buttonStyle(PressableScaleButtonStyle())
        .disabled(!isEnabled)
    }
}

struct TextInput: View {
    @Binding var text: String
    let placeholder: String
    let axis: Axis

    init(
        text: Binding<String>,
        placeholder: String,
        axis: Axis = .horizontal
    ) {
        self._text = text
        self.placeholder = placeholder
        self.axis = axis
    }

    var body: some View {
        TextField(
            "",
            text: $text,
            prompt: Text(placeholder).foregroundStyle(DSColor.textSecondary),
            axis: axis
        )
        .textInputAutocapitalization(.never)
        .autocorrectionDisabled(true)
        .foregroundStyle(.white)
        .padding(.horizontal, 14)
        .padding(.vertical, 12)
        .background(DSColor.inputBackground)
        .overlay(
            RoundedRectangle(cornerRadius: DSRadius.input, style: .continuous)
                .stroke(DSColor.border, lineWidth: 1)
        )
        .clipShape(RoundedRectangle(cornerRadius: DSRadius.input, style: .continuous))
    }
}

struct CardView<Content: View>: View {
    @ViewBuilder let content: Content

    init(@ViewBuilder content: () -> Content) {
        self.content = content()
    }

    var body: some View {
        content
            .padding(DSSpacing.lg)
            .frame(maxWidth: .infinity, alignment: .leading)
            .background(DSColor.card)
            .clipShape(RoundedRectangle(cornerRadius: DSRadius.card, style: .continuous))
            .shadow(color: .black.opacity(0.06), radius: 8, x: 0, y: 3)
    }
}

struct SectionContainer<Content: View>: View {
    let title: String
    @ViewBuilder let content: Content

    init(_ title: String, @ViewBuilder content: () -> Content) {
        self.title = title
        self.content = content()
    }

    var body: some View {
        VStack(alignment: .leading, spacing: DSSpacing.md) {
            Text(title)
                .font(.headline)
                .foregroundStyle(DSColor.textPrimary)
            content
        }
    }
}
