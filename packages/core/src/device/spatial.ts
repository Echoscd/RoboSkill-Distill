import { z } from "zod"
import { Pose } from "./profile/common.ts"
import type { Device } from "./profile/schema.ts"
import type { DeviceReading } from "./driver.ts"

// A read reports every dynamic frame; static transforms stay in the profile.
export function framePoses(intrinsics: { frames: Record<string, unknown> }) {
  const dynamic = Object.keys(intrinsics.frames).filter((name) => intrinsics.frames[name] === null)
  return z.record(z.string(), Pose).default({}).refine(
    (frames) => Object.keys(frames).length === dynamic.length && dynamic.every((name) => Object.hasOwn(frames, name)),
    "frame_poses must match declared dynamic frames",
  )
}

export function spatialReading(device: Device, reading: DeviceReading): DeviceReading {
  if (!("frames" in device.intrinsics)) return reading
  const frame_poses = framePoses(device.intrinsics).parse(reading.data?.frame_poses)
  return { ...reading, data: { ...reading.data, frame_poses } }
}
