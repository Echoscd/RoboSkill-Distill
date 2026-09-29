import { test, after } from 'node:test'
import assert from 'node:assert/strict'
import { execFile, spawn } from 'node:child_process'
import { once } from 'node:events'
import { promisify } from 'node:util'
import { link, mkdir, readFile, readdir, stat, symlink, writeFile } from 'node:fs/promises'
import { setTimeout as delay } from 'node:timers/promises'
import { fileURLToPath, pathToFileURL } from 'node:url'
import path from 'node:path'
import { isolate, workspace } from './helpers.mjs'

const isolation = await isolate()
after(isolation.cleanup)
const exec = promisify(execFile)
const entry = fileURLToPath(new URL('../bin/kinex.mjs', import.meta.url))

async function fixture(t, version = 3) {
  const cwd = await workspace(t)
  const temporary = path.join(cwd, 'temporary')
  await mkdir(temporary)
  const timestamp = '2026-09-29T00:00:00.000Z'
  const session = [
    { type: 'session', version, id: 'export-test', timestamp, cwd },
    { type: 'message', id: 'user-entry', parentId: null, timestamp,
      message: { role: 'user', content: 'Inspect the robot — 导出测试', timestamp: 1 } },
  ]
  const source = session.map(row => JSON.stringify(row)).join('\n') + '\n'
  await writeFile(path.join(cwd, 'session.jsonl'), source)
  const env = { ...process.env, TMPDIR: temporary, TMP: temporary, TEMP: temporary }
  return { cwd, temporary, source, env,
    invoke: (...args) => exec(process.execPath, [entry, ...args], { cwd, env, timeout: 15000 }) }
}

async function preserved(f, source = f.source) {
  assert.equal(await readFile(path.join(f.cwd, 'session.jsonl'), 'utf8'), source)
  assert.deepEqual(await readdir(f.temporary), [], 'temporary session copies are removed')
}

async function exported(file) {
  const html = await readFile(file, 'utf8')
  const encoded = html.match(/<script id="session-data" type="application\/json">([\s\S]*?)<\/script>/)?.[1]
  assert.ok(encoded, 'export contains embedded session data')
  return JSON.parse(Buffer.from(encoded, 'base64').toString('utf8'))
}

for (const output of [undefined, 'custom export.html', '-export.html']) {
  test(`CLI exports to ${output ?? 'the default HTML path'} without a runtime`, async t => {
    const f = await fixture(t)
    const { stdout, stderr } = await f.invoke('--export', 'session.jsonl', ...(output ? ['--', output] : []))
    const filename = output ?? 'pi-session-session.html'
    assert.equal(stdout.trim(), `Exported to: ${filename}`)
    assert.equal(stderr, '')
    const data = await exported(path.join(f.cwd, filename))
    assert.equal(data.header.id, 'export-test')
    assert.equal(data.entries[0].message.content, 'Inspect the robot — 导出测试')
    assert.equal(data.leafId, 'user-entry')
    await preserved(f)
    for (const directory of ['.kinex', '.pi']) await assert.rejects(stat(path.join(f.cwd, directory)), { code: 'ENOENT' })
  })
}

for (const version of [1, 2]) {
  test(`export migrates a version-${version} copy without changing the original`, async t => {
    const f = await fixture(t, version)
    await f.invoke('--export', 'session.jsonl', 'export.html')
    const data = await exported(path.join(f.cwd, 'export.html'))
    assert.equal(data.header.version, 3)
    assert.equal(data.entries[0].message.content, 'Inspect the robot — 导出测试')
    await preserved(f)
  })
}

test('export rejects input/output aliases, including symlinks and hard links', async t => {
  const f = await fixture(t)
  await symlink('session.jsonl', path.join(f.cwd, 'symlink.html'))
  await link(path.join(f.cwd, 'session.jsonl'), path.join(f.cwd, 'hardlink.html'))
  for (const output of ['session.jsonl', './temporary/../session.jsonl', 'symlink.html', 'hardlink.html']) {
    await assert.rejects(f.invoke('--export', 'session.jsonl', output), error => {
      assert.equal(error.code, 1)
      assert.match(error.stderr, /must not refer to the input session/)
      return true
    })
    await preserved(f)
  }
})

test('export reports bad arguments and missing, empty or invalid sessions without changing input', async t => {
  const f = await fixture(t)
  for (const args of [['--export'], ['--export', ''], ['--export', 'session.jsonl', ''], ['--export', 'session.jsonl', 'one.html', 'two.html']]) {
    await assert.rejects(f.invoke(...args), error => {
      assert.equal(error.code, 1)
      assert.match(error.stderr, /--export/)
      return true
    })
  }
  await assert.rejects(f.invoke('--export', 'missing.jsonl'), error => {
    assert.equal(error.code, 1)
    assert.match(error.stderr, /ENOENT/)
    return true
  })
  for (const source of ['', ' \n', 'not JSON\n']) {
    await writeFile(path.join(f.cwd, 'session.jsonl'), source)
    await assert.rejects(f.invoke('--export', 'session.jsonl'), error => {
      assert.equal(error.code, 1)
      assert.match(error.stderr, /empty|not a valid pi session/i)
      return true
    })
    await preserved(f, source)
    await assert.rejects(stat(path.join(f.cwd, 'pi-session-session.html')), { code: 'ENOENT' })
  }
  assert.match((await f.invoke('--help')).stdout, /--export/)
})

test('export cleans up after output failures and can replace an existing HTML file', async t => {
  const f = await fixture(t)
  await mkdir(path.join(f.cwd, 'directory.html'))
  for (const output of ['directory.html', 'missing/export.html']) {
    await assert.rejects(f.invoke('--export', 'session.jsonl', output), error => {
      assert.equal(error.code, 1)
      assert.match(error.stderr, /EISDIR|ENOENT/)
      return true
    })
    await preserved(f)
  }
  await writeFile(path.join(f.cwd, 'export.html'), 'old output')
  await f.invoke('--export', 'session.jsonl', 'export.html')
  assert.equal((await exported(path.join(f.cwd, 'export.html'))).header.id, 'export-test')
  await preserved(f)
})

for (const [signal, code] of [['SIGINT', 130], ['SIGTERM', 143]]) {
  test(`${signal} terminates an export worker and removes its temporary session`, { timeout: 15000 }, async t => {
    const f = await fixture(t)
    const hook = path.join(f.cwd, 'hold-worker.mjs')
    // Hold the real child before SDK startup; SIGTERM tests the escalation path.
    await writeFile(hook, `import { writeFileSync } from 'node:fs'
import { basename } from 'node:path'
if (basename(process.argv[1] ?? '') === 'export-worker.js') {
  ${signal === 'SIGTERM' ? "process.on('SIGTERM', () => {})" : ''}
  writeFileSync('worker.pid', String(process.pid))
  setInterval(() => {}, 1000)
  await new Promise(() => {})
}
`)
    const child = spawn(process.execPath, [entry, '--export', 'session.jsonl'], {
      cwd: f.cwd, env: { ...f.env, NODE_OPTIONS: `--import=${pathToFileURL(hook).href}` },
      stdio: ['ignore', 'pipe', 'pipe'],
    })
    let stderr = ''
    child.stdout.resume()
    child.stderr.on('data', data => { stderr += data })
    const closed = once(child, 'close')
    t.after(() => { if (child.exitCode === null && child.signalCode === null) child.kill('SIGKILL') })
    let pid
    for (let attempt = 0; attempt < 400 && pid === undefined && child.exitCode === null; attempt++) {
      const value = await readFile(path.join(f.cwd, 'worker.pid'), 'utf8').catch(error => {
        if (error.code === 'ENOENT') return undefined
        throw error
      })
      if (value) pid = Number(value)
      else await delay(25)
    }
    assert.ok(pid, stderr || 'export worker did not start')
    t.after(() => { try { process.kill(pid, 'SIGKILL') } catch (error) { if (error.code !== 'ESRCH') throw error } })
    child.kill(signal)
    assert.deepEqual(await closed, [code, null], stderr)
    assert.throws(() => process.kill(pid, 0), { code: 'ESRCH' })
    await preserved(f)
  })
}
