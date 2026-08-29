import { spawn } from 'node:child_process'
import { existsSync } from 'node:fs'
import { fileURLToPath } from 'node:url'

const repositoryRoot = fileURLToPath(new URL('../../../../', import.meta.url))
const dashboardRoot = fileURLToPath(new URL('../', import.meta.url))
const apiCommand = `${repositoryRoot}venv/bin/trading-analysis-dashboard`
const viteCommand = `${dashboardRoot}node_modules/.bin/vite`
const apiUrl = 'http://127.0.0.1:8765/api/health'
const viteUrl = 'http://127.0.0.1:5173/'
const children = new Set()
let stopping = false

function stop(exitCode = 0) {
  if (stopping) return
  stopping = true
  for (const child of children) child.kill('SIGTERM')
  setTimeout(() => process.exit(exitCode), 100).unref()
}

function start(command, args, label) {
  const child = spawn(command, args, { cwd: dashboardRoot, stdio: 'inherit' })
  children.add(child)
  child.on('error', (error) => {
    console.error(`[dashboard] Failed to start ${label}: ${error.message}`)
    stop(1)
  })
  child.on('exit', (code, signal) => {
    children.delete(child)
    if (!stopping) {
      console.error(`[dashboard] ${label} stopped (${signal || code || 0})`)
      stop(code || 1)
    }
  })
  return child
}

async function apiIsReady() {
  try {
    const response = await fetch(apiUrl)
    return response.ok
  } catch {
    return false
  }
}

async function dashboardViteIsReady() {
  try {
    const response = await fetch(viteUrl)
    return response.ok && (await response.text()).includes('<title>Trading Analysis</title>')
  } catch {
    return false
  }
}

async function waitForApi(child) {
  for (let attempt = 0; attempt < 50; attempt += 1) {
    if (await apiIsReady()) return
    if (child.exitCode !== null) throw new Error('Dashboard API exited before becoming ready.')
    await new Promise((resolve) => setTimeout(resolve, 100))
  }
  throw new Error('Dashboard API did not become ready within five seconds.')
}

process.on('SIGINT', () => stop(0))
process.on('SIGTERM', () => stop(0))

if (!existsSync(viteCommand)) {
  console.error('[dashboard] Frontend dependencies are missing. Run `npm install` first.')
  process.exit(1)
}

try {
  if (await apiIsReady()) {
    console.log('[dashboard] Reusing API already running at http://127.0.0.1:8765')
  } else {
    if (!existsSync(apiCommand)) {
      throw new Error('Dashboard CLI is missing. Run `./venv/bin/pip install -e modules/analysis`.')
    }
    const api = start(apiCommand, ['serve'], 'API')
    await waitForApi(api)
  }
  if (await dashboardViteIsReady()) {
    console.log(`[dashboard] Reusing dashboard already running at ${viteUrl}`)
  } else {
    start(viteCommand, [], 'Vite')
  }
} catch (error) {
  console.error(`[dashboard] ${error instanceof Error ? error.message : String(error)}`)
  stop(1)
}
