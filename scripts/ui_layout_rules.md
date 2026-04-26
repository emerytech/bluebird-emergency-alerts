# BlueBird Alerts — Web Admin UI Layout Rules

All web admin pages (super-admin and tenant) must follow the structure below.
Do not invent new layouts. Extend within this system.

---

## Shell Structure

Every authenticated page uses this exact HTML skeleton:

```html
<main class="page-shell">
  <div class="app-shell">

    <!-- LEFT: Fixed sidebar nav -->
    <aside class="sidebar nav-panel">
      <section class="brand-block"> ... </section>
      <section class="signal-card">
        <div class="nav-group">
          <p class="nav-label">Section Label</p>
          <nav class="nav-list">
            <!-- use _nav_item() helper -->
          </nav>
        </div>
        <div class="shell-actions">
          <!-- logout, secondary actions -->
        </div>
      </section>
    </aside>

    <!-- RIGHT: Scrollable main content -->
    <section class="content-stack workspace">
      <!-- one <section class="panel command-section"> per nav item -->
    </section>

  </div>
</main>
```

**Never** put content outside `app-shell`. **Never** create a second sidebar.

---

## Panel Structure

Each navigable section is a `panel command-section` with a required `id` matching the nav anchor:

```html
<section class="panel command-section" id="section-name">
  <div class="panel-header hero-band">
    <div>
      <p class="eyebrow">Subtitle / category</p>
      <h1>Section Title</h1>
      <p class="hero-copy">One-sentence description.</p>
    </div>
    <div class="status-row">
      <!-- optional status-pill elements -->
    </div>
  </div>

  <!-- content: tables, forms, cards -->
</section>
```

---

## Navigation Items

Always use the `_nav_item(anchor, label, badge?)` helper. Do not write raw `<a>` tags in nav.

```python
_nav_item("section-name", "Display Label")           # basic
_nav_item("section-name", "Display Label", "42")     # with count badge
_nav_item("section-name", "Display Label", "!")      # with alert badge
```

The helper produces the correct `.nav-item` anchor and active-state JS.

---

## Tables

All tabular data uses `.data-table` inside a `.table-wrap` (for scroll on narrow screens).
Client-side search uses `.table-search` + `makeSearchFilter()`:

```html
<div class="table-search">
  <input type="search" id="my-search" placeholder="Filter..." />
</div>
<div class="table-wrap">
  <table class="data-table" id="my-table">
    <thead><tr><th>Col</th> ...</tr></thead>
    <tbody> ... </tbody>
  </table>
</div>
```

Wire search in the page `<script>`:
```js
makeSearchFilter('my-search', 'my-table');
```

---

## CSS Variables (do not hardcode colors)

| Variable                  | Purpose                         |
|---------------------------|---------------------------------|
| `--color-accent`          | Primary brand color             |
| `--color-accent-strong`   | Hover / active accent           |
| `--color-card`            | Card / panel background         |
| `--color-sidebar-start`   | Sidebar gradient top            |
| `--color-sidebar-end`     | Sidebar gradient bottom         |
| `--panel`                 | Semi-transparent panel surface  |
| `--nav-bg`                | Sidebar nav background          |
| `--nav-text`              | Sidebar text color              |
| `--nav-muted`             | Sidebar muted / secondary text  |

All values are set by `_base_styles()` from design tokens. Override in tokens, not in inline `style=`.

---

## Typography Classes

| Class          | Use                                   |
|----------------|---------------------------------------|
| `.eyebrow`     | Small caps section label above h1/h2  |
| `.hero-copy`   | Lead paragraph under heading          |
| `.card-copy`   | Body text inside cards                |
| `.mini-copy`   | Small secondary text                  |
| `.signal-copy` | Sidebar / nav descriptive text        |
| `.nav-label`   | Nav group section label               |

---

## Buttons

| Class                  | Use                              |
|------------------------|----------------------------------|
| `.button`              | Default primary action           |
| `.button-secondary`    | Secondary / cancel               |
| `.button-danger`       | Destructive action               |
| `.button-sm`           | Compact variant                  |

Buttons inside forms use `<button type="submit">`. Links that look like buttons use `<a class="button ...">`.

---

## Status Pills

```html
<span class="status-pill ok">Label value</span>
<span class="status-pill danger">Label value</span>
<span class="status-pill">Label value</span>   <!-- neutral -->
```

Use `.ok` for healthy/active, `.danger` for error/alert, bare for informational.

---

## What NOT to Do

- Do not use inline `style=` for colors, fonts, or spacing — use CSS variables and classes.
- Do not create full-page layouts outside `page-shell > app-shell`.
- Do not create a second sidebar or a horizontal top nav.
- Do not add new CSS that duplicates existing utility classes (`.stack`, `.grid`, `.panel`, `.signal-card`).
- Do not use raw `<table>` without `.data-table` class.
- Do not hardcode pixel colors — all colors must come from `--color-*` variables.

---

## Login Pages

Login, change-password, and error pages use `login-shell` instead of `page-shell`:

```html
<main class="login-shell">
  <div class="login-panel"> ... </div>
</main>
```

These pages have no sidebar.
