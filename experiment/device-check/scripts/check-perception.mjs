#!/usr/bin/env node
import assert from 'node:assert/strict'
import { appendFile, copyFile, mkdir, readFile, realpath, symlink, unlink, writeFile } from 'node:fs/promises'
import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = '/LargeModelDev/users/chendong.song/kinex'
const run = path.resolve(process.argv[2] ?? '')
assert(run.startsWith(`${root}/experiment/device-check/runs/`))
const sim = JSON.parse(await readFile((await readFile(path.join(run, 'roboenv-run.path'), 'utf8')).trim(), 'utf8'))
const previous = JSON.parse(await readFile(path.join(run, 'followup-summary.json'), 'utf8'))
assert(previous.completed, 'Run after completed follow-up only')
assert(['127.0.0.1', 'localhost'].includes(new URL(sim.endpoint).hostname))
Object.assign(process.env, { ROBOENV_ENDPOINT: sim.endpoint, ROBOENV_SESSION: sim.session, ROBOENV_GENERATION: String(sim.generation) })
const detectorSource = path.join(root, 'env/workspace/.kinex/devices/grounding-dino')
const detectorTarget = path.join(sim.devices, 'grounding-dino')
// ProfileStore enumerates actual device directories; a child-directory symlink is skipped.
assert.equal(await realpath(detectorTarget), await realpath(detectorSource))
await unlink(detectorTarget)
await mkdir(detectorTarget)
await copyFile(path.join(detectorSource, 'profile.yaml'), path.join(detectorTarget, 'profile.yaml'))
await copyFile(path.join(detectorSource, 'driver.py'), path.join(detectorTarget, 'driver.py'))
await symlink(await realpath(path.join(detectorSource, 'weights')), path.join(detectorTarget, 'weights'))
const workspace = path.join(run, 'native-workspace')
const { createKinexRuntime } = await import(pathToFileURL(path.join(root, 'env/source/packages/core/dist/index.js')).href)
const { coreContribution } = await import(pathToFileURL(path.join(root, 'env/source/packages/core/dist/integration.js')).href)
const { OnlineLedger, observeContribution } = await import(pathToFileURL(path.join(root, 'experiment/harness/online/ledger.mjs')).href)
const ledger = new OnlineLedger({ file: path.join(run, 'perception-harness-events.jsonl'), runID: path.basename(run), generationID: String(sim.generation), mode: 'observe' })
await ledger.start()
const ask = async request => {
  assert(['device_read', 'device_act', 'python_tool', 'python_tool_controller'].includes(request.permission))
}
const runtime = createKinexRuntime({ directory: workspace, host: { ask, questions: async () => ({}) } })
ledger.attach(runtime)
const contribution = observeContribution(coreContribution(runtime), ledger)
let serial = 0
const checks = []
async function call(name, input) {
  const callID = `perception_${++serial}`
  await appendFile(path.join(run, 'perception-retry-calls.jsonl'), JSON.stringify({ type: 'start', callID, name, input }) + '\n')
  const result = await contribution.tools.call(name, input, { sessionID: `perception-${sim.session}`, callID, directory: workspace, abort: new AbortController().signal, ask, questions: async () => ({}) })
  await appendFile(path.join(run, 'perception-retry-calls.jsonl'), JSON.stringify({ type: 'end', callID, name, result }) + '\n')
  assert(!result.isError, result.output)
  return JSON.parse(result.output)
}
async function check(name, fn) {
  const start = Date.now()
  try { checks.push({ name, status: 'pass', duration_ms: Date.now() - start, detail: await fn() }) }
  catch (error) { checks.push({ name, status: 'fail', error: String(error) }); throw error }
  console.log(JSON.stringify(checks.at(-1)))
}
let completed = false
try {
  const profiles = await runtime.devices.list()
  const detector = profiles.find(p => p.name === 'grounding-dino')
  assert.equal(detector.type, 'detection')
  await check('load_grounding_dino', () => call('device', { deviceID: 'grounding-dino', action: 'load' }))
  await check('load_head_camera', () => call('device', { deviceID: 'head_camera', action: 'load' }))
  await check('measured_open_aperture_matches_native_command_scale', async () => {
    const values = {}
    for (const id of ['left_gripper', 'right_gripper']) {
      await call('device', { deviceID: id, action: 'load' })
      const state = await call('device', { deviceID: id })
      const expected_m = 0.090000165976
      assert(Math.abs(state.aperture_m - expected_m) <= 0.0005, JSON.stringify(state))
      values[id] = { measured: state, expected_m, tolerance_m: 0.0005,
        basis: 'RoboTwin config gripper_scale upper=0.045 per finger, aperture coefficients [1,1], offset=0.000000165976. URDF upper=0.04765 is a geometric bound.' }
    }
    return values
  })
  await check('python_rgbd_array_read', () => call('exec', {
    description: 'Validate actual RGB-D array fields and paired dimensions',
    python: 'from kinex import device\nimport numpy as np\nv=device("head_camera", "read", {"output":"array"})\nassert v["color"].shape[:2] == v["depth"].shape\nassert np.count_nonzero(v["depth"]) > 0\nprint({"color_shape":v["color"].shape, "depth_shape":v["depth"].shape, "depth_dtype":str(v["depth"].dtype), "timestamp":v["timestamp"]})',
  }))
  let located
  await check('grounding_dino_rgbd_localization', async () => {
    located = await call('locate_object_3d', { camera: 'head_camera', model: 'grounding-dino', prompt: 'red stapler', min_score: 0.3 })
    assert(Array.isArray(located.point) && located.point.length === 3 && located.point.every(Number.isFinite))
    return located
  })
  await check('calibrated_camera_to_world_transform', () => call('relative_pose', {
    child: { frame: 'head_camera', pose: [...located.point, 0, 0, 0, 1] }, parent: { frame: 'world' },
  }))
  completed = true
} catch (error) { console.error(String(error)) }
finally {
  await runtime.dispose()
  await ledger.finish({ exit_code: completed ? 0 : 1 })
  await writeFile(path.join(run, 'perception-retry-summary.json'), JSON.stringify({ completed, checks, no_model_api_calls: true }, null, 2))
}
process.exitCode = completed ? 0 : 1
