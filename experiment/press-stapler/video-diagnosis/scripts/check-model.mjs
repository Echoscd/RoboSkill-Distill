import path from 'node:path'
import { pathToFileURL } from 'node:url'

const root = '/LargeModelDev/users/chendong.song/kinex'
const entry = path.join(root, 'env/source/node_modules/@earendil-works/pi-coding-agent/dist/index.js')
const { ModelRuntime, resolveCliModel } = await import(pathToFileURL(entry).href)
const runtime = await ModelRuntime.create({
  authPath: path.join(root, 'env/data/agent/auth.json'),
  modelsPath: path.join(root, 'env/config/agent/models.json'),
  allowModelNetwork: false,
})
const resolved = resolveCliModel({
  cliModel: 'openrouter/qwen/qwen3.8-max-0902',
  cliThinking: 'low',
  modelRuntime: runtime,
})
console.log(JSON.stringify({
  error: resolved.error ?? runtime.getError(),
  warning: resolved.warning,
  model: resolved.model ? {
    id: resolved.model.id, provider: resolved.model.provider,
    api: resolved.model.api, input: resolved.model.input,
    contextWindow: resolved.model.contextWindow,
  } : null,
  thinkingLevel: resolved.thinkingLevel,
}))
if (!resolved.model || resolved.error || runtime.getError()) process.exitCode = 1
