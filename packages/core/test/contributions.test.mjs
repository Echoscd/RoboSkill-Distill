import { test } from 'node:test'
import assert from 'node:assert/strict'
import { composeContributions } from '../dist/integration.js'

test('contributions combine independently owned tools, commands, skills and context', async () => {
  let enabled = true
  const calls = []
  const source = id => ({
    id,
    tools: {
      list: async () => ({ tools: enabled ? [{ name: id, description: id, inputSchema: { type: 'object' } }] : [], problems: [] }),
      call: async (name, input, context) => { await context.ask({ permission: id, description: id }); calls.push(name); return { title: id, output: JSON.stringify(input) } },
    },
    commands: [{ name: id, arguments: '', description: id, kind: 'workflow', execute: async args => ({ kind: 'workflow', prompt: `${id}:${args}` }) }],
    skills: { list: async () => [{ name: id, description: id, file: id, directory: id }], load: async name => name === id ? { info: { name: id }, content: id } : undefined },
    context: async () => ({ instructions: id, sections: { state: id } }),
  })
  const composed = composeContributions([source('world'), source('core')])
  assert.deepEqual((await composed.tools.list()).tools.map(tool => tool.name), ['core', 'world'])
  assert.equal((await composed.context()).sections['world.state'], 'world')
  assert.match((await composed.context()).sections['world.skills'], /world/)
  assert.equal((await composed.skills.load('world')).content, 'world')
  assert.deepEqual(await composed.commands[1].execute('setup', {}), { kind: 'workflow', prompt: 'world:setup' })
  const invocation = { sessionID: 'test', directory: '.', abort: new AbortController().signal, ask: async () => {}, questions: async () => ({}) }
  await composed.tools.call('world', { x: 1 }, invocation)
  assert.deepEqual(calls, ['world'])
  await assert.rejects(composed.tools.call('core', {}, { ...invocation, ask: async () => { throw new Error('denied') } }), /denied/)
  enabled = false
  await assert.rejects(composed.tools.call('world', {}, invocation), /Unknown/)
  assert.throws(() => composeContributions([source('core'), source('core')]), /duplicate/i)
  enabled = true
  await assert.rejects(composeContributions([{ ...source('a'), commands: [] }, { ...source('b'), commands: [], tools: source('a').tools }]).tools.list(), /Duplicate tool/)
})
