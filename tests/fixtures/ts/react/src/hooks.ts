/** Keep a value, and give a setter. */
export function useValue(start: string,  // the first value
): (
  v: string,  // the new value
) => void {  // the setter
  return (v) => { start = v; };
}

/** Make a point. */
export function point(x: number,  // across
): {
  x: number;  // the x
} {  // the point
  return { x };
}

/** Make a pair. */
export const pair = (a: number,  // the first
): [number, number] => [a, a];  // the pair
