# Design direction

Audience: families who may be stressed and not fluent readers of English, and officers who work through long queues. Both need calm, plain, high-contrast screens.

- Type: system sans stack with a Devanagari fallback, 16px body, 1.6 line height, headings in a heavier weight. No web fonts (CSP is self-only and the page must load fast on weak links).
- Colour: deep teal as the one brand colour, a thin saffron and green rule under the header as a quiet reference to the national palette (UX4G convention), neutral greys, one warning red-brown. Status is never colour alone: every status has a text label.
- Spacing: 8px scale, generous card padding, one column on phones.
- Controls: 44px minimum tap height, visible 3px focus ring, labels always above fields.
- Motion: none beyond a colour transition, and none when reduced motion is requested.
- No gradient hero, no icon-card grid.
- Contrast: body text 4.5:1 or better, large text 3:1 or better; checked by script (scripts/contrast_check.py), not by eye.
- Widths checked: 360, 768 and 1280 with screenshots.
