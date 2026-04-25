# Bluebird Alerts UI Spec

This document defines the shared mobile UI system used by iOS and Android.

## Tokens

Primary source:
- `/design/tokens.json` (optional at runtime, read-only for app code)

If token file is unavailable or incomplete, platforms must fall back to existing in-code defaults.

### Colors
- `Primary`
- `Danger`
- `Background`
- `Card`
- `InputBackground`
- `TextPrimary`
- `TextSecondary`
- `Border`

### Spacing
- `XS = 4`
- `SM = 8`
- `MD = 12`
- `LG = 16`
- `XL = 20`

### Radius
- `Button`
- `Card`
- `Input`

### Typography
- `Title`
- `Body`
- `Button`

## Components

Use shared components instead of ad-hoc styling:
- `PrimaryButton`
- `DangerButton`
- `TextInput`
- `CardView`
- `SectionContainer`

Rules:
- Disabled buttons must appear visually muted.
- Loading actions must show progress feedback.
- Inputs must use shared paddings, radius, and border style.

## Interaction Rules

### Keyboard
- Tapping outside active input should dismiss keyboard.
- Keyboard dismissal should not break button taps.

### Buttons
- Enabled/disabled state must be obvious.
- Press interactions should use subtle scale feedback only.

### Slide-to-confirm
- If released before threshold, slider returns to start.
- Slider should never remain partially completed after release.

### Recipient selection
- Multi-select is required for admin messaging.
- Include `Select All`.
- Show dynamic label:
  - `All users`
  - `X users selected`

## Platform Mapping

### iOS
- Tokens: `DesignSystem.swift`
- Components: `UIComponents.swift`
- Theme mode preference key: `ds_theme_mode` (`system` / `light` / `dark`)

### Android
- Tokens: `DesignSystem.kt`
- Components: `UIComponents.kt`
- Token loader reads bundled asset `tokens.json` when present

### Admin Web
- Token-aware CSS variables are emitted from `backend/app/web/admin_views.py`
- Existing CSS variables continue to work via alias mapping and fallback values
