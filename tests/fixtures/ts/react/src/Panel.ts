/** Panels: boxes that hold other parts. No import follows this comment. */

/** What every panel takes. */
export interface PanelProps {
  title: string;  // the words at the top
  wide?: boolean;  // whether it fills the row
}

/**
 * A panel with a footer; its props join `PanelProps` and its own.
 * @param props.footer the words at the bottom
 */
export function FooterPanel({ title, wide = false, footer }: PanelProps & { footer?: string }): JSX.Element {
  return { html: title + wide + footer };
}

/**
 * A tag, with its props on one line.
 * @param text the words on the tag
 * @param props.color its colour
 */
export function Tag({ text, color }: { text: string; color: string }): JSX.Element {
  return { html: text + color };
}

/** The page's frame; it takes no props. */
export function Frame(): JSX.Element | null {
  return { html: "" };
}

/** A box: two fields on one line share one comment, which is neither's. */
export interface Box { width: number; height: number }  // the size

/** Draw a box. */
export function BoxView({ width, height }: Box): JSX.Element {
  return { html: `${width}x${height}` };
}

/** A title: it takes a string, not a props object, so it is no component. */
export function Title(text: string,  // the words
): JSX.Element {
  return { html: text };
}
