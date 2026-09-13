import { existsSync } from 'node:fs'
import { dirname, join, delimiter } from 'node:path'
import { fileURLToPath } from 'node:url'
import { spawnSync } from 'node:child_process'

const root = dirname(fileURLToPath(import.meta.url))
process.chdir(root)
const env = { ...process.env, PATH: `${dirname(process.execPath)}${delimiter}${process.env.PATH || ''}` }
const run = (command, args, shell = false) => {
  const result = spawnSync(command, args, { cwd: root, env, stdio: 'inherit', shell })
  if (result.error) console.error(result.error.message)
  return result.status ?? 1
}
if (!existsSync(join(root, 'node_modules/vite/bin/vite.js'))) {
  console.log('Installing dashboard dependencies (first run only)...')
  const bundledPnpm = join(dirname(process.execPath), '../node_modules/pnpm/bin/pnpm.cjs')
  const result = existsSync(bundledPnpm)
    ? run(process.execPath, [bundledPnpm, 'install', '--frozen-lockfile', '--store-dir', '.pnpm-store'])
    : run(process.platform === 'win32' ? 'npm.cmd' : 'npm', ['install'], process.platform === 'win32')
  if (result !== 0) process.exit(result)
}
console.log('\nOpen http://127.0.0.1:5173 in your browser. Press Ctrl+C to stop.\n')
process.exit(run(process.execPath, [join(root, 'node_modules/vite/bin/vite.js')]))
