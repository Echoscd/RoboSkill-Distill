import assert from 'node:assert/strict'
import { test } from 'node:test'
import { scheduleDevice } from '../dist/device/scheduler.js'

test('stop invalidates commands during asynchronous setup and while queued', async () => {
  const ready = Promise.withResolvers()
  const prepared = Promise.withResolvers()
  const effects = []
  const write = scheduleDevice('preparing', 'write', async ({ check }) => {
    ready.resolve()
    await prepared.promise
    check()
    effects.push('write')
  })
  const rejected = assert.rejects(write, /interrupted/)
  await ready.promise
  await scheduleDevice('preparing', 'stop', async () => { effects.push('stop') })
  prepared.resolve()
  await rejected
  assert.deepEqual(effects, ['stop'])
  await scheduleDevice('preparing', 'write', async ({ check }) => { check(); effects.push('new write') })
  assert.deepEqual(effects, ['stop', 'new write'])

  const loading = Promise.withResolvers()
  const load = scheduleDevice('preparing', 'load', () => loading.promise)
  const queued = scheduleDevice('preparing', 'write', async () => { effects.push('queued write') })
  const interrupted = assert.rejects(queued, /interrupted/)
  const stop = scheduleDevice('preparing', 'stop', async () => { effects.push('stop') })
  loading.resolve()
  await Promise.all([load, stop, interrupted])
  assert.deepEqual(effects, ['stop', 'new write', 'stop'])
})
