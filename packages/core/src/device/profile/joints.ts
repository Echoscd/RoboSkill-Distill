import { z } from "zod"

const positive = z.number().positive()
const bounds = z.strictObject({ min: z.number(), max: z.number() }).refine((v) => v.min < v.max, "min must be below max")

export const Joint = z.strictObject({
  name: z.string().min(1), type: z.enum(["revolute", "continuous", "prismatic"]),
  limits: bounds.nullable(), max_velocity: positive.nullable(), max_effort: positive.nullable(),
}).superRefine((joint, ctx) => {
  if ((joint.type === "continuous") !== (joint.limits === null))
    ctx.addIssue({ code: "custom", path: ["limits"], message: "only continuous joints have null position limits" })
})

const vector = z.tuple([z.number(), z.number(), z.number()])
const pose = z.tuple([z.number(), z.number(), z.number(), z.number(), z.number(), z.number(), z.number()])
  .refine((v) => Math.abs(Math.hypot(...v.slice(3)) - 1) < 1e-5, "unit quaternion required")

export const Joints = z.array(Joint).min(1).refine((v) => new Set(v.map((j) => j.name)).size === v.length, "joint names must be unique")
export const ChainLink = z.union([
  z.strictObject({ origin: pose }),
  z.strictObject({ origin: pose, joint: z.number().int().nonnegative(),
    axis: vector.refine((v) => Math.abs(Math.hypot(...v) - 1) < 1e-5, "unit axis required"),
    anchor: vector, reference: z.number(),
  }),
])

export const JointSpeed = z.strictObject({
  max_velocity: z.record(z.string().min(1), positive).refine((v) => Object.keys(v).length > 0, "speed ceilings cannot be empty"),
  default_fraction: positive.max(1),
}).nullable()

export function jointConfigurationErrors(value: {
  home: Record<string, number> | null | "???",
  control: { speed: z.infer<typeof JointSpeed> | "???" } | "???",
}, model: { joints: z.infer<typeof Joints> }): string[] {
  const errors: string[] = []
  const names = model.joints.map((j) => j.name)
  const home = value.home
  const speed = value.control !== "???" ? value.control.speed : "???"
  for (const [label, map] of [["home", home], ["control.speed.max_velocity", speed !== "???" && speed !== null ? speed.max_velocity : speed]] as const) {
    if (map === "???" || map === null) continue
    if (Object.keys(map).length !== names.length || names.some((name) => !Object.hasOwn(map, name))) errors.push(`${label} must name every model joint exactly once`)
  }
  for (const joint of model.joints) {
    const q = home !== "???" && home !== null ? home[joint.name] : undefined
    if (q !== undefined && joint.limits && (q < joint.limits.min || q > joint.limits.max)) errors.push(`home exceeds limits for ${joint.name}`)
    if (speed !== "???" && speed !== null && joint.max_velocity !== null && (speed.max_velocity[joint.name] ?? 0) > joint.max_velocity)
      errors.push(`command speed exceeds model velocity limit for ${joint.name}`)
  }
  return errors
}
