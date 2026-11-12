/** Chips: small labels in a row. */

/** What a chip takes. */
export interface ChipProps {
  label: string;  // the text on the chip
}

/** Draw a chip; a component needs no comment on what it returns. */
export function Chip({ label }: ChipProps): JSX.Element {
  return { html: `<span>${label}</span>` };
}

/** Draw a line; it returns a string, not JSX, so it is no component, and its return needs a comment. */
export function Divider(): string {
  return "<hr>";
}

/** Draw two chips; a function with a small name is no component. */
export function chips(a: string,  // the first
                      b: string,  // the second
): string {
  return a + b;
}
