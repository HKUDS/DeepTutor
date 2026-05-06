import { spawn, execSync } from 'child_process'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = resolve(__dirname, '..')

console.log('Starting Next.js dev server...')

// Start Next.js dev server in background
const nextProcess = spawn('npm', ['run', 'dev'], {
  cwd: resolve(rootDir, '../web'),
  shell: true,
  stdio: 'pipe'
})

nextProcess.stdout.on('data', (data) => {
  const output = data.toString()
  process.stdout.write(`[Next.js] ${output}`)
  // Wait for Next.js to be ready
  if (output.includes('Ready in') || output.includes('Local:')) {
    console.log('Next.js ready, starting Electron...')
    setTimeout(() => {
      const electronProcess = spawn('npx', ['electron-vite', 'dev'], {
        cwd: rootDir,
        shell: true,
        stdio: 'inherit'
      })

      electronProcess.on('close', (code) => {
        console.log(`Electron exited with code ${code}`)
        nextProcess.kill()
        process.exit(code || 0)
      })
    }, 3000)
  }
})

nextProcess.stderr.on('data', (data) => {
  process.stderr.write(`[Next.js Error] ${data}`)
})

nextProcess.on('close', (code) => {
  console.log(`Next.js exited with code ${code}`)
  process.exit(code || 0)
})

// Handle Ctrl+C
process.on('SIGINT', () => {
  console.log('Shutting down...')
  nextProcess.kill()
  process.exit(0)
})
