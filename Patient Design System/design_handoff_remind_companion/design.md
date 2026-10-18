# Calm — Design System

A companion screen for people living with dementia. The screen shows a soft sky-to-meadow gradient, and sometimes a photo or a few words. Nothing else.

## Elements

The UI has exactly three elements. Never add any others.

### 1. Ground (always on)
Full-screen vertical gradient. Soft morning sky fading into a pale meadow.

```css
background: linear-gradient(180deg, rgb(214,232,240) 0%, rgb(230,239,216) 100%);
```

### 2. Words
- Font: **Atkinson Hyperlegible Next** (Google Fonts, weights 400 and 600). It was designed for low vision: open shapes, no easily confused letters.
- Ink: `#1E2B26` (deep pine). Contrast is 11.7:1 on the sky stop and 12.4:1 on the meadow stop.
- Always centered, `text-wrap: balance`.

| Style   | Size / line-height | Weight | Use                      |
|---------|--------------------|--------|--------------------------|
| Message | 64px / 80px (1.25) | 600    | Standalone sentence      |
| Caption | 40px / 54px (1.35) | 400    | Line beneath a photo     |

On a 1440px-wide screen. Scale with viewport: Message = 4.44vw, Caption = 2.78vw.

### 3. Photos
- One at a time, centered.
- Corner radius: 32px.
- Shadow: `0 24px 60px rgba(30,43,38,0.14)`.
- No frames, overlays, borders or controls.
- Size: about 56% of screen width when alone, about 46% when paired with a caption.

## Screens

1. **Rest:** gradient only. The default state; most of the day looks like this.
2. **Message:** one short sentence, centered. 12 words at most. Horizontal padding of 10% of the screen width.
3. **Photo:** a single photo, centered.
4. **Photo + caption:** photo, then caption below. The gap is 4% of the screen width.

## Motion
- All changes fade in and out over **1200ms ease-in-out**.
- Never slide, bounce, flash or animate the gradient abruptly.

## Rules
1. Only the gradient, a photo, and words. No buttons, icons, clocks or badges.
2. One thing on screen at a time.
3. Change slowly. Fade over 1.2 seconds; never slide or flash.
4. Write warmly, in the present tense, using names. Never test or correct.
5. Text is always ink on the gradient. Never place text over a photo.

## Nurse setup screen (caregiver only)
The only screen with controls. It looks like a small physical device sitting on the gradient, with a light stone faceplate, recessed wells and raised keys. The patient never sees it.

- **Faceplate:** `linear-gradient(180deg,#F1F3EE,#E0E4DB)`, radius 36px, padding 44px, max-width 640px. Inner top highlight `inset 0 1px 0 #FFF`, shadow `0 30px 60px rgba(30,43,38,0.16)`.
- **Header:** title 32px/600, with a 3×3 speaker grille (6px dots, `#59605B`) and a power light on the right.
- **Text field:** recessed well (padding 5px, radius 18px, `linear-gradient(180deg,#CDD2C8,#F5F7F2)`). The field inside has radius 14px, height 62px, `#F8F9F5`, `inset 0 2px 5px rgba(30,43,38,0.22)` and 26px text.
- **Toggle keys (Games):** a recessed well matching the Start key (`linear-gradient(180deg,#C6CBC1,#F5F7F2)`, radius 24px, padding 6px, gap 6px) holding four keys. Each key is 112px tall with radius 18px.
  - On: green pressed key `linear-gradient(180deg,#5A9A76,#3D7457)`.
  - Off: grey raised key `linear-gradient(180deg,#D9DCD6,#B9BEB6)`.
  - Disabled: off state at 45% opacity, not clickable, label `#7A817C`. Reorder is disabled until the robot is connected.
  - Each key has a centered 44px line icon (1.8px stroke): white when on, `#5E655F` when off. Icons: smiling face (Famous faces), speech bubble (Sayings), speaker (Sounds), up/down arrows (Reorder).
  - Labels sit below the tray, 18px, centered.
- **Primary key (Start):** a pine key `linear-gradient(180deg,#4C8A68,#2F6248)`, 84px tall, radius 20px, 30px/600 white text. It sits in a 6px recessed well and presses down 2px on click.
- **Secondary text:** 18px, `#4A524D`.
- After Start, show the calm view only. Esc returns to setup.

## Copy examples
- "Good morning, Margaret."
- "This is you and Tom at the lake."

## Tokens

```css
@import url("https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;600&display=swap");

:root {
  --ground-top: rgb(214,232,240);
  --ground-bottom: rgb(230,239,216);
  --ground: linear-gradient(180deg, var(--ground-top) 0%, var(--ground-bottom) 100%);
  --ink: #1E2B26;
  --font: "Atkinson Hyperlegible Next", system-ui, sans-serif;
  --text-message: 600 64px/1.25 var(--font);
  --text-caption: 400 40px/1.35 var(--font);
  --photo-radius: 32px;
  --photo-shadow: 0 24px 60px rgba(30,43,38,0.14);
  --fade: 1200ms ease-in-out;
}
```
