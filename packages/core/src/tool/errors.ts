import { NamedError } from "../util/error.ts"

export class PermissionDeniedError extends NamedError {
  constructor(
    permission: string,
    public feedback?: string,
  ) {
    super(
      "PermissionDeniedError",
      feedback
        ? `The user rejected permission "${permission}" with feedback: ${feedback}`
        : `The user rejected permission "${permission}". Do not retry the same action; ask the user how to proceed instead.`,
    )
  }
}

export class QuestionDeclinedError extends NamedError {
  constructor() {
    super(
      "QuestionDeclinedError",
      "The user declined to answer the questions and will follow up with instructions. Stop and wait for their next message.",
    )
  }
}
