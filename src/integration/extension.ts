import { readFile } from "node:fs/promises"
import { Type } from "typebox"
import { Text } from "@earendil-works/pi-tui"
import type { ExtensionAPI, ExtensionContext, ExtensionFactory } from "@earendil-works/pi-coding-agent"
import { executeRoboticsCommand, roboticsCommands, type KinexRuntime, type RoboticsCommand } from "@kinex/core"
import type { RoboticsOwner } from "./owner.ts"
import { contextUpdate } from "./context.ts"
import { toolBridge } from "./tools.ts"
import type { CompactionControl } from "./compaction.ts"

export interface SessionControl {
  prompt(text: string): Promise<void>
  settle(): Promise<void>
  compaction: CompactionControl
}

export function kinexExtension(owner: RoboticsOwner, runtime: KinexRuntime, report: (text: string) => void, session: SessionControl): ExtensionFactory {
  return async (pi: ExtensionAPI) => {
    const instructions = await readFile(new URL("./instructions.txt", import.meta.url), "utf8")
    const bridge = toolBridge(pi, runtime, owner.interaction)
    await bridge.refresh()
    let unsubscribe: (() => void) | undefined
    let devices: string[] = []
    let active = false
    const notify = (ctx: ExtensionContext, message: string, level: "info" | "warning" | "error") => {
      if (ctx.hasUI) ctx.ui.notify(message, level)
      else console.error(`Kinex: ${message}`)
    }
    const status = async (ctx: ExtensionContext) => {
      if (!active) return
      const list = await runtime.devices.list()
      const recording = await runtime.recording.status()
      devices = list.map(device => device.name)
      if (active && ctx.hasUI) ctx.ui.setStatus("kinex", `Kinex · ${list.filter(device => device.loaded).length}/${list.length} devices · ${owner.interaction.mode}${recording ? ` · REC ${recording.name}` : ""}`)
    }
    const execute = async (name: RoboticsCommand, args: string, ctx: ExtensionContext) => {
      if (name === "stop") ctx.abort()
      try {
        const result = await executeRoboticsCommand(runtime, name, args, {
          sessionID: ctx.sessionManager.getSessionId(),
          confirm: (title, description) => ctx.hasUI ? ctx.ui.confirm(title, description, { signal: ctx.signal }) : Promise.resolve(false),
          notify: message => notify(ctx, message, "info"),
        })
        if (result.kind === "workflow") {
          await session.prompt(result.prompt)
        } else {
          pi.sendMessage({ customType: "kinex", content: result.text, display: true })
          if (!ctx.hasUI) report(result.text)
          if (result.isError) {
            owner.failure = new Error(result.text)
            notify(ctx, "Some device operations failed", "warning")
          }
        }
      } catch (error) {
        owner.failure = error instanceof Error ? error : new Error(String(error))
        if (!ctx.hasUI) throw error
        ctx.ui.notify(error instanceof Error ? error.message : String(error), "error")
      } finally { await status(ctx) }
    }
    for (const command of roboticsCommands) {
      if (command.name === "reload") continue
      pi.registerCommand(command.name, {
        description: `${command.description} ${command.arguments}`.trim(),
        getArgumentCompletions: prefix => ["load", "unload", "ping", "stop", "unregister"].includes(command.name)
          ? [...devices, ...(command.name === "stop" || command.name === "unregister" ? [] : ["all"])].filter(name => name.startsWith(prefix)).map(name => ({ value: name, label: name })) : null,
        handler: (args, ctx) => execute(command.name, args, ctx),
      })
    }
    pi.on("input", async (event, ctx) => {
      const match = /^\/reload\s+(.+)$/s.exec(event.text.trim())
      if (!match?.[1]) return { action: "continue" }
      await execute("reload", match[1], ctx)
      return { action: "handled" }
    })
    pi.registerCommand("mode", {
      description: "Set Kinex permissions: ask, auto, yolo",
      handler: async (args, ctx) => {
        const selection = args.trim() || (ctx.hasUI ? await ctx.ui.select("Kinex mode", ["ask", "auto", "yolo"]) : owner.interaction.mode)
        if (selection !== "ask" && selection !== "auto" && selection !== "yolo") return
        owner.interaction.reset()
        owner.interaction.mode = selection
        await status(ctx)
      },
    })
    pi.registerTool({
      name: "question", label: "Question", description: "Ask the user for missing facts or choices.",
      executionMode: "sequential",
      parameters: Type.Object({ questions: Type.Array(Type.Object({ header: Type.String(), question: Type.String(), options: Type.Array(Type.Object({ label: Type.String(), description: Type.Optional(Type.String()) })), multiple: Type.Optional(Type.Boolean()) })) }),
      async execute(_id, args, signal, _update, ctx) {
        try {
          const answers = await owner.interaction.run(ctx, signal, () => owner.interaction.questions(args.questions))
          return { content: [{ type: "text", text: JSON.stringify(answers) }], details: { answers } }
        } catch (error) { ctx.abort(); throw error }
      },
    })
    pi.on("session_start", async (_event, ctx) => {
      active = true
      owner.bind(ctx)
      if (ctx.hasUI) {
        ctx.ui.setHeader((_tui, theme) => new Text(`${theme.fg("accent", "Kinex")} · robotics coding agent`, 1, 1))
        ctx.ui.addAutocompleteProvider(current => ({
          async getSuggestions(lines, line, col, options) {
            const prefix = lines[line]?.slice(0, col) ?? ""
            const match = /^\/reload\s+(\S*)$/.exec(prefix)
            if (match) return { prefix: match[1] ?? "", items: [...devices, "all"].filter(name => name.startsWith(match[1] ?? "")).map(name => ({ value: name, label: name })) }
            return current.getSuggestions(lines, line, col, options)
          },
          applyCompletion: (...args) => current.applyCompletion(...args),
        }))
      }
      unsubscribe = runtime.subscribe(event => {
        if (event.type === "recording.warning") notify(ctx, event.message, "warning")
        if (event.type === "recording.changed") void status(ctx).catch(error => notify(ctx, String(error), "error"))
      })
      for (const activation of await runtime.devices.warmLoaded()) void activation.ready.catch(error => notify(ctx, `${activation.device.name}: ${String(error)}`, "error"))
      await bridge.refreshActive(ctx)
      await status(ctx)
    })
    pi.on("session_shutdown", async event => {
      active = false
      session.compaction.end()
      unsubscribe?.()
      await session.settle()
      if (event.reason === "quit") await owner.dispose()
      else await owner.leaveSession()
    })
    pi.on("before_agent_start", async (event, ctx) => {
      const problems = await bridge.refreshActive(ctx)
      const context = await contextUpdate(runtime, ctx, problems)
      event.systemPromptOptions.sections.kinex = `${instructions}\n\n${context.instructions}`
      const failure = session.compaction.recover()
      if (failure && owner.failure === failure) owner.failure = undefined
      return { message: context.message }
    })
    pi.on("session_before_compact", event => { session.compaction.begin(event.signal) })
    pi.on("session_compact_failed", () => { session.compaction.end() })
    pi.on("session_compact", async (_event, ctx) => {
      session.compaction.end()
      try {
        const problems = await bridge.refreshActive(ctx)
        const context = await contextUpdate(runtime, ctx, problems)
        if (context.message) session.compaction.append(context.message)
        const failure = session.compaction.recover()
        if (failure && owner.failure === failure) owner.failure = undefined
      } catch (error) {
        owner.failure = error instanceof Error ? error : new Error(String(error))
        session.compaction.fail(owner.failure)
        ctx.abort()
        throw error
      }
    })
    pi.on("tool_call", async (event, ctx) => {
      const permission = event.toolName === "bash" ? "shell" : event.toolName === "write" || event.toolName === "edit" ? event.toolName : undefined
      if (!permission) return
      try {
        await owner.interaction.run(ctx, undefined, async () => owner.interaction.host.ask?.({ permission, description: JSON.stringify(event.input) }))
      } catch (error) {
        // Abort the whole run as a denied sibling must not allow further model actions.
        ctx.abort()
        return { block: true, terminate: true, reason: error instanceof Error ? error.message : String(error) }
      }
    })
    pi.on("tool_result", event => {
      if (!bridge.owns(event.toolName)) return
      const details: unknown = event.details
      if (details && typeof details === "object" && "kinex" in details && details.kinex && typeof details.kinex === "object" && "isError" in details.kinex) return { isError: details.kinex.isError === true }
    })
    // Pi emits message_end to extensions before persisting that message. These
    // boundaries run after persistence, so recording references real entry IDs.
    pi.on("turn_end", async (_event, ctx) => {
      owner.observeMessages(ctx)
      if (ctx.signal?.aborted) return
      const problems = await bridge.refreshActive(ctx)
      const context = await contextUpdate(runtime, ctx, problems)
      // Pi flushes these after the complete tool batch, before preparing the next
      // request. Updating context must not start another turn after a final reply.
      if (!ctx.signal?.aborted && context.message) pi.sendMessage(context.message, { triggerTurn: false })
    })
    pi.on("agent_end", (_event, ctx) => owner.observeMessages(ctx))
    pi.on("agent_settled", (_event, ctx) => status(ctx))
    pi.on("tool_execution_start", event => { if (!bridge.owns(event.toolName)) runtime.observe({ type: "tool", callID: event.toolCallId, name: event.toolName, status: "running" }) })
    pi.on("tool_execution_end", event => { if (!bridge.owns(event.toolName)) runtime.observe({ type: "tool", callID: event.toolCallId, name: event.toolName, status: event.isError ? "error" : "completed", isError: event.isError }) })
  }
}
