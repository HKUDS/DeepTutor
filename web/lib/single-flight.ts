/**
 * Wrap an async loader so concurrent calls share one in-flight request.
 * Arguments from later callers are intentionally ignored until that request
 * settles; the next call starts a fresh request with its own arguments.
 */
export function createSingleFlight<Args extends unknown[], Result>(
  loader: (...args: Args) => Promise<Result>,
): (...args: Args) => Promise<Result> {
  let inFlight: Promise<Result> | null = null;

  return (...args: Args) => {
    if (inFlight) return inFlight;

    const request = loader(...args);
    inFlight = request;
    const clear = () => {
      if (inFlight === request) inFlight = null;
    };
    void request.then(clear, clear);
    return request;
  };
}
