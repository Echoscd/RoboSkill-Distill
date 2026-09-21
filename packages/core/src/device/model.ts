import { z } from "zod"
import { modelLifecycle, modelValueSchema } from "./profile/model.ts"
import { isModel, type Device } from "./profile/schema.ts"
import { NamedError } from "../util/error.ts"
import type { DeviceReading } from "./driver.ts"

class ModelContractError extends NamedError {
  constructor(message: string) { super("ModelContractError", message) }
}

export function modelOperation(device: Device, action: string) {
  if (!isModel(device)) return undefined
  if (modelLifecycle.some((name) => name === action)) return undefined
  const operation = device.intrinsics.operations.find((operation) => operation.name === action)
  if (!operation) throw new ModelContractError(`${device.name}: undeclared model operation ${action}`)
  return operation
}

type Operation = NonNullable<ReturnType<typeof modelOperation>>
export function modelInput(operation: Operation | undefined, args: Record<string, unknown>): Record<string, unknown> {
  if (!operation) return args
  const result = modelValueSchema(operation.input).safeParse(args)
  if (!result.success) throw new ModelContractError(`${operation.name} input: ${result.error.message}`)
  return z.record(z.string(), z.unknown()).parse(result.data)
}

export function modelOutput(operation: Operation | undefined, reading: DeviceReading): DeviceReading {
  if (!operation) return reading
  const payload = { ...reading.data, ...(reading.filePath ? { file: reading.filePath } : {}) }
  const result = modelValueSchema(operation.output, false).safeParse(payload)
  if (!result.success) throw new ModelContractError(`${operation.name} output: ${result.error.message}`)
  return reading
}
