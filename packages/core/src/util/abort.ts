// The resource owner cancels the process or queued work; this releases waiters.
export function abortable<T>(work: Promise<T>, signal?: AbortSignal): Promise<T> {
  if (!signal) return work
  const { promise, resolve, reject } = Promise.withResolvers<T>()
  const abort = () => reject(signal.reason)
  signal.addEventListener("abort", abort, { once: true })
  if (signal.aborted) abort()
  work.then(resolve, reject)
  return promise.finally(() => signal.removeEventListener("abort", abort))
}
