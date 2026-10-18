// App-wide events so windows stay in step: a transfer in one window refreshes the others.
export const bus = new EventTarget();

export function emit(name, detail = null) {
  bus.dispatchEvent(new CustomEvent(name, { detail }));
}

/** Listen until `until` (an AbortSignal) fires, typically when the window closes. */
export function on(name, fn, until) {
  bus.addEventListener(name, fn, { signal: until });
}
