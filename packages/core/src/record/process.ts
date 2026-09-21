import { NamedError } from "../util/error.ts"

export class CaptureError extends NamedError {
  constructor(message: string) { super("CaptureError", message) }
}

export const reason = (error: unknown) => error instanceof Error ? error.message : String(error)

export async function deadline<T>(promise: Promise<T>, ms: number, message: string): Promise<T> {
  const timer: { value?: ReturnType<typeof setTimeout> } = {}
  return Promise.race([
    promise,
    new Promise<never>((_, reject) => { timer.value = setTimeout(() => reject(new CaptureError(message)), ms) }),
  ]).finally(() => clearTimeout(timer.value))
}

// Drain while the process runs; never accumulate an unbounded stderr pipe.
export async function diagnostics(stream: ReadableStream<Uint8Array>, output: { text: string }) {
  const reader = stream.getReader()
  for (;;) {
    const chunk = await reader.read()
    if (chunk.done) return
    output.text = (output.text + new TextDecoder().decode(chunk.value)).slice(-8192)
  }
}
