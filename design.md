# Calm — Design System

A companion screen for people living with dementia. The screen shows a warm gradient, and sometimes a photo or a few words. Nothing else.

## Elements

The UI has exactly three elements. Never add any others.

### 1. Ground (always on)
Full-screen vertical gradient. Source: Figma frame "Desktop - 1" (1440×1024).

```css
background: linear-gradient(180deg, rgb(255,144,54) 0%, rgb(230,235,208) 100%);
```

### 2. Words
- Font: **Atkinson Hyperlegible Next** (Google Fonts, weights 400 and 600). It was designed for low vision: open shapes, no easily confused letters.
- Ink: `#2A1A0E` (deep warm brown). Contrast is 7.6:1 on the orange stop and 14:1 on the sage stop.
- Always centered, `text-wrap: balance`.

| Style   | Size / line-height | Weight | Use                      |
|---------|--------------------|--------|--------------------------|
| Message | 64px / 80px (1.25) | 600    | Standalone sentence      |
| Caption | 40px / 54px (1.35) | 400    | Line beneath a photo     |

On a 1440px-wide screen. Scale with viewport: Message = 4.44vw, Caption = 2.78vw.

### 3. Photos
- One at a time, centered.
- Corner radius: 32px.
- Shadow: `0 24px 60px rgba(42,26,14,0.18)`.
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

## Copy examples
- "Good morning, Margaret."
- "This is you and Tom at the lake."

## Tokens

```css
@import url("https://fonts.googleapis.com/css2?family=Atkinson+Hyperlegible+Next:wght@400;600&display=swap");

:root {
  --ground-top: rgb(255,144,54);
  --ground-bottom: rgb(230,235,208);
  --ground: linear-gradient(180deg, var(--ground-top) 0%, var(--ground-bottom) 100%);
  --ink: #2A1A0E;
  --font: "Atkinson Hyperlegible Next", system-ui, sans-serif;
  --text-message: 600 64px/1.25 var(--font);
  --text-caption: 400 40px/1.35 var(--font);
  --photo-radius: 32px;
  --photo-shadow: 0 24px 60px rgba(42,26,14,0.18);
  --fade: 1200ms ease-in-out;
}
```
