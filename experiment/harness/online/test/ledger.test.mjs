import assert from 'node:assert/strict'
import test from 'node:test'
import { OnlineLedger, observeContribution } from '../ledger.mjs'

function recorder(capabilities = new Map()) {
  const events = []
  const ledger = new OnlineLedger({ file: '/unused', runID: 'unit', toolboxCapabilities: capabilities })
  ledger.append = async (kind, data) => { events.push({ kind, ...data }) }
  return { ledger, events }
}
const invocation = { sessionID: 'test-session', callID: 'test-call', abort: new AbortController().signal }

test('legacy enforce mode fails before any model or device operation', () => {
  assert.throws(() => new OnlineLedger({ file: '/unused', mode: 'enforce' }), /legacy enforce is retired/)
})

test('recorder preserves native actuator, policy, batch, and Python interfaces', async () => {
  const { ledger, events } = recorder()
  const delegated = []
  const tool = observeContribution({ tools: {
    list: async () => ({ tools: [], problems: [] }),
    call: async (name, input) => { delegated.push({ name, input }); return { output: '{"execution_id":"stub"}' } },
  } }, ledger)
  const calls = [
    ['device', { deviceID: 'gripper', action: 'write', args: { actions: [0], duration_s: 1 } }],
    ['device', { deviceID: 'suction', action: 'write', args: { actions: [1], duration_s: 1 } }],
    ['devices', { calls: [{ deviceID: 'gripper', action: 'write', args: { actions: [1], duration_s: 1 } }] }],
    ['servo', { device: 'arm', joints: [0], block: false }],
    ['servo', { device: 'arm', pose: [0, 0, 0, 0, 0, 0, 1], frame: 'world' }],
    ['run_policy', { model: 'policy', observation: {}, command: [{ device: 'arm' }] }],
    ['exec', { python: 'from kinex import device\ndevice("gripper", "write", {"actions":[0], "duration_s":1})' }],
    ['device_stop', { deviceID: 'arm' }],
    ['custom_controller', { target: 'native-contract' }],
  ]
  for (const [name, input] of calls) await tool.tools.call(name, input, invocation)
  assert.deepEqual(delegated, calls.map(([name, input]) => ({ name, input })))
  assert.equal(events.filter(e => e.kind === 'harness.blocked').length, 0)
})

test('native validation errors are retained unchanged', async () => {
  const { ledger } = recorder()
  const invalid = { title: 'native error', output: '{"error":"target exceeds profile command bounds"}', isError: true }
  const tool = observeContribution({ tools: { call: async () => invalid } }, ledger)
  assert.deepEqual(await tool.tools.call('device', {}, invocation), invalid)
})

test('observation IDs and measured receipts remain available in observe mode', async () => {
  const { ledger, events } = recorder()
  await ledger.modelToolStart('device', {}, invocation)
  await ledger.runtimeEvent({ type: 'device', event: {
    device: { name: 'camera', type: 'rgbd' }, action: 'read', reading: { data: { timestamp: 1 } },
  } })
  const annotated = ledger.annotateResult(invocation.callID, { output: '{"timestamp":1}' })
  assert.equal(JSON.parse(annotated.output).observation_ids.length, 1)
  await ledger.runtimeEvent({ type: 'device', event: {
    device: { name: 'gripper', type: 'gripper' }, action: 'write', reading: { data: { execution_id: 'e' } },
  } })
  const receipt = events.find(e => e.kind === 'execution.receipt')
  assert.equal(receipt.accepted, true)
  assert.equal(receipt.completed, null)
  assert.equal(receipt.reached, null)
})

test('plan annotations are descriptive, bind selected_arm, and ignore inventory domain tags', async () => {
  const caps = new Map([['planner', { domains: ['planning'] }], ['inventory', { domains: ['planning'] }]])
  const { ledger, events } = recorder(caps)
  await ledger.modelToolEnd('inventory', {}, invocation, 'inventory', { output: '{}' }, 1)
  assert.equal(events.filter(e => e.kind === 'plan.created').length, 0)
  await ledger.modelToolEnd('planner', { observation_id: 'o' }, invocation, 'plan', {
    output: JSON.stringify({ plan_id: 'p', selected_arm: 'left_arm', frame: 'world', expires_at_s: 2, position_uncertainty_m: 0.01, joints: [0] }),
  }, 1)
  const plan = events.find(e => e.kind === 'plan.created')
  assert.equal(plan.device, 'left_arm')
  assert.equal(plan.validation_scope, 'shape_only_not_execution_authorization')
  assert.equal(plan.reported_target_count, 1)
})
