import type { ManagedProcess } from "../util/process.ts"
import { lineSource } from "../util/lines.ts"

export interface ServeProcess {
  proc: ManagedProcess
  source: ReturnType<typeof lineSource>
  stderr: { tail: string }
  stopping?: Promise<void>
}

// Drain continuously: an unread stderr pipe can block the driver's SDK calls.
// Keep only a bounded tail, including logs without newlines.
export function serveProcess(proc: ServeProcess["proc"]): ServeProcess {
  const stderr = { tail: "" }
  void (async () => {
    const decoder = new TextDecoder()
    const reader = proc.stderr.getReader()
    for (;;) {
      const { done, value } = await reader.read()
      if (done) break
      stderr.tail = (stderr.tail + decoder.decode(value, { stream: true })).slice(-16_384)
    }
    stderr.tail = (stderr.tail + decoder.decode()).slice(-16_384)
  })().catch(() => {})
  return { proc, source: lineSource(proc.stdout), stderr }
}

// EOF lets the driver release its connection and recorder. Bound cleanup time,
// then force termination; replacement must await actual exit.
export function terminate(entry: ServeProcess, graceful = false): Promise<void> {
  entry.stopping ??= (async () => {
    if (graceful) entry.proc.stdin.end()
    if (!graceful) entry.proc.kill()
    const timer = graceful ? setTimeout(() => entry.proc.kill(), 5000) : undefined
    await entry.proc.exited.finally(() => {
      clearTimeout(timer)
      entry.proc.kill("SIGKILL") // also reap any surviving owned children
    })
  })()
  return entry.stopping
}
