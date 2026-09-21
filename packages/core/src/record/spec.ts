import type { DeviceSpec } from "./recorder.ts"

export function parseSpec(raw: string | number): DeviceSpec | string {
  const rate = Number(raw)
  if (!String(raw).trim() || !Number.isFinite(rate) || rate <= 0) return `${raw}: expected a positive rate in Hz`
  return { rate }
}

export function parseSpecs(tokens: string[]): { specs: Record<string, DeviceSpec>; instruction: string } {
  const specs: Record<string, DeviceSpec> = {}
  const index = tokens.findIndex((token) => !token.includes("="))
  const heads = index === -1 ? tokens : tokens.slice(0, index)
  for (const token of heads) {
    const [name = "", raw = "", ...extra] = token.split("=")
    const spec = parseSpec(raw)
    if (!name || extra.length || typeof spec === "string") throw new Error(`${token}: expected <device>=<rate in Hz>, e.g. arm=10 or cam=2`)
    specs[name] = spec
  }
  return { specs, instruction: (index === -1 ? [] : tokens.slice(index)).join(" ") }
}
