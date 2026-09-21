import { hasMissing } from "./profile/common.ts"
import { sensorChannelReading } from "./sensor.ts"
import type { Device } from "./profile/schema.ts"
import { NamedError } from "../util/error.ts"
import type { DeviceReading } from "./driver.ts"

// Applied once at dispatch, before any tool or recorder receives the sample.
export function forceTorqueReading(device: Device, reading: DeviceReading): DeviceReading {
  if (device.type !== "force_torque") return reading
  const measurement = device.intrinsics.measurement
  if (measurement === "???" || hasMissing(measurement))
    throw new NamedError("ForceTorqueReadingError", "force/torque measurement must be calibrated before reading")
  const channel = (key: "force" | "torque") => sensorChannelReading(key, measurement[key], reading.data?.[key])
  return { ...reading, data: { ...reading.data, force: channel("force"), torque: channel("torque") } }
}
