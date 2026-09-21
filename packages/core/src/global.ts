import os from "node:os"
import path from "node:path"
import fs from "node:fs/promises"

const home = os.homedir()
const xdgConfig = process.env["XDG_CONFIG_HOME"] ?? path.join(home, ".config")
const xdgData = process.env["XDG_DATA_HOME"] ?? path.join(home, ".local", "share")

export const Global = {
  Path: {
    config: process.env["KINEX_CONFIG_DIR"] ?? path.join(xdgConfig, "kinex"),
    data: process.env["KINEX_DATA_DIR"] ?? path.join(xdgData, "kinex"),
  },
  async init() {
    await Promise.all([
      fs.mkdir(Global.Path.config, { recursive: true }),
      fs.mkdir(Global.Path.data, { recursive: true }),
    ])
  },
}
