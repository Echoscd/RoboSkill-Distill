#!/usr/bin/env node
import path from "node:path"
import os from "node:os"
const config = process.env.KINEX_CONFIG_DIR ?? path.join(process.env.XDG_CONFIG_HOME ?? path.join(os.homedir(), ".config"), "kinex")
process.env.PI_CODING_AGENT_DIR = path.join(config, "agent")
process.env.PI_SKIP_VERSION_CHECK = "1"
process.env.PI_TELEMETRY = "0"
await import("../dist/cli.js")
