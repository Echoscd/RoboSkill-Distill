import { main } from "@earendil-works/pi-coding-agent"

// Pi's public CLI exits the process; keep it outside the parent's cleanup scope.
await main(process.argv.slice(2))
