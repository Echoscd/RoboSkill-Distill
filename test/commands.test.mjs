import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { isolate, workspace, seed } from './helpers.mjs'
const isolation = await isolate()
after(isolation.cleanup)
const { createKinexRuntime, executeRoboticsCommand } = await import('@kinex/core')

test('shared commands validate arguments, preserve approval boundaries and distinguish workflows', async t => {
  const cwd = await workspace(t)
  const core = createKinexRuntime({ directory: cwd })
  t.after(() => core.dispose())
  await seed(core)
  const context = { sessionID: 'command', confirm: async () => false }
  await assert.rejects(executeRoboticsCommand(core, 'load', '', context), /Usage/)
  assert.equal((await executeRoboticsCommand(core, 'register', 'rgb camera', context)).kind, 'workflow')
  assert.equal((await core.devices.list())[0].loaded, false)
  await executeRoboticsCommand(core, 'load', 'all', context)
  assert.equal((await core.devices.list())[0].loaded, true)
  assert.match((await executeRoboticsCommand(core, 'unregister', 'sensor', context)).text, /Cancelled/)
  assert.equal((await core.devices.list()).length, 1)
  await assert.rejects(core.tools.call('device', { deviceID: 'sensor', action: 'unload' }, { sessionID: 'model' }), /Permission/)
  await executeRoboticsCommand(core, 'unregister', 'sensor', { ...context, confirm: async () => true })
  assert.equal((await core.devices.list()).length, 0)
})
