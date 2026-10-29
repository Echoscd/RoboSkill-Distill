#!/usr/bin/env node
import { readFile, writeFile } from "node:fs/promises"
import { createHash } from "node:crypto"
import os from "node:os"
import path from "node:path"
import { pathToFileURL } from "node:url"
import { OnlineLedger, loadToolboxCapabilities, observeContribution } from "./ledger.mjs"
import { attachModelStreamGuard } from "./stream-guard.mjs"

function parseArguments(values) {
  const result = {}
  for (let index = 0; index < values.length; index += 2) {
    const key = values[index]
    const value = values[index + 1]
    if (!key?.startsWith("--") || value === undefined) throw new Error(`Invalid argument near ${key ?? "end"}`)
    result[key.slice(2)] = value
  }
  for (const required of ["source-root", "model", "prompt-file", "events-file"])
    if (!result[required]) throw new Error(`--${required} is required`)
  return result
}

const values = parseArguments(process.argv.slice(2))
const sourceRoot = path.resolve(values["source-root"])
const repository = path.resolve(sourceRoot, "..", "..")
const config = process.env.KINEX_CONFIG_DIR ?? path.join(process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), ".config"), "kinex")
process.env.PI_CODING_AGENT_DIR = path.join(config, "agent")
process.env.PI_SKIP_VERSION_CHECK = "1"
process.env.PI_TELEMETRY = "0"

const absoluteImport = relative => import(pathToFileURL(path.join(sourceRoot, relative)).href)
const [{ createApplication }, { runPrintMode }, { coreContribution }, setup] = await Promise.all([
  absoluteImport("dist/application.js"),
  absoluteImport("node_modules/@earendil-works/pi-coding-agent/dist/index.js"),
  absoluteImport("packages/core/dist/integration.js"),
  absoluteImport("packages/setup/dist/index.js"),
])

const capabilities = await loadToolboxCapabilities(path.join(repository, "toolbox"))
const ledger = new OnlineLedger({
  file: values["events-file"],
  runID: process.env.KINEX_RUN_ID ?? path.basename(path.dirname(path.resolve(values["events-file"]))),
  generationID: process.env.ROBOENV_GENERATION,
  mode: process.env.KINEX_HARNESS_MODE ?? "observe",
  toolboxCapabilities: capabilities,
})
await ledger.start()

const composition = {
  builtinSkillRoots: setup.setupSkillRoots,
  reservedToolNames: setup.setupToolNames,
  contributions(runtime) {
    ledger.attach(runtime)
    return [
      observeContribution(coreContribution(runtime), ledger),
      observeContribution(setup.setupContribution(setup.createKinexSetup(runtime)), ledger),
    ]
  },
}

let prompt = await readFile(path.resolve(values["prompt-file"]), "utf8")
const policySkill = path.resolve(
  values["policy-skill"]
    ?? path.join(repository, "experiment", "skills", "simulator-verdict-failure-analysis", "SKILL.md"),
)
try {
  const policy = await readFile(policySkill, "utf8")
  prompt = `${prompt.trim()}\n\n## Required experiment policy\n\n${policy.trim()}\n`
  await ledger.append("policy.skill_loaded", {
    name: "simulator-verdict-failure-analysis",
    path: path.relative(repository, policySkill),
  })
} catch (error) {
  throw new Error(`Required simulator verdict policy skill is unavailable: ${policySkill}`, { cause: error })
}
const app = await createApplication({
  cwd: process.cwd(), model: values.model,
  ...(process.env.KINEX_THINKING_LEVEL ? { thinkingLevel: process.env.KINEX_THINKING_LEVEL } : {}),
  mode: "yolo", composition,
})
const effectivePrompt = path.resolve(values["prompt-file"]).replace(/\.txt$/, "") + ".effective.txt"
await writeFile(effectivePrompt, prompt)
await ledger.append("prompt.effective", {
  path: effectivePrompt,
  sha256: createHash("sha256").update(prompt).digest("hex"),
  scope: "user_message_including_appended_policy",
})
let finalAssistantError = null
const unsubscribeErrors = app.host.session.subscribe(event => {
  if (event.type === "message_end" && event.message?.role === "assistant") {
    finalAssistantError = event.message.stopReason === "error"
      ? event.message.errorMessage ?? "Assistant response ended with an error" : null
  }
})
const streamGuard = attachModelStreamGuard(app.host.session, ledger, {
  maxToolArgumentChars: Number(process.env.KINEX_MAX_TOOL_ARGUMENT_CHARS ?? 8192),
})
let exitCode = 1
const shutdown = () => {
  void app.dispose().finally(async () => {
    await ledger.finish({ exit_code: 130, interrupted: true })
    process.exit(130)
  })
}
process.once("SIGINT", shutdown)
try {
  exitCode = await runPrintMode(app.host, { mode: "json", initialMessage: prompt, messages: [] })
  if (streamGuard.tripped) exitCode = 75
  if (app.owner.failure) exitCode = 1
  if (finalAssistantError) {
    exitCode = 1
    await ledger.append("model.error", { message: finalAssistantError, final_response_failed: true })
  }
} finally {
  process.off("SIGINT", shutdown)
  streamGuard.dispose()
  unsubscribeErrors()
  await app.dispose()
  await ledger.finish({ exit_code: exitCode, interrupted: false, model_stream_guard: streamGuard.tripped })
}
process.exitCode = exitCode

