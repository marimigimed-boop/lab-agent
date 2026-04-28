# UI Verification Protocol (Playwright)

> Mandatory after any visual change. Claude executes automatically.

## Auto-Trigger Files
.tsx, .jsx, .vue, .svelte, .html, .ejs, .css, .scss, .sass,
.module.css, tailwind.config.*, globals.css, layout files

## Verification Sequence (7 Steps)
1. **Dev server** — check running (port 3000/5173/8080); start if not
2. **Navigate** — go to affected page; wait for full load
3. **Desktop screenshot** — 1440x900; check layout/spacing/colors
4. **Mobile screenshot** — 375x812; check no horizontal scroll, readable text, touch targets
5. **Tablet screenshot** — 768x1024; check layout reflows correctly
6. **Accessibility snapshot** — verify DOM structure, labels, roles
7. **Show to user** — "ნახე შედეგი — კარგად გამოიყურება?"

## Responsive Breakpoints
| Device | Width | Height |
|--------|-------|--------|
| iPhone SE | 375 | 667 |
| iPad | 768 | 1024 |
| Laptop | 1440 | 900 |

## What to Check per Screenshot
- No horizontal scrollbar
- Text readable (min 14px mobile, 16px desktop)
- Touch targets ≥ 44x44px on mobile
- Navigation accessible
- Images scale proportionally
- No overlapping elements

## Accessibility Checks
- Every <img> has alt attribute
- One <h1> per page; headings don't skip levels
- All interactive elements have visible focus indicators
- Modals trap focus; Escape closes them
- Tab order is logical (left→right, top→bottom)

## Console & Network
- Zero console errors expected
- No failed network requests (4xx/5xx)
- No broken images or resources

## Before/After Comparison
For modifications to existing UI:
1. Take "before" screenshots at all 3 viewports
2. Make changes
3. Take "after" screenshots
4. Show both to user: "ასე გამოიყურებოდა → ასე გამოიყურება ახლა"
