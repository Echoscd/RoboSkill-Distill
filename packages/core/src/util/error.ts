export class NamedError extends Error {
  constructor(
    name: string,
    message: string,
    public readonly data: Record<string, unknown> = {},
  ) {
    super(message)
    this.name = name
  }
}
