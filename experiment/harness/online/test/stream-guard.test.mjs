import assert from "node:assert/strict"
import test from "node:test"
import { ModelStreamGuard, protectedFilesystemMutation } from "../stream-guard.mjs"

const start = { type: "message_start", message: { role: "assistant" } }
const delta = value => ({
  type: "message_update",
  assistantMessageEvent: { type: "toolcall_delta", contentIndex: 1, delta: value },
})

test("allows ordinary bounded tool arguments", () => {
  const guard = new ModelStreamGuard({ maxToolArgumentChars: 1000 })
  guard.observe(start)
  assert.equal(guard.observe(delta('{"camera":"head_camera","prompt":"stapler"}')), null)
  assert.equal(guard.tripped, null)
})

test("aborts oversized tool arguments before execution", () => {
  const guard = new ModelStreamGuard({ maxToolArgumentChars: 32 })
  guard.observe(start)
  assert.equal(guard.observe(delta("x".repeat(20))), null)
  const decision = guard.observe(delta("y".repeat(20)))
  assert.equal(decision.reason, "tool_argument_limit")
  assert.equal(decision.chars, 40)
})

test("detects the recursive path wording from iter 003", () => {
  const guard = new ModelStreamGuard({
    maxToolArgumentChars: 10000,
    minRepeatCount: 8,
    minRepeatedChars: 64,
  })
  guard.observe(start)
  assert.equal(guard.observe(delta('{"command":"ls ../ && echo No great-')), null)
  const decision = guard.observe(delta("great-".repeat(20)))
  assert.equal(decision.reason, "repeated_tool_argument_suffix")
  assert.ok(decision.repeat_count >= 8)
})

test("blocks deletion through a workspace device symlink", () => {
  const decision = protectedFilesystemMutation({
    type: "tool_execution_start",
    toolCallId: "delete-device",
    toolName: "bash",
    args: { command: "rm -rf /tmp/workspace/.kinex/devices/grounding-dino" },
  })
  assert.equal(decision.reason, "protected_kinex_path_mutation")
  assert.equal(decision.call_id, "delete-device")
})

test("allows read-only shell inspection of managed paths", () => {
  assert.equal(protectedFilesystemMutation({
    type: "tool_execution_start",
    toolCallId: "inspect",
    toolName: "bash",
    args: { command: "ls /tmp/workspace/.kinex/devices" },
  }), null)
})

