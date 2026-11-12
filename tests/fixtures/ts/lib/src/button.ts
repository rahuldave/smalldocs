/** What a button takes. */
export interface ButtonProps {
  label: string;  // the text on it
  onClick?: () => void;  // what a click does
  disabled?: boolean;  // whether it is grey
}

/** A button, as a string of HTML. */
export function Button({ label, disabled = false }: ButtonProps): string {  // the HTML
  return `<button${disabled ? " disabled" : ""}>${label}</button>`;
}
