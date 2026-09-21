import type { Device } from "../../device/profile/schema.ts"
import type { DeviceReading } from "../../device/driver.ts"
import type { Result } from "../tool.ts"

// Device routing lives in the device engine; the tool family re-exports it.
export { dispatchDevice } from "../../device/dispatch.ts"

export function noRobot(): Result {
  return {
    title: "no robot configured",
    output: "No robot is configured in this project. Run the /onboarding command first.",
    isError: true,
  }
}

export function unknownDevice(deviceID: string): Result {
  return {
    title: "unknown device",
    output: `no device "${deviceID}" in this workspace — see the <robot> block or run calib_plan`,
    isError: true,
  }
}

export function unloadedDevice(device: Device): Result {
  return {
    title: `device ${device.name} is unloaded`,
    output: `device "${device.name}" is unloaded and must not be touched. Use the device tool with action="load" to activate it.`,
    isError: true,
  }
}

export function renderReading(reading: DeviceReading): string {
  const data = JSON.stringify(reading.data ?? {}, null, 2)
  if (reading.filePath) return `written to ${reading.filePath}\n${data}`
  return data
}
