import path from "node:path"
import { ConfigPaths } from "./paths.ts"

// Workspace/project roots nearest-first, then global and builtin content.
export async function contentRoots(cwd: string, name: string, builtin: string): Promise<string[]> {
  return [...(await ConfigPaths.directories(cwd)).toReversed().map((dir) => path.join(dir, name)), builtin]
}
