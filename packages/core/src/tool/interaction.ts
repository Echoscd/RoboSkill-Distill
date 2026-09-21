export interface QuestionOption {
  label: string
  description?: string
}

export interface Question {
  question: string
  header: string
  options: QuestionOption[]
  multiple?: boolean
}

// Fallback for runs with no interactive frontend (the TUI supplies its own
// questions handler through the loop input).
export async function askQuestions(questions: Question[]): Promise<Record<string, string>> {
  const answers: Record<string, string> = {}
  for (const question of questions) answers[question.question] = "(no user answer — interviews disabled; resolve choices from available evidence and continue, keeping unknown facts unknown)"
  return answers
}
