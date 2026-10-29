import { createHash } from "node:crypto"
import { appendFile, mkdir, readFile } from "node:fs/promises"
import path from "node:path"

const OBSERVATION_TYPES = new Set(["rgb", "rgbd", "detection", "segmentation"])
const ACTUATED_TYPES = new Set(["joint", "velocity", "legged_base", "gripper", "dexterous_hand", "suction"])
const SECRET_KEY = /(authorization|api[_-]?key|token|secret|password|proxy)/i
const MAX_STRING = 512
const MAX_ARRAY = 64

function digest(value) {
  return createHash("sha256").update(value).digest("hex")
}

function compact(value, key = "", depth = 0) {
  if (SECRET_KEY.test(key)) return "[REDACTED]"
  if (depth > 6) return "[MAX_DEPTH]"
  if (typeof value === "string") {
    if (value.length <= MAX_STRING) return value
    return { truncated: true, bytes: Buffer.byteLength(value), sha256: digest(value) }
  }
  if (Array.isArray(value)) {
    const items = value.slice(0, MAX_ARRAY).map(item => compact(item, key, depth + 1))
    return value.length > MAX_ARRAY ? [...items, { truncated_items: value.length - MAX_ARRAY }] : items
  }
  if (!value || typeof value !== "object") return value
  return Object.fromEntries(Object.entries(value).map(([name, item]) => [name, compact(item, name, depth + 1)]))
}

function parseObject(text) {
  if (typeof text !== "string") return undefined
  try {
    const value = JSON.parse(text)
    return value && typeof value === "object" && !Array.isArray(value) ? value : undefined
  } catch {
    return undefined
  }
}

function explicitObservationIDs(input, output) {
  const values = [
    input?.observation_id,
    ...(Array.isArray(input?.observation_ids) ? input.observation_ids : []),
    ...(Array.isArray(output?.based_on) ? output.based_on : []),
  ]
  return [...new Set(values.filter(value => typeof value === "string" && value.trim()))]
}

function numericVector(value, length) {
  return Array.isArray(value) && (!length || value.length === length)
    && value.every(item => typeof item === "number" && Number.isFinite(item))
}

function reportedTargets(output) {
  if (!output || typeof output !== "object") return []
  const targets = []
  const visit = (value, key = "", depth = 0) => {
    if (depth > 5 || !value || typeof value !== "object") return
    if (numericVector(value)) {
      if (/joints$/i.test(key)) targets.push({ kind: "joints", value })
      else if (/pose(?:_world)?$/i.test(key) && value.length === 7)
        targets.push({ kind: "pose", value, frame: /_world$/i.test(key) ? "world" : null })
      return
    }
    for (const [name, item] of Object.entries(value)) visit(item, name, depth + 1)
  }
  visit(output)
  return targets
}

export async function loadToolboxCapabilities(toolboxRoot) {
  if (!toolboxRoot) return new Map()
  let registry
  try { registry = JSON.parse(await readFile(path.join(toolboxRoot, "registry.json"), "utf8")) }
  catch { return new Map() }
  const result = new Map()
  for (const entry of registry.tools ?? []) {
    try {
      const metadata = JSON.parse(await readFile(path.join(toolboxRoot, "tools", entry.name, "metadata.json"), "utf8"))
      result.set(entry.name, {
        domains: Array.isArray(metadata.domains) ? metadata.domains : [],
        version: metadata.version,
        level: metadata.level?.score,
        generality: metadata.generality?.score,
      })
    } catch {
      result.set(entry.name, { domains: [], version: entry.version, level: entry.level, generality: entry.generality })
    }
  }
  return result
}

export class OnlineLedger {
  constructor({ file, runID, generationID, mode = "observe", toolboxCapabilities = new Map(), now = () => Date.now() }) {
    if (mode !== "observe") throw new Error(`Unsupported harness mode ${mode}: legacy enforce is retired. Use observe; Kinex owns device authorization and validation.`)
    this.file = path.resolve(file)
    this.runID = runID
    this.generationID = generationID ?? null
    this.mode = mode
    this.toolboxCapabilities = toolboxCapabilities
    this.now = now
    this.sequence = 0
    this.queue = Promise.resolve()
    this.activeCalls = new Map()
    this.observationsByCall = new Map()
    this.unsubscribe = undefined
  }

  append(kind, payload = {}) {
    const event = {
      schema: "kinex/harness-online-event/1",
      seq: ++this.sequence,
      wall_time: new Date(this.now()).toISOString(),
      run_id: this.runID,
      generation_id: this.generationID,
      mode: this.mode,
      kind,
      ...compact(payload),
    }
    const line = JSON.stringify(event) + "\n"
    this.queue = this.queue.then(async () => {
      await mkdir(path.dirname(this.file), { recursive: true })
      await appendFile(this.file, line, "utf8")
    })
    return this.queue
  }

  async start() {
    await this.append("harness.started", {
      behavior: "shadow",
      enforcement: false,
    })
  }

  attach(runtime) {
    if (this.unsubscribe) throw new Error("online ledger is already attached")
    this.unsubscribe = runtime.subscribe(event => { void this.runtimeEvent(event) })
  }

  detach() {
    this.unsubscribe?.()
    this.unsubscribe = undefined
  }

  currentCallIDs() {
    return [...this.activeCalls.keys()]
  }

  async runtimeEvent(runtimeEvent) {
    if (runtimeEvent.type === "execution") {
      const event = runtimeEvent.event
      if (event.type === "tool") {
        const existing = this.activeCalls.get(event.callID) ?? {}
        if (event.status === "running") this.activeCalls.set(event.callID, { ...existing, name: event.name, started: this.now() })
        else this.activeCalls.delete(event.callID)
        await this.append("kinex.tool_state", { ...event })
      } else {
        await this.append("kinex.message_state", { ...event })
      }
      return
    }
    if (runtimeEvent.type !== "device") {
      await this.append("kinex.runtime_event", runtimeEvent)
      return
    }

    const event = runtimeEvent.event
    const active = this.currentCallIDs()
    const link = active.length === 1
      ? { call_id: active[0], link_confidence: "single_active_call" }
      : { active_call_ids: active, link_confidence: active.length ? "ambiguous" : "none" }
    const derived = []

    if (OBSERVATION_TYPES.has(event.device.type) && event.action === "read") {
      const observationID = `obs_${String(this.sequence + 2).padStart(6, "0")}`
      const data = event.reading?.data ?? {}
      const observation = {
        observation_id: observationID,
        session_id: active.length === 1 ? this.activeCalls.get(active[0])?.sessionID ?? null : null,
        source_call_ids: active,
        device_id: event.device.name,
        device_type: event.device.type,
        acquired_at_s: typeof data.timestamp === "number" ? data.timestamp : null,
        frame_id: event.device.spatial?.pose_frame ?? event.device.name,
        calibration_id: null,
        payload: event.reading,
        contract_status: "incomplete",
        missing: [...(typeof data.timestamp === "number" ? [] : ["acquired_at_s"]), "calibration_id"],
      }
      for (const callID of active) {
        const values = this.observationsByCall.get(callID) ?? []
        values.push(observationID)
        this.observationsByCall.set(callID, values)
      }
      derived.push(["observation.created", observation])
    }

    if (ACTUATED_TYPES.has(event.device.type) && event.action === "write") {
      const reading = event.reading?.data ?? {}
      derived.push(["execution.receipt", {
        execution_id: typeof reading.execution_id === "string" ? reading.execution_id : `dispatch_${String(this.sequence + 2).padStart(6, "0")}`,
        source_call_ids: active,
        device_id: event.device.name,
        device_type: event.device.type,
        accepted: !event.error,
        completed: null,
        reached: null,
        error: event.error ?? null,
        contract_status: "partial",
        missing: ["completed", "reached"],
      }])
    }
    await this.append("device.dispatch", {
      ...link,
      workspace: event.workspace,
      device: { id: event.device.name, type: event.device.type },
      action: event.action,
      args: event.args,
      reading: event.reading,
      error: event.error,
      started_wall_ms: event.wall,
      latency_ms: event.latencyMs,
      origin: event.origin,
    })
    for (const [kind, payload] of derived) await this.append(kind, payload)
  }

  async modelToolStart(name, input, invocation) {
    const callID = invocation.callID ?? `call_${String(this.sequence + 1).padStart(6, "0")}`
    this.activeCalls.set(callID, { name, sessionID: invocation.sessionID, started: this.now() })
    await this.append("model_tool.start", {
      call_id: callID,
      session_id: invocation.sessionID,
      name,
      input,
      capability: this.toolboxCapabilities.get(name) ?? null,
    })
    return callID
  }

  annotateResult(callID, result) {
    if (result?.isError) return result
    const observationIDs = this.observationsByCall.get(callID) ?? []
    const parsed = parseObject(result?.output)
    if (!observationIDs.length || !parsed) return result
    return {
      ...result,
      output: JSON.stringify({ ...parsed, observation_ids: [...new Set(observationIDs)] }),
    }
  }

  async modelToolEnd(name, input, invocation, callID, result, durationMs) {
    const capability = this.toolboxCapabilities.get(name)
    const parsed = parseObject(result?.output)
    await this.append("model_tool.end", {
      call_id: callID,
      session_id: invocation.sessionID,
      name,
      duration_ms: durationMs,
      is_error: Boolean(result?.isError),
      result: result ? {
        title: result.title,
        output_bytes: Buffer.byteLength(result.output ?? ""),
        output_sha256: digest(result.output ?? ""),
        metadata: result.metadata,
        attachments: result.attachments,
      } : null,
      capability: capability ?? null,
    })

    if (capability?.domains?.includes("planning") && typeof parsed?.plan_id === "string" && !result?.isError) {
      const duringCall = this.observationsByCall.get(callID) ?? []
      const explicit = explicitObservationIDs(input, parsed)
      const basedOn = [...new Set([...explicit, ...duringCall])]
      const planID = typeof parsed?.plan_id === "string" ? parsed.plan_id : `plan_${String(this.sequence + 1).padStart(6, "0")}`
      const missing = []
      if (!basedOn.length) missing.push("observation_dependency")
      if (!parsed?.frame && !parsed?.source_frame && !parsed?.reference_frame) missing.push("coordinate_frame")
      if (typeof parsed?.expires_at_s !== "number") missing.push("expiry")
      if (typeof parsed?.position_uncertainty_m !== "number") missing.push("position_uncertainty_m")
      const plan = {
        plan_id: planID,
        session_id: invocation.sessionID,
        source_call_id: callID,
        tool: { name, version: capability.version ?? null },
        based_on: basedOn,
        link_basis: explicit.length ? "explicit" : duringCall.length ? "observed_during_tool_call" : "none",
        source_frame: parsed?.source_frame ?? parsed?.frame ?? parsed?.reference_frame ?? null,
        target_frame: parsed?.target_frame ?? null,
        expires_at_s: parsed?.expires_at_s ?? null,
        position_uncertainty_m: parsed?.position_uncertainty_m ?? null,
        device: parsed?.selected_arm ?? parsed?.arm ?? parsed?.device ?? null,
        reported_target_count: reportedTargets(parsed).length,
        validation_scope: "shape_only_not_execution_authorization",
        output_sha256: digest(result.output ?? ""),
        contract_status: missing.length ? "incomplete" : "complete",
        missing,
      }
      await this.append("plan.created", plan)
    }

    this.activeCalls.delete(callID)
    this.observationsByCall.delete(callID)
  }

  async modelToolError(name, invocation, callID, error, durationMs) {
    await this.append("model_tool.error", {
      call_id: callID,
      session_id: invocation.sessionID,
      name,
      duration_ms: durationMs,
      error: error instanceof Error ? { name: error.name, message: error.message } : String(error),
    })
    this.activeCalls.delete(callID)
    this.observationsByCall.delete(callID)
  }

  async finish(payload = {}) {
    this.detach()
    await this.append("harness.finished", payload)
    await this.flush()
  }

  flush() { return this.queue }
}

export function observeContribution(contribution, ledger) {
  if (!contribution.tools) return contribution
  return {
    ...contribution,
    tools: {
      list: () => contribution.tools.list(),
      async call(name, input, invocation) {
        const started = Date.now()
        const callID = await ledger.modelToolStart(name, input, invocation)
        try {
          const result = ledger.annotateResult(callID, await contribution.tools.call(name, input, invocation))
          await ledger.modelToolEnd(name, input, invocation, callID, result, Date.now() - started)
          return result
        } catch (error) {
          await ledger.modelToolError(name, invocation, callID, error, Date.now() - started)
          throw error
        }
      },
    },
  }
}

