/** Format a count as a badge's text. */
export function badgeText(n: number,  // how many
): string {                           // the text
  return n > 99 ? "99+" : String(n);
}
