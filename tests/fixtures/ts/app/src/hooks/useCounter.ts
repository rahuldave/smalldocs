/** What `useCounter` gives back. */
export interface Counter<T> {
  value: number;  // the count now
  last: T | null;  // the last thing counted
  bump: (by?: number) => void;  // add to the count
}

/** Count things as they come. */
export function useCounter<T>(start = 0,  // where the count begins
                              step: number = 1,
): Counter<T> {
  let value = start;
  return { value, last: null, bump: (by = step) => { value += by; } };
}
