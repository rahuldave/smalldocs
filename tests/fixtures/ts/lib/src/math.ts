/** Add two numbers. */
export function add(a: number,      // the first number
                    b: number = 1,  // the second number
): number {                         // the sum
  return a + b;
}

/**
 * Scale a number.
 * @param x the number to scale
 * @param by how much to scale it
 * @returns the scaled number
 */
export function scale(x: number, by = 2) {
  return x * by;
}

/** Repeat a number as text. */
export const twice = (n: number,       // the number
                      label?: string,  // what goes before it
): string => `${label ?? ""}${n * 2}`;  // the text

/** Log a message. */
export function log(message: string): void {  // the message to log
  console.log(message);
}

export function bare(x: number) {
  return x;
}
