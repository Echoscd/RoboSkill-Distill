import { scoped } from "../scope.ts"
import { jointReading } from "./joint.ts"
import { spatialReading } from "./spatial.ts"
import { velocityReading } from "./velocity.ts"
import { writeCommand } from "./command.ts"
import { abortable } from "../util/abort.ts"
import { imuReading } from "./imu.ts"
import { modelOperation, modelInput, modelOutput } from "./model.ts"
import { forceTorqueReading } from "./force-torque.ts"
import path from "node:path"
import { CalibrationStore } from "../calibration/store.ts"
import { known, type Device } from "./profile/schema.ts"
import { runDriver, isServing, stopServing, type DeviceReading } from "./driver.ts"
import { mockAct } from "./virtual.ts"
import { notifyDevice, notifyDeactivation } from "./observe.ts"
import { NamedError } from "../util/error.ts"

// The one routing point for reaching a device: the agent-written driver, or
// the in-memory mock — used by the device tools, the python-tool runner, the
// recorder, and the lifecycle helpers below.
export function route(cwd: string, device: Device, action: string, args: Record<string, unknown>, signal?: AbortSignal): Promise<DeviceReading> {
  if (device.type === "world" && ["load", "unload", "status"].includes(action))
    return Promise.resolve({ deviceID: device.name, kind: device.type, data: { loaded: action === "load" || (action === "status" && device.loaded), noop: true } })
  const access = device.access
  const kind = access && known(access.connection) ? access.connection.kind : undefined
  if (access?.driver) return runDriver(cwd, device, action, args, signal)
  if (kind === "mock") return Promise.resolve(mockAct(cwd, device, action, args))
  if (action === "unload") return Promise.resolve({ deviceID: device.name, kind: device.type, data: { unloaded: true } })
  return Promise.reject(
    new Error(
      `device "${device.name}" has no way to reach it: no access.driver is recorded (and its access.connection.kind is not "mock"). Write devices/${device.name}/driver.py and record it under access.driver first.`,
    ),
  )
}

// --- per-device lane -------------------------------------------------------
// Calls on one device run one at a time: a persistent driver answers on a
// single stdin/stdout pair (two interleaved callers would swap responses) and
// a one-shot driver's hardware handle is not shareable either. Different
// devices stay concurrent (the batched "devices" call of python tools). "stop"
// on a one-shot driver bypasses the lane — a safety stop must never queue
// behind a blocking write, and a fresh process can run at once. (A persistent
// driver answers on one channel, so its stop is serial by construction.)

const lanes = scoped(() => new Map<string, Promise<void>>())
const inflight = scoped(() => new Map<string, number>())
const inactive = scoped(() => new Set<string>())
const noop = () => {}

export function validateReading(device: Device, reading: DeviceReading): DeviceReading {
  const spatial = spatialReading(device, reading)
  switch (device.type) {
    case "joint":
    case "dexterous_hand": return jointReading(device, spatial)
    case "velocity": return velocityReading(device, spatial)
    case "imu": return imuReading(device, spatial)
    case "force_torque": return forceTorqueReading(device, spatial)
    default: return spatial
  }
}

function enqueue<T>(key: string, run: () => Promise<T>): Promise<T> {
  const previous = lanes().get(key) ?? Promise.resolve()
  const result = previous.then(run, run)
  const tail = result.then(noop, noop)
  lanes().set(key, tail)
  void tail.then(() => {
    if (lanes().get(key) === tail) lanes().delete(key)
  })
  return result
}

// A call is in flight (queued or running) on this device — the recorder's
// sampler yields instead of piling on.
export async function isDeviceBusy(cwd: string, name: string): Promise<boolean> {
  return (inflight().get(await CalibrationStore.deviceDir(cwd, name)) ?? 0) > 0
}

export async function dispatchDevice(
  cwd: string,
  device: Device,
  action: string,
  args: Record<string, unknown>,
  origin?: string,
  signal?: AbortSignal,
): Promise<DeviceReading> {
  const workspace = await CalibrationStore.workspaceDir(cwd)
  return dispatchInWorkspace(workspace, device, action, args, origin, signal)
}

// Synchronous reservation lets startup enqueue load before exposing device tools.
function dispatchInWorkspace(workspace: string, device: Device, action: string, args: Record<string, unknown>, origin?: string, signal?: AbortSignal): Promise<DeviceReading> {
  const key = path.join(workspace, "devices", device.name)
  const wall = Date.now()
  const request = { args }
  inflight().set(key, (inflight().get(key) ?? 0) + 1)
  const run = async () => {
    signal?.throwIfAborted()
    if (["load", "unload", "status"].includes(action) && Object.keys(args).length)
      throw new NamedError("DeviceLifecycleError", `${action} accepts no arguments`)
    if (!["load", "unload", "status", "stop", "record_stop"].includes(action) && (!device.loaded || inactive().has(key)))
      throw new NamedError("DeviceInactiveError", `device "${device.name}" is inactive; load it before ${action}`)
    const operation = modelOperation(device, action)
    request.args = modelInput(operation, args)
    if (action === "write")
      request.args = writeCommand(device, request.args)
    const reading = await route(workspace, device, action, request.args, signal).finally(async () => {
      if (action === "unload") await stopServing(workspace, device.name)
    })
    if (action === "load") inactive().delete(key)
    return action === "read" ? validateReading(device, reading) : modelOutput(operation, reading)
  }
  const bypass = action === "stop" && !device.access?.driver?.persistent
  const settle = bypass ? run() : enqueue(key, run)
  return abortable(settle, signal)
    .then(
      (reading) => {
        notifyDevice({ workspace, device, action, args: request.args, origin, reading, wall, latencyMs: Date.now() - wall })
        return reading
      },
      (error: unknown) => {
        const message = error instanceof Error ? error.message : String(error)
        notifyDevice({ workspace, device, action, args: request.args, origin, error: message, wall, latencyMs: Date.now() - wall })
        throw error
      },
    )
    .finally(() => {
      const count = (inflight().get(key) ?? 1) - 1
      if (count === 0) inflight().delete(key)
      if (count > 0) inflight().set(key, count)
    })
}

// Lifecycle requests share the operation lane; shutdown completes before its
// next request. Recorder deactivation happens outside that lane because it may
// dispatch record_stop itself.
export interface ProbeResult {
  reading: DeviceReading
  elapsedMs: number
  serving?: boolean
}

export async function probeDevice(cwd: string, device: Device): Promise<ProbeResult> {
  const started = Date.now()
  const reading = await dispatchDevice(cwd, device, "status", {})
  return {
    reading,
    elapsedMs: Date.now() - started,
    ...(device.access?.driver?.persistent ? { serving: await isServing(cwd, device.name) } : {}),
  }
}

export async function queueActivation(cwd: string, device: Device, signal?: AbortSignal) {
  const workspace = await CalibrationStore.workspaceDir(cwd)
  signal?.throwIfAborted()
  const ready = dispatchInWorkspace(workspace, device, "load", {}, undefined, signal)
  void ready.catch(() => {})
  return { ready, activating: device.access?.driver !== undefined }
}

export async function deactivateDevice(cwd: string, device: Device): Promise<void> {
  const workspace = await CalibrationStore.workspaceDir(cwd)
  inactive().add(path.join(workspace, "devices", device.name))
  const errors: unknown[] = []
  await notifyDeactivation({ workspace, device, action: "deactivate", args: {}, wall: Date.now(), latencyMs: 0 })
    .catch((error: unknown) => errors.push(error))
  await dispatchInWorkspace(workspace, device, "unload", {})
    .catch((error: unknown) => errors.push(error))
  if (errors.length) throw new NamedError("DeviceUnloadError", `unload failed for ${device.name}: ${errors.map(String).join("; ")}`, { errors: errors.map(String) })
}
