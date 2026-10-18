# Handoff: ReMind Companion (Calm design system + Nurse Setup)

## Overview
ReMind Companion is a screen for people living with dementia. It has two modes:
1. **Nurse Setup**: a caregiver-only screen for entering the patient's name and choosing which games to run.
2. **Calm view**: what the patient sees. It shows only a soft gradient, a photo and/or a short line of text. There are no controls.

## About the design files
The HTML files in this bundle are **design references**. They are prototypes that show the intended look and behaviour, not production code to copy. Recreate them in the target codebase using its existing framework and patterns. If no codebase exists yet, choose an appropriate framework (for example React, or SwiftUI for a tablet app) and implement the designs there. The `.dc.html` files run in a browser with `support.js` alongside them. Every style is written inline, so you can read exact values directly from the markup.

## Fidelity
**High fidelity.** Colours, type, spacing, radii and shadows are final. Recreate them pixel-perfectly.

---

## Design tokens

### Colour
| Token | Value | Use |
|---|---|---|
| ground-top | `rgb(214,232,240)` / `#D6E8F0` | Gradient top (sky) |
| ground-bottom | `rgb(230,239,216)` / `#E6EFD8` | Gradient bottom (meadow) |
| ground | `linear-gradient(180deg, ground-top 0%, ground-bottom 100%)` | Full-screen background, always on |
| ink | `#1E2B26` | All primary text. 11.7:1 contrast on the top stop, 12.4:1 on the bottom |
| ink-muted | `#4A524D` | Form labels, helper text |
| ink-label | `#2F3833` | Game key labels |
| ink-disabled | `#7A817C` | Disabled labels |
| placeholder | `#8A928C` | Input placeholder |
| face-top / face-bottom | `#F1F3EE` / `#E0E4DB` | Device faceplate gradient |
| well-top / well-bottom | `#C6CBC1` / `#F5F7F2` | Recessed wells (game tray, Start) |
| field-well-top | `#CDD2C8` | Recessed well around the text field (bottom is `#F5F7F2`) |
| field | `#F8F9F5` | Text field fill |
| green-key | `#5A9A76` → `#3D7457` | Active game key |
| grey-key | `#D9DCD6` → `#B9BEB6` | Inactive game key |
| primary | `#4C8A68` → `#2F6248` | Start key |
| icon-off | `#5E655F` | Icon on an inactive key |
| grille | `#59605B` | Speaker-grille dots |
| power-led | `#6EE7A0` | Power indicator |

### Typography
Font: **Atkinson Hyperlegible Next** (Google Fonts, weights 400 and 600), fallback `system-ui, sans-serif`. Use `-webkit-font-smoothing: antialiased`.

| Style | Size / line-height | Weight | Notes |
|---|---|---|---|
| Message (calm) | 64px / 1.25 | 600 | On a 1440px screen. Fluid: `max(40px, 4.44vw)`. Centered, `text-wrap: balance` |
| Caption (calm) | 40px / 1.35 | 400 | Fluid: `2.78vw`. Below a photo |
| Device title | 32px | 600 | letter-spacing −0.01em, text-shadow `0 1px 0 rgba(255,255,255,0.8)` |
| Start label | 30px | 600 | White, text-shadow `0 -1px 0 rgba(0,0,0,0.25)` |
| Input text | 26px | 400 | |
| Label / helper | 18px / 1.3–1.5 | 400 | |

### Radii
Faceplate 36 · Start well 26 · Game tray 24 · Text field well 18 · Game key 18 · Start key 20 · Text field 14 · Photo 32

### Shadows
- Faceplate: `inset 0 1px 0 #FFFFFF, inset 0 -2px 0 rgba(30,43,38,0.06), 0 2px 4px rgba(30,43,38,0.12), 0 30px 60px rgba(30,43,38,0.16)`
- Well: `inset 0 1px 2px rgba(30,43,38,0.2)`
- Text field: `inset 0 2px 5px rgba(30,43,38,0.22), inset 0 0 0 1px rgba(30,43,38,0.08)`
- Active game key: `inset 0 1px 0 rgba(255,255,255,0.3), inset 0 -3px 0 rgba(0,0,0,0.15), 0 2px 4px rgba(30,43,38,0.3)`
- Inactive game key: `inset 0 1px 0 rgba(255,255,255,0.8), inset 0 -2px 0 rgba(0,0,0,0.1), 0 2px 3px rgba(30,43,38,0.3)`
- Start key: `inset 0 1px 0 rgba(255,255,255,0.35), inset 0 -3px 0 rgba(0,0,0,0.18), 0 3px 6px rgba(30,43,38,0.35)`
- Start key (pressed): `inset 0 2px 6px rgba(0,0,0,0.3), 0 1px 2px rgba(30,43,38,0.3)`, plus `translateY(2px)`
- Photo: `0 24px 60px rgba(30,43,38,0.14)`
- Grille dot: `inset 0 1px 1px rgba(0,0,0,0.6), 0 1px 0 #fff`
- Power LED glow: `0 0 10px rgba(110,231,160,0.9), 0 0 2px rgba(110,231,160,1)`

### Motion
All calm-view changes cross-fade over **1200ms ease-in-out**. No slides, bounces or flashes.

---

## Screen 1: Nurse Setup
**Purpose:** the caregiver enters the patient's first name, picks games and starts the session.

**Layout**
- Viewport: `min-height: 100vh`, `ground` gradient background, padding 48px 20px, content centered both ways.
- Faceplate: width 100%, max-width 640px, padding 44px 44px 36px, vertical flex, gap 32px.

**Components, top to bottom**
1. **Header row:** flex, space-between, gap 16px.
   - Title "ReMind Companion".
   - Right cluster (flex, gap 18px): a 3×3 grid of 6px dots (gap 5px) forming a speaker grille, then a 10px power LED.
2. **Name field:** label "Patient's first name" (18px, ink-muted), gap 12px.
   - Well: padding 5px, radius 18, `linear-gradient(180deg,#CDD2C8,#F5F7F2)`.
   - Input: height 62px, padding 0 20px, radius 14, no border or outline, placeholder "First name", default value "Rose".
3. **Games:** label "Games", gap 12px.
   - Tray: padding 6px, radius 24, well gradient, a 4-column grid (`minmax(0,1fr)`) with gap 6px.
   - Keys: height 112px, radius 18, no border, a 44px icon centered.
     - On: green-key gradient, icon `#FFFFFF`.
     - Off: grey-key gradient, icon `#5E655F`.
     - Disabled: Off style at `opacity: 0.45`, `cursor: not-allowed`, not clickable, label ink-disabled.
   - Labels: a separate 4-column grid below the tray (gap 6px, padding 0 6px), 18px/1.3, centered, `text-wrap: balance`.
   - Games, in order:
     - Famous faces: smiling-face icon, on by default
     - Sayings: speech-bubble icon, on by default
     - Sounds: speaker icon, on by default
     - Reorder (needs the robot): up/down-arrows icon, **disabled** until a robot is connected
   - Icons are 24×24 viewBox, `fill:none`, stroke-width 1.8, round caps and joins. Path data:
     - Famous faces: `M12 3a9 9 0 1 0 0 18a9 9 0 1 0 0-18Z M8.5 14.5c1 1.3 2.2 2 3.5 2s2.5-.7 3.5-2 M9 9.5h.01 M15 9.5h.01`
     - Sayings: `M21 12a8 8 0 0 1-11.6 7.1L4 20.5l1.4-4.6A8 8 0 1 1 21 12Z`
     - Sounds: `M11 5 6 9H3v6h3l5 4V5Z M15.5 8.5a5 5 0 0 1 0 7 M18.5 5.5a9 9 0 0 1 0 13`
     - Reorder: `M7 4v16 M3 8l4-4 4 4 M17 20V4 M13 16l4 4 4-4`
4. **Start:** well with padding 6px, radius 26, well gradient. The key is full width, 84px tall, radius 20, primary gradient, label "Start".
5. **Helper text:** "After Start, the screen shows only the calm view. Press Esc to come back here." (18px/1.5, ink-muted).

## Screen 2: Calm view (patient)
- Full screen, `ground` gradient. Show **one thing at a time**, always centered.
- **Rest:** gradient only. This is the default state.
- **Message:** a single sentence of 12 words or fewer, in Message style. Horizontal padding is 10vw.
- **Photo:** about 56% of screen width, radius 32, photo shadow.
- **Photo + caption:** photo at about 46% width, then the caption below it with a 4vw gap.
- Never show buttons, icons, clocks or badges. Never put text over a photo. Copy should be warm, in the present tense and use names, for example "Good morning, Margaret." or "This is you and Tom at the lake." It must never test or correct the patient.

## Interactions & state
- `name: string` (default "Rose") is bound to the input.
- `games: { faces, sayings, sounds, reorder }` as booleans. Clicking a key toggles it. A disabled key ignores clicks and always renders Off.
- `reorderAvailable: boolean` stays false until a robot is connected. When true, Reorder behaves like the other keys.
- `started: boolean`. Start sets it to true and swaps to the calm view (fullscreen is recommended). **Esc** sets it back to false and returns to Setup.
- The prototype greets the patient with "Hello, {name}." in the calm view. That greeting is placeholder copy; real content comes from the selected games.
- Accessibility: game keys are `<button aria-pressed>`, icons are `aria-hidden`, and the label element wraps the name input.

## Files
- `Nurse Setup.dc.html`: interactive Setup prototype plus calm view (open it in a browser next to `support.js`)
- `Calm Design System.dc.html`: design system specimen covering ground, type, photos, the four calm screens and the rules
- `styles.css`: CSS custom properties for the calm tokens
- `design.md`: a short version of this spec
- `image-slot.js`: photo-placeholder helper used only by the specimen page (not needed in production)

## Assets
- Font: Atkinson Hyperlegible Next (Google Fonts)
- Icons: the inline SVG paths listed above
- Photos: supplied by the family or caregiver at runtime; none are bundled
