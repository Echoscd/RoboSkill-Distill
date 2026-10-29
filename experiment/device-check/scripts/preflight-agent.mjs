#!/usr/bin/env node
// Initialize and dispose the host without sending any model request.
import { createApplication } from '/LargeModelDev/users/chendong.song/kinex/env/source/dist/application.js'
const app = await createApplication({ cwd: process.argv[2], model: 'openrouter/qwen/qwen3.8-max-0902', mode: 'yolo' })
try {
  console.log(JSON.stringify({ initialized: true, no_model_requests: true, model: app.host.session.model?.id }))
} finally { await app.dispose() }
