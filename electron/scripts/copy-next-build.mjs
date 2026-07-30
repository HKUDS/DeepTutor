import { cpSync, mkdirSync, existsSync } from 'fs'
import { resolve, dirname } from 'path'
import { fileURLToPath } from 'url'

const __dirname = dirname(fileURLToPath(import.meta.url))
const rootDir = resolve(__dirname, '..')
const outDir = resolve(rootDir, 'out/renderer')

// Ensure output directory exists
mkdirSync(outDir, { recursive: true })

// Copy Next.js app HTML files to renderer
const nextAppDir = resolve(rootDir, '../web/.next/server/app')
if (existsSync(nextAppDir)) {
  cpSync(nextAppDir, resolve(outDir, 'app'), { recursive: true })
  console.log('Copied Next.js app files to renderer')
}

// Copy static files
const nextStaticDir = resolve(rootDir, '../web/.next/static')
if (existsSync(nextStaticDir)) {
  mkdirSync(resolve(outDir, '_next'), { recursive: true })
  cpSync(nextStaticDir, resolve(outDir, '_next/static'), { recursive: true })
  console.log('Copied Next.js static files to renderer')
}

// Copy any public files from web/public
const publicDir = resolve(rootDir, '../web/public')
if (existsSync(publicDir)) {
  cpSync(publicDir, outDir, { recursive: true })
  console.log('Copied public files to renderer')
}

console.log('Next.js build copied to renderer output')
