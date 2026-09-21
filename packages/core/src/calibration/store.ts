import { parse as parseYaml } from "yaml"
import { z } from "zod"
import { resolveDeviceModel } from "./device-model.ts"
import path from "node:path"
import fs from "node:fs/promises"
import { ConfigPaths } from "../config/paths.ts"
import { writeJson, exists } from "../util/filesystem.ts"
import { toYaml } from "../util/yaml.ts"
import { CalibrationResult, RobotManifest, Device } from "../device/profile/schema.ts"
import { create } from "../util/log.ts"

const log = create("calibration")
const object = z.record(z.string(), z.unknown())
export interface CalibrationSnapshot { robot?: RobotManifest; devices: Device[] }

// Explicit replacement applies only to supplied top-level sections.
function mergeSections(existing: Record<string, unknown>, patch: Record<string, unknown>, replace: readonly string[], allowed: readonly string[]) {
  const merged = deepMerge(existing, patch)
  for (const key of replace) {
    if (!allowed.includes(key) || !Object.hasOwn(patch, key)) throw new Error(`replace needs a supplied section: ${key}`)
    if (patch[key] === null) {
      if (!["access", "extrinsics", "sim"].includes(key)) throw new Error(`cannot remove required section ${key}`)
      delete merged[key]
      continue
    }
    const previous = object.safeParse(existing[key]).data
    const value = object.parse(patch[key])
    merged[key] = previous?.needs_calibration && !Object.hasOwn(value, "needs_calibration")
      ? { ...value, needs_calibration: previous.needs_calibration } : value
  }
  return merged
}

async function validateClears(cwd: string, patch: Record<string, unknown>, snapshot: CalibrationSnapshot, name?: string) {
  const { checkCalibrationItem } = await import("./dag.ts")
  for (const [key, value] of Object.entries(patch)) {
    if (object.safeParse(value).data?.needs_calibration !== null) continue
    const item = name ? `${key}:${name}` : Object.entries(ROBOT_ITEMS).find(([, section]) => section === key)?.[0]
    if (!item) throw new Error(`no calibration item for section ${key}`)
    const check = await checkCalibrationItem(cwd, snapshot, item)
    if (!check.done) throw new Error(`cannot clear ${item}: ${check.detail}`)
  }
}


// One robot configuration per workspace, under .kinex/:
//   workspace.yaml, devices/<name>/{profile.yaml,driver.py}, lib/, skill/,
//   docs/, calib/<routine>[-<device>].json, recordings/<id>/.

// A derived view of the needs-calibration queue (markers live IN the profile
// sections as `needs_calibration`, not in a side file).
export interface NeededEntry {
  item: string
  note?: string
}

// Robot-level calibration item ids → manifest section keys; device items are
// `<section>:<device-name>` instead. The task-ready sink is not resolvable.
const ROBOT_ITEMS = {
  identity: "identity",
  "devices-declared": "devices",
  safety: "safety",
} as const
const DEVICE_SECTIONS = ["access", "intrinsics", "extrinsics"] as const
type DeviceSection = (typeof DEVICE_SECTIONS)[number]

type ResolvedItem = { kind: "robot"; section: string } | { kind: "device"; section: DeviceSection; name: string }

function resolveItem(itemID: string): ResolvedItem {
  const colon = itemID.indexOf(":")
  if (colon !== -1) {
    const head = itemID.slice(0, colon)
    const name = itemID.slice(colon + 1)
    const section = DEVICE_SECTIONS.find((entry) => entry === head)
    if (!section)
      throw new Error(`unknown calibration item "${itemID}" — device items are access:<device>, intrinsics:<device>, extrinsics:<device>`)
    if (!name) throw new Error(`device item "${itemID}" needs a device name suffix, e.g. ${head}:wrist_cam`)
    return { kind: "device", section, name }
  }
  const section = (ROBOT_ITEMS as Record<string, string>)[itemID]
  if (!section) throw new Error(`unknown calibration item "${itemID}" — use a calib_plan item id`)
  return { kind: "robot", section }
}

function deepMerge(target: Record<string, unknown>, patch: Record<string, unknown>): Record<string, unknown> {
  const result = { ...target }
  for (const [key, value] of Object.entries(patch)) {
    const existing = result[key]
    if (
      value &&
      existing &&
      typeof value === "object" &&
      typeof existing === "object" &&
      !Array.isArray(value) &&
      !Array.isArray(existing)
    ) {
      result[key] = deepMerge(existing as Record<string, unknown>, value as Record<string, unknown>)
      continue
    }
    result[key] = value
  }
  return result
}

async function readYaml(file: string): Promise<Record<string, unknown> | undefined> {
  if (!(await exists(file))) return undefined
  const text = await fs.readFile(file, "utf-8")
  const parsed = (() => {
    try {
      return parseYaml(text)
    } catch {
      return undefined
    }
  })()
  if (typeof parsed !== "object" || parsed === null) return undefined
  return parsed as Record<string, unknown>
}

async function writeYaml(file: string, value: unknown): Promise<void> {
  await fs.mkdir(path.dirname(file), { recursive: true })
  await fs.writeFile(file, toYaml(value))
}

export const CalibrationStore = {
  async workspaceDir(cwd: string): Promise<string> {
    return ConfigPaths.projectDir(cwd)
  },

  // A device is a DIRECTORY: its profile plus the utility code that reaches it.
  async deviceDir(cwd: string, name: string): Promise<string> {
    return path.join(await CalibrationStore.workspaceDir(cwd), "devices", name)
  },

  async deviceFile(cwd: string, name: string): Promise<string> {
    return path.join(await CalibrationStore.deviceDir(cwd, name), "profile.yaml")
  },

  async writeManifest(cwd: string, patch: Record<string, unknown>, replace: readonly string[] = []): Promise<RobotManifest> {
    const file = path.join(await CalibrationStore.workspaceDir(cwd), "workspace.yaml")
    const existing = (await readYaml(file)) ?? {}
    const merged = mergeSections(existing, patch, replace, ["identity", "sim", "devices", "safety"])
    const now = new Date().toISOString()
    const meta = (merged["meta"] as Record<string, unknown> | undefined) ?? { created_at: now }
    merged["meta"] = { ...meta, updated_at: now }
    const manifest = RobotManifest.parse(merged)
    if (Object.values(patch).some((value) => object.safeParse(value).data?.needs_calibration === null))
      await validateClears(cwd, patch, { robot: manifest, devices: await CalibrationStore.listDevices(cwd) })
    await writeYaml(file, manifest)
    return manifest
  },

  async readManifest(cwd: string): Promise<RobotManifest | undefined> {
    const raw = await readYaml(path.join(await CalibrationStore.workspaceDir(cwd), "workspace.yaml"))
    if (!raw) return undefined
    const parsed = RobotManifest.safeParse(raw)
    if (!parsed.success) {
      log.warn("invalid workspace manifest", { issues: parsed.error.issues.length })
      return undefined
    }
    return parsed.data
  },

  async writeDevice(cwd: string, patch: Record<string, unknown> & { name: string }, replace: readonly string[] = []): Promise<Device> {
    if (typeof patch.name !== "string" || patch.name === "") throw new Error("device patch needs a non-empty name")
    const file = await CalibrationStore.deviceFile(cwd, patch.name)
    const existing = (await readYaml(file)) ?? {}
    // Merging across union variants would interleave two intrinsics shapes —
    // a retype replaces the file wholesale instead.
    const retyped = typeof existing["type"] === "string" && typeof patch["type"] === "string" && existing["type"] !== patch["type"]
    if (replace.includes("extrinsics") && patch.extrinsics === null && !["model", "detection", "segmentation", "world"].includes(String(patch.type ?? existing.type)))
      throw new Error("cannot remove required section extrinsics")
    const merged = mergeSections(retyped ? {} : existing, patch, replace, DEVICE_SECTIONS)
    const now = new Date().toISOString()
    const meta = (retyped ? undefined : (merged["meta"] as Record<string, unknown> | undefined)) ?? { created_at: now }
    merged["meta"] = { ...meta, updated_at: now }
    const device = await resolveDeviceModel(Device.parse(merged), path.dirname(file), retyped || Object.keys(object.safeParse(patch.intrinsics).data ?? {}).some((key) => key !== "needs_calibration"))
    if (Object.values(patch).some((value) => object.safeParse(value).data?.needs_calibration === null)) {
      const snapshot = await CalibrationStore.snapshot(cwd)
      await validateClears(cwd, patch, { ...snapshot, devices: [...snapshot.devices.filter((entry) => entry.name !== device.name), device] }, device.name)
    }
    await writeYaml(file, device)
    return device
  },

  async readDevice(cwd: string, name: string): Promise<Device | undefined> {
    const raw = await readYaml(await CalibrationStore.deviceFile(cwd, name))
    if (!raw) return undefined
    const parsed = Device.safeParse(raw)
    if (!parsed.success) {
      log.warn(`invalid device profile ${name}`, { issues: parsed.error.issues.length })
      return undefined
    }
    return resolveDeviceModel(parsed.data, await CalibrationStore.deviceDir(cwd, name))
  },

  async listDevices(cwd: string): Promise<Device[]> {
    const dir = path.join(await CalibrationStore.workspaceDir(cwd), "devices")
    if (!(await exists(dir))) return []
    const devices: Device[] = []
    for (const entry of (await fs.readdir(dir, { withFileTypes: true })).sort((a, b) => a.name.localeCompare(b.name))) {
      if (!entry.isDirectory()) continue
      const parsed = Device.safeParse(await readYaml(path.join(dir, entry.name, "profile.yaml")))
      if (parsed.success) devices.push(await resolveDeviceModel(parsed.data, path.join(dir, entry.name)))
    }
    return devices
  },

  // The /load and /unload switch: whether the agent may read from the device.
  async setDeviceLoaded(cwd: string, name: string, loaded: boolean): Promise<Device> {
    const device = await CalibrationStore.readDevice(cwd, name)
    if (!device) throw new Error(`unknown device "${name}"`)
    return CalibrationStore.writeDevice(cwd, { name, loaded })
  },

  // The /unregister path: delete the whole device directory (profile, driver,
  // and any confined assets like venvs/weights) plus its calibration records.
  // Per-device needs-calibration markers live IN the profile, so they go too.
  async removeDevice(cwd: string, name: string): Promise<void> {
    await fs.rm(await CalibrationStore.deviceDir(cwd, name), { recursive: true, force: true })
    const calibDir = path.join(await CalibrationStore.workspaceDir(cwd), "calib")
    if (!(await exists(calibDir))) return
    for (const entry of await fs.readdir(calibDir)) {
      if (entry.endsWith(`-${name}.json`)) await fs.rm(path.join(calibDir, entry), { force: true })
    }
  },

  async writeCalibration(cwd: string, result: CalibrationResult): Promise<string> {
    const name = result.deviceID ? `${result.routine}-${result.deviceID}` : result.routine
    const file = path.join(await CalibrationStore.workspaceDir(cwd), "calib", `${name}.json`)
    await writeJson(file, CalibrationResult.parse(result))
    return file
  },

  // --- needs-calibration queue: derived from per-section markers ------------

  async snapshot(cwd: string): Promise<CalibrationSnapshot> {
    const [robot, devices] = await Promise.all([CalibrationStore.readManifest(cwd), CalibrationStore.listDevices(cwd)])
    return { robot, devices }
  },

  needed({ robot, devices }: CalibrationSnapshot): NeededEntry[] {
    const entries: NeededEntry[] = []
    for (const [item, key] of Object.entries(ROBOT_ITEMS)) {
      const note = robot?.[key].needs_calibration
      if (note) entries.push({ item, note })
    }
    for (const device of devices) for (const section of DEVICE_SECTIONS) {
      const note = device[section]?.needs_calibration
      if (note) entries.push({ item: `${section}:${device.name}`, note })
    }
    return entries
  },

  async listNeeded(cwd: string): Promise<NeededEntry[]> {
    return CalibrationStore.needed(await CalibrationStore.snapshot(cwd))
  },

  async markNeeded(cwd: string, itemID: string, note?: string): Promise<void> {
    const fix = note ?? "needs calibration"
    const resolved = resolveItem(itemID)
    if (resolved.kind === "device") {
      const device = await CalibrationStore.readDevice(cwd, resolved.name)
      if (!device) throw new Error(`unknown device "${resolved.name}" — declare it first (calib_write kind device)`)
      const { checkCalibrationItem } = await import("./dag.ts")
      await checkCalibrationItem(cwd, await CalibrationStore.snapshot(cwd), itemID)
      await CalibrationStore.writeDevice(cwd, { name: resolved.name, [resolved.section]: { needs_calibration: fix } })
      return
    }
    await CalibrationStore.writeManifest(cwd, {
      [resolved.section]: { needs_calibration: fix },
    })
  },

  async clearNeeded(cwd: string, itemID: string): Promise<void> {
    const resolved = resolveItem(itemID)
    if (resolved.kind === "device") {
      await CalibrationStore.writeDevice(cwd, { name: resolved.name, [resolved.section]: { needs_calibration: null } })
      return
    }
    await CalibrationStore.writeManifest(cwd, { [resolved.section]: { needs_calibration: null } })
  },
}
