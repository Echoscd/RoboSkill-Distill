import { spawn } from "node:child_process"
import { once } from "node:events"
import { mkdtemp, readFile, rm, stat, writeFile } from "node:fs/promises"
import { homedir, tmpdir } from "node:os"
import { basename, join, resolve } from "node:path"
import { fileURLToPath } from "node:url"

function absolutePath(file: string): string {
  return resolve(file.startsWith("~/") ? join(homedir(), file.slice(2)) : file)
}

async function runExporter(input: string, output: string, signal: AbortSignal): Promise<number> {
  signal.throwIfAborted()
  const child = spawn(process.execPath, [fileURLToPath(new URL("./export-worker.js", import.meta.url)), "--export", input, output], {
    stdio: ["ignore", "ignore", "inherit"],
  })
  let force: ReturnType<typeof setTimeout> | undefined
  const stop = () => {
    child.kill("SIGTERM")
    force = setTimeout(() => child.kill("SIGKILL"), 1000)
  }
  signal.addEventListener("abort", stop, { once: true })
  try {
    const [code] = await once(child, "close")
    return typeof code === "number" ? code : 1
  } finally {
    signal.removeEventListener("abort", stop)
    clearTimeout(force)
  }
}

export async function exportSession(source: string, destination?: string): Promise<number> {
  const input = absolutePath(source)
  const displayedOutput = destination ?? `pi-session-${basename(input, ".jsonl")}.html`
  const output = absolutePath(displayedOutput)
  const controller = new AbortController()
  let interrupted = 0
  const interrupt = (code: number) => { interrupted = code; controller.abort() }
  const onInterrupt = () => interrupt(130)
  const onTerminate = () => interrupt(143)
  process.once("SIGINT", onInterrupt)
  process.once("SIGTERM", onTerminate)
  let temporary: string | undefined
  try {
    const inputStat = await stat(input)
    const outputStat = await stat(output).catch((error: unknown) => {
      if (error instanceof Error && "code" in error && error.code === "ENOENT") return undefined
      throw error
    })
    if (input === output || (outputStat && inputStat.dev === outputStat.dev && inputStat.ino === outputStat.ino)) {
      throw new Error("Export output must not refer to the input session")
    }
    const contents = await readFile(input)
    if (!contents.toString("utf8").trim()) throw new Error(`Session file is empty: ${source}`)
    temporary = await mkdtemp(join(tmpdir(), "kinex-export-"))
    const copy = join(temporary, "session.jsonl")
    await writeFile(copy, contents, { mode: 0o600 })
    if (interrupted) return interrupted
    // SessionManager may migrate older files in place. Only give Pi our copy.
    const code = await runExporter(copy, output, controller.signal)
    if (interrupted) return interrupted
    if (code === 0) console.log(`Exported to: ${displayedOutput}`)
    return code
  } finally {
    try {
      if (temporary) await rm(temporary, { recursive: true, force: true })
    } finally {
      process.off("SIGINT", onInterrupt)
      process.off("SIGTERM", onTerminate)
    }
  }
}
