import path from "node:path"
import { scoped } from "../scope.ts"
import { CalibrationStore } from "../calibration/store.ts"
import { queueActivation, deactivateDevice, probeDevice } from "./dispatch.ts"
import type { Device } from "./profile/schema.ts"

export interface Activation {
  device: Device
  activating: boolean
  ready: Awaited<ReturnType<typeof queueActivation>>["ready"]
}
async function activation(cwd: string, device: Device, signal?: AbortSignal): Promise<Activation> {
  return { device, ...await queueActivation(cwd, device, signal) }
}
export async function warmLoadedDevices(cwd: string, signal?: AbortSignal): Promise<Activation[]> {
  const devices = await CalibrationStore.listDevices(cwd)
  signal?.throwIfAborted()
  return Promise.all(devices.filter(device => device.loaded).map(device => activation(cwd, device, signal)))
}
// Serialize profile changes and full lifecycle completion, independently of
// the driver lane (recorder shutdown may itself use that lane).
const transitions = scoped(() => new Map<string, Promise<void>>())
const locating = scoped(() => new Map<string, Promise<string>>())
async function transition<T>(cwd: string, name: string, run: () => Promise<T>, ready?: (value: T) => Promise<unknown>): Promise<T> {
  const directory = path.resolve(cwd)
  // Share in-flight discovery so concurrent calls reserve their lanes in call
  // order, rather than the completion order of independent filesystem reads.
  let workspace = locating().get(directory)
  if (!workspace) {
    workspace = CalibrationStore.workspaceDir(directory)
    locating().set(directory, workspace)
    void workspace.finally(() => locating().delete(directory)).catch(() => {})
  }
  const key = path.join(await workspace, "devices", name)
  const result = (transitions().get(key) ?? Promise.resolve()).then(run)
  const tail = result.then(ready).then(() => {}, () => {})
  transitions().set(key, tail)
  void tail.then(() => { if (transitions().get(key) === tail) transitions().delete(key) })
  return result
}
export async function loadDevice(cwd: string, name: string, signal?: AbortSignal): Promise<Activation> {
  return transition(cwd, name, async () => {
    signal?.throwIfAborted()
    return activation(cwd, await CalibrationStore.setDeviceLoaded(cwd, name, true), signal)
  }, value => value.ready)
}
export async function unloadDevice(cwd: string, name: string): Promise<void> {
  return transition(cwd, name, async () => {
    const device = await CalibrationStore.readDevice(cwd, name)
    if (!device) throw new Error(`unknown device "${name}"`)
    await CalibrationStore.setDeviceLoaded(cwd, name, false)
    await deactivateDevice(cwd, device)
  })
}
export async function reloadDevice(cwd: string, name: string, signal?: AbortSignal): Promise<Activation> {
  return transition(cwd, name, async () => {
    signal?.throwIfAborted()
    const device = await CalibrationStore.readDevice(cwd, name)
    if (!device?.loaded) throw new Error(`device "${name}" is not loaded`)
    await deactivateDevice(cwd, device)
    return activation(cwd, device, signal)
  }, value => value.ready)
}
export async function pingDevice(cwd: string, name: string) {
  const device = await CalibrationStore.readDevice(cwd, name)
  if (!device) throw new Error(`unknown device "${name}"`)
  return probeDevice(cwd, device)
}
export async function unregisterDevice(cwd: string, name: string): Promise<void> {
  return transition(cwd, name, async () => {
    const device = await CalibrationStore.readDevice(cwd, name)
    if (!device) throw new Error(`unknown device "${name}"`)
    await deactivateDevice(cwd, device)
    await CalibrationStore.removeDevice(cwd, name)
  })
}

// Agent and host action dispatch use the same persisted lifecycle as commands.
export async function lifecycleAction(cwd: string, device: Device, action: "load" | "unload", signal?: AbortSignal) {
  signal?.throwIfAborted()
  if (action === "load") return (await loadDevice(cwd, device.name, signal)).ready
  await unloadDevice(cwd, device.name)
  return { deviceID: device.name, kind: device.type, data: { unloaded: true } }
}
