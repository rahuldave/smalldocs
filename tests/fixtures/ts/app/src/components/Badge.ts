/**
 * Badge: a small label with a tone.
 *
 * Pages use it beside a name.
 */
import { shout } from "../utils/format";

interface Props {
  text: string;  // the words on the badge
  /** How it looks. */
  tone?: "info" | "warn";
  loud?: boolean;
  onPick?: (text: string,
            at: number) => void;  // what a click does
}

/** Draw a badge. */
export default function Badge({ text, tone = "info",
                                loud = false }: Props): JSX.Element {  // the HTML of the badge
  return { html: `<span class="${tone}">${loud ? shout(text) : text}</span>` };
}
