import { z } from "zod"
import { loadRawConfig } from "./loader.ts"
import { currentScope } from "../scope.ts"

// Output frame rate is independent of device sampling rates.
export const RecordConfig = z.object({
  max_mb: z.number().positive().default(4096),
  video_fps: z.number().positive().default(15),
  video_max_px: z.number().int().min(2).default(480),
})
export type RecordConfig = z.infer<typeof RecordConfig>

export const CoreSettings = z.object({ record: RecordConfig.partial().optional() })
export type CoreSettings = z.infer<typeof CoreSettings>
export function recordConfig(config: CoreSettings): RecordConfig { return RecordConfig.parse(config.record ?? {}) }
export async function loadConfig(cwd: string): Promise<CoreSettings> {
  const result = CoreSettings.safeParse(await loadRawConfig(cwd))
  return { ...(result.success ? result.data : {}), ...currentScope().settings }
}
