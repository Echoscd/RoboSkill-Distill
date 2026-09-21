import path from "node:path"
import fs from "node:fs/promises"

export async function exists(target: string): Promise<boolean> {
  return fs
    .access(target)
    .then(() => true)
    .catch(() => false)
}

// Walk up from `start` to the filesystem root, returning every existing path
// named by one of `targets`, nearest first.
export async function findUp(targets: string[], start: string): Promise<string[]> {
  const found: string[] = []
  const current = { dir: path.resolve(start) }
  while (true) {
    for (const target of targets) {
      const candidate = path.join(current.dir, target)
      if (await exists(candidate)) found.push(candidate)
    }
    if (current.dir === path.parse(current.dir).root) break
    current.dir = path.dirname(current.dir)
  }
  return found
}

export async function readJson<T>(file: string): Promise<T | undefined> {
  if (!(await exists(file))) return undefined
  const text = await fs.readFile(file, "utf-8")
  return JSON.parse(text) as T
}

export async function writeJson(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true })
  await fs.writeFile(file, JSON.stringify(value, null, 2) + "\n")
}
