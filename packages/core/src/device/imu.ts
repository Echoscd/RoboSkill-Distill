import { hasMissing } from "./profile/common.ts"
import { z } from "zod"
import { quaternion } from "./profile/common.ts"
import type { Device } from "./profile/schema.ts"
import { NamedError } from "../util/error.ts"
import type { DeviceReading } from "./driver.ts"
import { sensorChannelReading } from "./sensor.ts"

export function imuReading(device: Device, reading: DeviceReading): DeviceReading {
  if (device.type !== "imu") return reading
  const measurement = device.intrinsics.measurement
  if (measurement === "???" || hasMissing(measurement))
    throw new NamedError("ImuReadingError", "IMU measurement must be calibrated before reading")
  const orientation = measurement.orientation === null ? z.null().parse(reading.data?.orientation) : quaternion.parse(reading.data?.orientation)
  const channels = Object.fromEntries((["angular_velocity", "linear_acceleration", "magnetic_field"] as const)
    .map((key) => [key, sensorChannelReading(key, measurement[key], reading.data?.[key])]))
  // Specific force is preserved. Gravity compensation needs an explicit consumer.
  return { ...reading, data: { ...reading.data, ...channels, orientation } }
}
