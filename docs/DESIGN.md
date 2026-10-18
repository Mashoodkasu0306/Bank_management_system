# Design

## Look
Dark navy sidebar, white top bar, light grey page, white rounded cards. Calm, banking style, readable on a phone.

## Colors (variables in static/css/app.css)
- Navy #0f1b2d (sidebar, theme color), navy 2 #16263d, ink #111827, muted #6b7280, line #e5e7eb, page background #f4f6fa.
- Accent blue #2563eb (soft #dbeafe).
- OK green #047857 (soft #d1fae5), warning #b45309 (soft #fef3c7), bad red #b91c1c (soft #fee2e2).
- Radius 12px. Sidebar width 256px. Font: Inter or the system font.

## Layout
- Shell in templates/base.html: sidebar, top bar, back bar (Back + Dashboard on every inner page), page area, messages.
- Under 900px the sidebar becomes a slide-out menu. Under 700px tables scroll sideways inside their own box. Under 600px grids become one column.
- Touch targets are at least 44px high.

## Components (classes)
- Cards and layout: card, card-head, grid grid-2/3/4, cards-grid, page-head, kv and kv-grid (label and value rows).
- Numbers: stat-box, stat-label, stat-value, kpi-grid and kpi (clickable counts).
- Status: badge with badge-ok, badge-warn, badge-bad, badge-info; notice with notice-bad, notice-ok, notice-info.
- Buttons: btn, btn-primary, btn-danger, btn-sm, btn-block, row-actions, inline-form.
- Navigation: chips and chip (filter chips, chip-on = active), tile and tiles (link lists), quick (big action tiles), svc (service rows), back-link.
- Forms: form-card (labelled fields in a card), field, filter-bar, choice-row and choice (radio buttons as boxes).
- Tables: plain tables are styled automatically; use thead, tbody and a td.empty row for "nothing here".
- Special: bubble (support messages), progress (bars), vcard (virtual ATM card, partial virtual_card.html).

## Rules
- Status colors: green = good or done, amber = waiting, red = problem or rejected, blue = information.
- Money shows with the rupee sign and two decimals (floatformat:2 for sums).
- No fake numbers: show only values that come from the data.
- Keep inline styles for the bar widths only.

## PWA
- Name "Apex Core Banking", short name "Apex Bank", navy theme, icons in static/pwa.
- Install button in the sidebar footer (shown when the browser allows installing).
- Offline page is public and shows no personal details.