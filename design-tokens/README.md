# BlueBird Design Tokens

The canonical token source is `bluebird.tokens.json`.  
All three platforms (web, Android, iOS) read from a copy of this file.

## Token File Locations

| Platform | File Path |
|----------|-----------|
| Source of truth | `design-tokens/bluebird.tokens.json` |
| Web (legacy copy) | `design/tokens.json` |
| Android (bundled asset) | `android/app/src/main/assets/tokens.json` |
| iOS (bundle resource) | `BlueBirdAlerts/BlueBirdAlerts/tokens.json` (add to Xcode target) |

Keep all three copies identical. Copy `bluebird.tokens.json` → other locations after any change.

## Token Structure

### Colors

```jsonc
"color": {
  "mode": {              // light/dark variants
    "primary":  { "light": "#...", "dark": "#..." },
    "background": ...
  },
  "status": {            // semantic status colors
    "success", "warning", "info", "quiet",
    "offline", "archived", "expired", "trial", "active_license"
  },
  "alert": {             // alert-type colors
    "lockdown", "secure", "evacuate", "shelter", "hold", "active", "clear"
  }
}
```

### Spacing
`xs`=4  `sm`=8  `md`=12  `lg`=16  `xl`=20  `xxl`=24  (all in dp/pt/px)

### Radius
`sm`=8  `md`=12  `lg`=16  `xl`=20  `button`=16  `card`=20  `input`=14  `pill`=9999

### Typography
`title_large`=28  `title_medium`=20  `title`=24  `section_title`=13  
`body`=16  `button`=16  `caption`=12  (all in sp/pt)

### Animation (ms)
`fast`=150  `normal`=250  `slow`=350  `hold`=80

## Rules

1. **Never hardcode colors** in individual screens or components.
2. **Always use token references**: `DSColor.primary`, `var(--accent)`, `MaterialTheme.colorScheme.primary`.
3. **Dark/light modes** are handled by `color.mode.*` keys — use the `{ "light": "#...", "dark": "#..." }` format.
4. **To change a global color**: edit `bluebird.tokens.json`, copy to the three platform locations, rebuild.

## Platform Consumption

### Web

CSS variables defined in `:root` / `[data-theme="dark"]` in `dashboard.py` and `admin_views.py`:

```css
--accent:    var mapping of color.mode.primary.light
--danger:    color.danger
--success:   color.status.success
--bg:        color.mode.background.light
```

### Android

`DSTokenStore.kt` loads `assets/tokens.json` at runtime. Access via:

```kotlin
DSColor.Primary      // → color.mode.primary (light or dark)
DSColor.Danger       // → color.danger
DSColor.Success      // → color.status.success
BBAlertColors.forType("lockdown")  // → color.alert.lockdown
BBStatusColors.Offline             // → color.status.offline
```

### iOS

`DSTokenStore.swift` loads `tokens.json` from the app bundle. Access via:

```swift
DSColor.primary      // → color.mode.primary (adaptive light/dark)
DSColor.danger       // → color.danger
DSColor.success      // → color.status.success
DSAlertColor.forType("lockdown")   // → color.alert.lockdown
DSAlertColor.lockdown              // direct access
```
