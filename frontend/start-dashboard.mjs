import { existsSync } from 'node:fs'
import { dirname, join } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = dirname(fileURLToPath(import.meta.url))
process.chdir(root)
const run = (command, args, shell = false) => {
  const result = spawnSync(command, args, { cwd: root, stdio: 'inherit', shell })
  if (result.error) console.error(result.error.message)
  return result.status ?? 1
}
if (!existsSync(join(root, 'node_modules/vite/bin/vite.js'))) {
  console.log('Installing dashboard dependencies (first run only)...')
  const pnpm = process.platform === 'win32' ? 'pnpm.cmd' : 'pnpm'
  const result = run(pnpm, ['install', '--frozen-lockfile'], process.platform === 'win32')
  if (result !== 0) process.exit(result)
}
console.log('\nOpen http://127.0.0.1:5173 in your browser. Press Ctrl+C to stop.\n')
process.exit(run(process.execPath, [join(root, 'node_modules/vite/bin/vite.js'), '--open']))
