import { AsyncLocalStorage } from "node:async_hooks"
import type { ManagedProcess } from "./util/process.ts"
import type { CoreSettings } from "./config/config.ts"

export interface RuntimeScope {
  signal?: AbortSignal
  closed?: boolean
  assetsRoot?: string
  settings?: CoreSettings
  processes: Set<ManagedProcess>
}

export const createScope = (options: { assetsRoot?: string; settings?: CoreSettings } = {}): RuntimeScope => ({ ...options, processes: new Set() })
const storage = new AsyncLocalStorage<RuntimeScope>()
// Low-level APIs use the application's default scope. Explicit runtimes always
// bind their own scope, including asynchronous callbacks and background capture.
const application = createScope()
export const currentScope = () => storage.getStore() ?? application
export const inScope = <T>(scope: RuntimeScope, run: () => T): T => storage.run(scope, run)
export function scoped<T>(create: () => T): () => T {
  const values = new WeakMap<RuntimeScope, T>()
  return () => {
    const scope = currentScope()
    if (values.has(scope)) return values.get(scope)!
    const value = create()
    values.set(scope, value)
    return value
  }
}
