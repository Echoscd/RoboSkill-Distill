// Minimal block-style YAML emitter for plain data (objects, arrays, scalars).
// Produces conventional block layout for readable profiles.

const PLAIN = /^[A-Za-z0-9_][A-Za-z0-9_ .\/+()\-]*$/

function scalar(value: unknown): string {
  if (value === null || value === undefined) return "null"
  if (typeof value === "number" || typeof value === "boolean") return String(value)
  const text = String(value)
  if (text === "???") return "'???'"
  if (text === "") return "''"
  // Quote anything that could be misparsed: reserved words, numbers, structure
  // characters, or leading/trailing whitespace.
  if (
    !PLAIN.test(text) ||
    /^(true|false|null|yes|no|on|off|~)$/i.test(text) ||
    /^[-+]?[0-9.]/.test(text) ||
    text.trim() !== text
  )
    return `"${text.replace(/\\/g, "\\\\").replace(/"/g, '\\"')}"`
  return text
}

function isPlainObject(value: unknown): value is Record<string, unknown> {
  return typeof value === "object" && value !== null && !Array.isArray(value)
}

function emit(value: unknown, indent: number): string[] {
  const pad = "  ".repeat(indent)
  if (Array.isArray(value)) {
    if (value.length === 0) return [`${pad}[]`]
    return value.flatMap((item) => {
      if (isPlainObject(item) || Array.isArray(item)) {
        const lines = emit(item, indent + 1)
        const first = lines[0]!.slice(pad.length + 2)
        return [`${pad}- ${first}`, ...lines.slice(1)]
      }
      return [`${pad}- ${scalar(item)}`]
    })
  }
  if (isPlainObject(value)) {
    const entries = Object.entries(value).filter(([, item]) => item !== undefined)
    if (entries.length === 0) return [`${pad}{}`]
    return entries.flatMap(([key, item]) => {
      if (Array.isArray(item) && item.length === 0) return [`${pad}${scalar(key)}: []`]
      if (isPlainObject(item) && Object.keys(item).length === 0) return [`${pad}${scalar(key)}: {}`]
      if (isPlainObject(item) || Array.isArray(item)) return [`${pad}${scalar(key)}:`, ...emit(item, indent + 1)]
      return [`${pad}${scalar(key)}: ${scalar(item)}`]
    })
  }
  return [`${pad}${scalar(value)}`]
}

export function toYaml(value: unknown): string {
  return emit(value, 0).join("\n") + "\n"
}
