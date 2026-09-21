import { readFile } from "node:fs/promises"
import { Unsafe } from "typebox"
import type { ExtensionAPI, ExtensionContext, ToolDefinition } from "@earendil-works/pi-coding-agent"
import { PermissionDeniedError, QuestionDeclinedError, type KinexRuntime, type Result } from "@kinex/core"
import type { Interaction } from "./interaction.ts"

export async function piResult(result: Result, signal?: AbortSignal): Promise<Awaited<ReturnType<ToolDefinition["execute"]>>> {
  const content: Awaited<ReturnType<ToolDefinition["execute"]>>["content"] = [{ type: "text", text: result.output }]
  for (const attachment of result.attachments ?? []) {
    const bytes = await readFile(attachment.path, { signal })
    content.push({ type: "image", mimeType: attachment.mime, data: bytes.toString("base64") })
  }
  return { content, details: { kinex: { title: result.title, isError: result.isError, metadata: result.metadata } } }
}

export function toolBridge(pi: ExtensionAPI, runtime: KinexRuntime, interaction: Interaction) {
  const registered = new Map<string, string>()
  const present = new Set<string>()
  return {
    owns: (name: string) => registered.has(name),
    async refresh(bound = false) {
      const catalog = await runtime.tools.list()
      const foreign = new Set(bound ? pi.getAllTools().map(tool => tool.name).filter(name => !registered.has(name)) : [])
      // Built-ins must retain their native semantics even before session binding.
      for (const name of ["read", "write", "edit", "bash", "grep", "find", "ls", "question"]) foreign.add(name)
      const problems = [...catalog.problems]
      const next = new Set<string>()
      const added: string[] = []
      for (const tool of catalog.tools) {
        if (foreign.has(tool.name)) { problems.push(`Kinex tool ${tool.name} conflicts with a host tool`); continue }
        next.add(tool.name)
        if (!present.has(tool.name)) added.push(tool.name)
        const fingerprint = JSON.stringify(tool)
        if (registered.get(tool.name) === fingerprint) continue
        pi.registerTool({
          name: tool.name, label: `Kinex ${tool.name}`, description: tool.description,
          parameters: Unsafe<Record<string, unknown>>(tool.inputSchema), executionMode: "sequential",
          async execute(callID, args, signal, _update, ctx) {
            if (!present.has(tool.name)) throw new Error(`Tool ${tool.name} is no longer available`)
            try {
              return await interaction.run(ctx, signal, async combined => piResult(await runtime.tools.call(tool.name, args, {
                sessionID: ctx.sessionManager.getSessionId(), callID, signal: combined,
              }), combined))
            } catch (error) {
              if (error instanceof PermissionDeniedError || error instanceof QuestionDeclinedError) ctx.abort()
              throw error
            }
          },
        })
        registered.set(tool.name, fingerprint)
      }
      const removed = new Set([...present].filter(name => !next.has(name)))
      present.clear()
      for (const name of next) present.add(name)
      return { problems, added, removed }
    },
    async refreshActive(_ctx: ExtensionContext) {
      const result = await this.refresh(true)
      if (result.added.length || result.removed.size) pi.setActiveTools([...new Set([
        ...pi.getActiveTools().filter(name => !result.removed.has(name)), ...result.added,
      ])])
      return result.problems
    },
  }
}
