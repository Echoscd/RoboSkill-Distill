#!/usr/bin/env node
// Deterministic simulator-only compatibility checks. No model/API requests.
import assert from 'node:assert/strict'
import { appendFile, copyFile, mkdir, readFile, realpath, symlink, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'
import { setTimeout as sleep } from 'node:timers/promises'

const root = '/LargeModelDev/users/chendong.song/kinex'
const run = path.resolve(process.argv[2] ?? '')
const followup = process.argv[3] === 'followup'
const prefix = followup ? 'followup-' : ''
assert(run.startsWith(`${root}/experiment/device-check/runs/`), 'Run must be an owned device-check directory')
const runJSON = (await readFile(path.join(run, 'roboenv-run.path'), 'utf8')).trim()
const sim = JSON.parse(await readFile(runJSON, 'utf8'))
assert.equal(sim.state, 'ready')
assert(['127.0.0.1', 'localhost'].includes(new URL(sim.endpoint).hostname), 'Simulator must use a local endpoint')
assert(path.resolve(sim.directory).startsWith(`${run}/roboenv/`), 'Cannot borrow another run')
process.env.ROBOENV_ENDPOINT = sim.endpoint
process.env.ROBOENV_SESSION = sim.session
process.env.ROBOENV_GENERATION = String(sim.generation)
const workspace = path.join(run, 'native-workspace')
await mkdir(path.join(workspace, '.kinex'), { recursive: true })
for (const [source, name] of [[sim.devices, 'devices'], [path.join(root, 'env/workspace/.kinex/python'), 'python']]) {
  const target = path.join(workspace, '.kinex', name)
  try { await symlink(source, target) }
  catch (error) {
    if (!followup || error.code !== 'EEXIST') throw error
    assert.equal(await realpath(target), await realpath(source))
  }
}
await copyFile(path.join(root, 'env/workspace/.kinex/workspace.yaml'), path.join(workspace, '.kinex/workspace.yaml'))

const { createKinexRuntime } = await import(pathToFileURL(path.join(root, 'env/source/packages/core/dist/index.js')).href)
const { coreContribution } = await import(pathToFileURL(path.join(root, 'env/source/packages/core/dist/integration.js')).href)
const { OnlineLedger, observeContribution } = await import(pathToFileURL(path.join(root, 'experiment/harness/online/ledger.mjs')).href)
const ledger = new OnlineLedger({ file: path.join(run, `${prefix}harness-events.jsonl`), runID: path.basename(run), generationID: String(sim.generation), mode: 'observe' })
await ledger.start()
const log = (name, value) => appendFile(path.join(run, `${prefix}${name}`), `${JSON.stringify(value)}\n`, 'utf8')
const ask = async request => {
  assert(['device_read', 'device_act', 'python_tool', 'python_tool_controller'].includes(request.permission), `Unexpected permission ${request.permission}`)
  await log('permissions.jsonl', { at: new Date().toISOString(), permission: request.permission, description: request.description })
}
const runtime = createKinexRuntime({ directory: workspace, host: { ask, questions: async () => ({}) } })
ledger.attach(runtime)
const native = observeContribution(coreContribution(runtime), ledger)
const controller = new AbortController()
let serial = 0
const results = []
const sessionID = `device-compat-${sim.session}`
const snapshots = {}

async function call(name, input, { expectedError = false } = {}) {
  const callID = `check_${++serial}`
  const start = Date.now()
  await log('calls.jsonl', { type: 'start', callID, name, input, at: new Date().toISOString() })
  let result
  try {
    result = await native.tools.call(name, input, { sessionID, callID, directory: workspace, abort: controller.signal, ask, questions: async () => ({}) })
  } catch (error) {
    await log('calls.jsonl', { type: 'exception', callID, name, error: String(error), duration_ms: Date.now() - start })
    throw error
  }
  await log('calls.jsonl', { type: 'end', callID, name, result, duration_ms: Date.now() - start })
  if (expectedError) assert.equal(result.isError, true, `Expected a rejected input: ${name}`)
  else assert(!result.isError, `${name} returned: ${result.output}`)
  let output
  try { output = JSON.parse(result.output) } catch { output = { text: result.output } }
  if (output.results && !expectedError) assert(output.results.every(item => item.ok), JSON.stringify(output))
  return output
}

const device = (deviceID, action = 'read', args = {}) => call('device', { deviceID, action, args })
async function check(name, fn) {
  const start = Date.now()
  try {
    const detail = await fn()
    const row = { name, status: 'pass', duration_ms: Date.now() - start, detail }
    results.push(row)
    console.log(JSON.stringify(row))
    await log('checks.jsonl', row)
  } catch (error) {
    const row = { name, status: 'fail', duration_ms: Date.now() - start, error: String(error) }
    results.push(row)
    console.log(JSON.stringify(row))
    await log('checks.jsonl', row)
    throw error // No uncertain subsequent actuation after a failed motion check.
  }
}

async function arrival(id, predicate, description, timeout_s = 45) {
  const start = Date.now()
  let stable = 0
  let last
  while (Date.now() - start < timeout_s * 1000) {
    last = await device(id)
    assert(!(last.faults?.length), `${id} fault: ${JSON.stringify(last.faults)}`)
    stable = predicate(last) ? stable + 1 : 0
    if (stable >= 2) return { reached: true, elapsed_wall_s: (Date.now() - start) / 1000, stable_samples: stable, measured: last }
    await sleep(250)
  }
  throw new Error(`${id} ${description} timed out: ${JSON.stringify(last)}`)
}

const jointArrival = (id, target) => arrival(id, state =>
  state.positions?.length === target.length && Math.max(...state.positions.map((value, i) => Math.abs(value - target[i]))) <= 0.01, 'joint arrival')

let completed = false
try {
  const profiles = await runtime.devices.list()
  await check('simulator_profile_isolation', async () => {
    for (const profile of profiles) {
      assert.equal(profile.access?.connection?.kind, 'url')
      assert.equal(profile.access.connection.url, sim.endpoint)
    }
    assert.equal(profiles.length, 8)
    await writeFile(path.join(run, `${prefix}device-inventory.json`), JSON.stringify(profiles, null, 2))
    return profiles.map(p => ({ id: p.name, type: p.type, actions: p.access.driver.actions }))
  })
  await check('load_all_devices', () => call('devices', { calls: profiles.map(p => ({ deviceID: p.name, action: 'load' })) }))
  await check('status_all_devices', () => call('devices', { calls: profiles.map(p => ({ deviceID: p.name, action: 'status' })) }))
  await check('read_all_devices_and_rgbd_files', async () => {
    const output = await call('devices', { calls: profiles.map(p => ({ deviceID: p.name, action: 'read', args: p.type === 'rgbd' ? { output: 'file' } : {} })) })
    for (const item of output.results) snapshots[item.deviceID] = item.data
    return output
  })
  await check('world_wait', () => device('world', 'wait', { duration_s: 0.25 }))
  for (const arm of profiles.filter(p => !followup && p.type === 'joint')) {
    const id = arm.name
    const initial = (await device(id)).positions
    const target = [...initial]
    target[0] += 0.04
    await check(`${id}_fk_ik_roundtrip`, async () => {
      const fk = await device(id, 'fk', { joints: initial })
      const ik = await device(id, 'ik', { pose: fk.pose, seed: initial })
      assert.equal(ik.joints.length, initial.length)
      return { fk, ik }
    })
    await check(`${id}_raw_write_and_measured_arrival`, async () => {
      const receipt = await device(id, 'write', { actions: [target], duration_s: 0.5 })
      assert(receipt.execution_id)
      return { receipt, target, tolerance_rad: 0.01, arrival: await jointArrival(id, target) }
    })
    await check(`${id}_servo_joints_return`, async () => {
      const receipt = await call('servo', { device: id, joints: initial, block: false })
      assert(receipt.execution_id)
      return { receipt, arrival: await jointArrival(id, initial) }
    })
    await check(`${id}_servo_pose_current_frame`, async () => {
      const state = await device(id)
      const fk = await device(id, 'fk', { joints: state.positions })
      const receipt = await call('servo', { device: id, pose: fk.pose, frame: id, block: false })
      return { receipt, arrival: await jointArrival(id, receipt.joints) }
    })
    await check(`${id}_stop`, async () => {
      const receipt = await call('device_stop', { deviceID: id, reason: 'compatibility check' })
      return { receipt, state: await device(id) }
    })
  }
  for (const gripper of profiles.filter(p => p.type === 'gripper')) {
    const id = gripper.name
    const control = gripper.intrinsics.control
    const range = gripper.intrinsics.aperture_m
    assert.equal(control.mode, 'position')
    assert.equal(control.units, 'normalized')
    for (const endpoint of ['close', 'open']) {
      await check(`${id}_${endpoint}_${followup ? 'direction_and_settling' : 'and_measured_aperture'}`, async () => {
        const before = await device(id)
        const receipt = await device(id, 'write', { actions: [control[`${endpoint}_target`]], duration_s: 0.5 })
        assert(receipt.execution_id)
        const expected = endpoint === 'close' ? range.min : range.max
        const tolerance_m = Math.max(0.004, (range.max - range.min) * 0.05)
        if (!followup) return { receipt, expected_aperture_m: expected, tolerance_m, arrival: await arrival(id, state => Math.abs(state.aperture_m - expected) <= tolerance_m, endpoint) }
        let previous = null
        const reached = await arrival(id, state => {
          const directionalEffect = endpoint === 'close'
            ? state.aperture_m <= Math.max(0.005, before.aperture_m - 0.04)
            : state.aperture_m >= Math.min(0.08, before.aperture_m + 0.04)
          const stationary = previous !== null && Math.abs(state.aperture_m - previous) <= 0.0001
          previous = state.aperture_m
          return directionalEffect && stationary
        }, `${endpoint} direction and settling`)
        return { receipt, before, expected_aperture_m: expected, tolerance_m, arrival: reached,
          at_advertised_endpoint: Math.abs(reached.measured.aperture_m - expected) <= tolerance_m,
          interpretation: 'Direction and settling check only. The original advertised-endpoint failure remains unresolved.' }
      })
    }
    await check(`${id}_stop_holds_aperture`, async () => {
      const before = await device(id)
      const receipt = await call('device_stop', { deviceID: id, reason: 'verify hold behavior' })
      const after = await device(id)
      assert(Math.abs(after.aperture_m - before.aperture_m) < 0.005)
      return { before, receipt, after }
    })
    await check(`${id}_rejects_out_of_bounds_command`, async () => {
      const before = await device(id)
      const rejected = await call('device', { deviceID: id, action: 'write', args: { actions: [control.bounds.max + 1], duration_s: 0.5 } }, { expectedError: true })
      const after = await device(id)
      assert(Math.abs(after.aperture_m - before.aperture_m) < 0.005)
      return { rejected, before, after }
    })
  }
  await check('concurrent_batch_gripper_writes', async () => {
    const grips = profiles.filter(p => p.type === 'gripper')
    return call('devices', { calls: grips.map(p => ({ deviceID: p.name, action: 'write', args: { actions: [p.intrinsics.control.open_target], duration_s: 0.25 } })) })
  })
  await check('python_nested_device_read', () => call('exec', { description: 'Check documented Python device read', python: 'from kinex import device\nprint(device("left_gripper", "read"))' }))
  await check('python_nested_gripper_hold_write', () => call('exec', { description: 'Check native Python gripper write with the already-open target', python: 'from kinex import device\nprint(device("left_gripper", "write", {"actions": [1], "duration_s": 0.25}))' }))
  await check('native_permission_denial_precedes_actuation', async () => {
    const result = await native.tools.call('device', { deviceID: 'left_gripper', action: 'write', args: { actions: [0], duration_s: 0.5 } }, {
      sessionID, callID: 'deny-gripper-write', directory: workspace, abort: controller.signal,
      ask: async () => { throw new Error('EXPECTED_TEST_PERMISSION_DENIAL') }, questions: async () => ({}),
    }).catch(error => ({ isError: true, output: String(error) }))
    assert(result.isError && result.output.includes('EXPECTED_TEST_PERMISSION_DENIAL'))
    return { denied: true, result }
  })
  await check('final_camera_observations', () => call('devices', { calls: profiles.filter(p => p.type === 'rgbd').map(p => ({ deviceID: p.name, args: { output: 'file' } })) }))
  await check('unload_and_reload_camera', async () => {
    await device('head_camera', 'unload')
    await device('head_camera', 'load')
    return device('head_camera', 'read', { output: 'file' })
  })
  completed = true
} catch (error) {
  console.error(String(error))
} finally {
  try { await call('device_stop', { reason: 'End simulator-only compatibility checks' }) } catch (error) { console.error('Cleanup stop:', String(error)) }
  await runtime.dispose()
  await ledger.finish({ exit_code: completed ? 0 : 1 })
  await writeFile(path.join(run, `${prefix}summary.json`), JSON.stringify({
    schema: 'kinex/device-compatibility-check/1', completed, no_model_calls: true,
    scope: 'Eight RoboTwin devices on this local simulator generation; small free-space motion and gripper endpoints',
    harness_mode: 'observe', followup, run: sim.session, generation: sim.generation,
    calls: serial, passed: results.filter(x => x.status === 'pass').length, failed: results.filter(x => x.status === 'fail').length,
    checks: results,
    excluded: ['Real hardware', 'Task success', 'Contact/force/collision guarantees', 'Policy-model inference and absent device types', 'Legacy enforce mode compatibility'],
  }, null, 2))
}
process.exitCode = completed ? 0 : 1
