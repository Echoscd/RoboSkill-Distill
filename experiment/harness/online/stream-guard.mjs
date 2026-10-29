const DEFAULTS = Object.freeze({
  maxToolArgumentChars: 8192,
  maxRepeatUnitChars: 64,
  minRepeatCount: 12,
  minRepeatedChars: 192,
})

const PROTECTED_KINEX_PATH = /(?:^|[\\/])\.kinex[\\/](?:devices|tools)(?:[\\/]|$)|(?:^|[\\/])\.kinex[\\/]workspace\.yaml(?:$|\s)/i
const DESTRUCTIVE_SHELL = /(?:^|[;&|]\s*|\s)(?:rm|rmdir|mv|unlink|truncate)\s|\bfind\b[^\n;&|]*\s-delete(?:\s|$)/i

export function protectedFilesystemMutation(event) {
  if (event?.type !== "tool_execution_start") return null
  if (event.toolName === "bash") {
    const command = event.args?.command
    if (typeof command === "string" && PROTECTED_KINEX_PATH.test(command) && DESTRUCTIVE_SHELL.test(command))
      return {
        reason: "protected_kinex_path_mutation",
        tool: "bash",
        call_id: event.toolCallId,
        command_chars: command.length,
      }
  }
  if ((event.toolName === "write" || event.toolName === "edit")
    && typeof event.args?.path === "string" && PROTECTED_KINEX_PATH.test(event.args.path))
    return {
      reason: "protected_kinex_path_mutation",
      tool: event.toolName,
      call_id: event.toolCallId,
      path: event.args.path,
    }
  return null
}

function repeatedSuffix(value, options) {
  const maximum = Math.min(options.maxRepeatUnitChars, Math.floor(value.length / options.minRepeatCount))
  for (let width = 1; width <= maximum; width += 1) {
    const unit = value.slice(-width)
    let count = 1
    for (let end = value.length - width; end >= width; end -= width) {
      if (value.slice(end - width, end) !== unit) break
      count += 1
    }
    if (count >= options.minRepeatCount && count * width >= options.minRepeatedChars)
      return { unit, unit_chars: width, repeat_count: count, repeated_chars: count * width }
  }
  return null
}

export class ModelStreamGuard {
  constructor(options = {}) {
    this.options = { ...DEFAULTS, ...options }
    this.toolArguments = new Map()
    this.tripped = null
  }

  observe(event) {
    if (this.tripped) return null
    if (event?.type === "message_start" && event.message?.role === "assistant") {
      this.toolArguments.clear()
      return null
    }
    if (event?.type === "message_end") {
      this.toolArguments.clear()
      return null
    }
    if (event?.type !== "message_update") return null
    const update = event.assistantMessageEvent
    if (update?.type !== "toolcall_delta" || typeof update.delta !== "string") return null
    const index = update.contentIndex ?? 0
    const value = `${this.toolArguments.get(index) ?? ""}${update.delta}`
    this.toolArguments.set(index, value)

    if (value.length > this.options.maxToolArgumentChars) {
      this.tripped = {
        reason: "tool_argument_limit",
        content_index: index,
        chars: value.length,
        limit: this.options.maxToolArgumentChars,
      }
      return this.tripped
    }
    const repetition = repeatedSuffix(value, this.options)
    if (repetition) {
      this.tripped = {
        reason: "repeated_tool_argument_suffix",
        content_index: index,
        chars: value.length,
        ...repetition,
      }
      return this.tripped
    }
    return null
  }
}

export function attachModelStreamGuard(session, ledger, options = {}) {
  const guard = new ModelStreamGuard(options)
  let aborting = false
  let filesystemDecision = null
  const unsubscribe = session.subscribe(event => {
    filesystemDecision ??= protectedFilesystemMutation(event)
    const decision = filesystemDecision ?? guard.observe(event)
    if (!decision || aborting) return
    aborting = true
    void ledger.append(filesystemDecision ? "filesystem.guard" : "model_stream.guard", {
      decision: "abort",
      ...decision,
    })
    void session.abort()
  })
  return {
    dispose: unsubscribe,
    get tripped() { return filesystemDecision ?? guard.tripped },
  }
}

