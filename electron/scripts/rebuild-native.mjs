import { execFileSync } from 'child_process'
import { join, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = join(__dirname, '..')

console.log('Rebuilding native modules for Electron...')

try {
  execFileSync('npx', ['electron-rebuild'], {
    cwd: rootDir,
    stdio: 'inherit'
  })
  console.log('Native modules rebuilt successfully')
} catch (error) {
  console.error('Failed to rebuild native modules:', error.message)
  process.exit(1)
}
