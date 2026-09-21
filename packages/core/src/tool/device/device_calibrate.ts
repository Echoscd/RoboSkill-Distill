import { z } from "zod"
import { define } from "../tool.ts"
import { noRobot, unloadedDevice } from "./shared.ts"
import { getRoutine, ROUTINES } from "../../calibration/routines/index.ts"
import { CalibrationStore } from "../../calibration/store.ts"
import DESCRIPTION from "./device_calibrate.txt"

export const DeviceCalibrateTool = define("device_calibrate", {
  description: DESCRIPTION,
  parameters: z.object({
    routine: z.string().describe("routine name, e.g. urdf-introspect"),
    deviceID: z.string().optional().describe("target device for device-specific routines"),
  }),
  execute: async (args, ctx) => {
    const robot = await CalibrationStore.readManifest(ctx.directory)
    if (!robot) return noRobot()
    const routine = getRoutine(args.routine)
    if (!routine)
      return {
        title: "unknown routine",
        output: `unknown routine "${args.routine}". Available: ${ROUTINES.map((entry) => `${entry.name} (${entry.platforms.join("/")})`).join(", ")}`,
      }
    if (args.deviceID) {
      const device = await CalibrationStore.readDevice(ctx.directory, args.deviceID)
      if (device && !device.loaded) return unloadedDevice(device)
    }
    if (!routine.platforms.includes(robot.identity.platform))
      return {
        title: "routine not applicable",
        output: `routine ${routine.name} applies to ${routine.platforms.join("/")} robots, but ${robot.identity.id} is platform "${robot.identity.platform}"`,
      }
    await ctx.ask({ permission: "device_calibrate", description: `run ${routine.name} (requires: ${routine.requires})` })
    const result = await routine.run({ cwd: ctx.directory, robot, deviceID: args.deviceID })
    const file = await CalibrationStore.writeCalibration(ctx.directory, result)
    return {
      title: `${routine.name}: ${result.status}`,
      output: [`status: ${result.status}`, result.notes ?? "", `result stored at ${file}`].filter(Boolean).join("\n"),
      isError: result.status === "failed",
    }
  },
})
