import { z } from "zod"
import type { SensorChannel } from "./profile/sensor.ts"
import { NamedError } from "../util/error.ts"

const axes = z.strictObject({ x: z.number().optional(), y: z.number().optional(), z: z.number().optional() })

// Shared by scalar-axis sensors. Bias is applied once, before observations/recording.
export function sensorChannelReading(key: string, config: z.infer<typeof SensorChannel> | "???" | null, raw: unknown) {
  if (config === null) {
    if (raw !== null) throw new NamedError("SensorReadingError", `${key} must be null when unsupported`)
    return null
  }
  if (config === "???" || config.bias === "???") throw new NamedError("SensorReadingError", `${key} is incomplete`)
  const values = axes.parse(raw)
  if (Object.keys(values).length !== config.axes.length || config.axes.some((a) => values[a] === undefined))
    throw new NamedError("SensorReadingError", `${key} must contain exactly the declared axes`)
  const bias = config.bias
  return Object.fromEntries(config.axes.map((a) => [a, z.number().parse(values[a]! - bias[a]!)]))
}
