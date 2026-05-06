import { spawn, ChildProcess } from 'child_process'
import { app } from 'electron'
import { join } from 'path'
import log from 'electron-log'
import { existsSync } from 'fs'

export class BackendManager {
  private process: ChildProcess | null = null
  private port: number = 8001
  private maxRetries: number = 10
  private retryCount: number = 0

  async start(): Promise<void> {
    log.info('Starting DeepTutor backend...')

    const pythonPath = this.findPython()
    if (!pythonPath) {
      throw new Error('Python 3.11+ not found')
    }

    const backendPath = this.findBackendPath()
    log.info(`Backend path: ${backendPath}`)

    return new Promise((resolve, reject) => {
      this.process = spawn(pythonPath, [
        '-m', 'uvicorn',
        'deeptutor.api.main:app',
        '--host', '127.0.0.1',
        '--port', String(this.port)
      ], {
        cwd: app.isPackaged
          ? join(process.resourcesPath!, 'app')
          : join(__dirname, '../../..'),
        env: {
          ...process.env,
          PYTHONUNBUFFERED: '1',
          BACKEND_PORT: String(this.port)
        },
        stdio: ['ignore', 'pipe', 'pipe']
      })

      this.process.stdout?.on('data', (data: Buffer) => {
        const output = data.toString()
        log.info(`[Backend] ${output}`)
        if (output.includes('Uvicorn running on') && this.retryCount === 0) {
          this.retryCount++
          resolve()
        }
      })

      this.process.stderr?.on('data', (data: Buffer) => {
        log.warn(`[Backend Error] ${data.toString()}`)
      })

      this.process.on('error', (err) => {
        log.error('Backend process error:', err)
        reject(err)
      })

      this.process.on('exit', (code) => {
        log.info(`Backend exited with code ${code}`)
        this.process = null
      })

      this.waitForServer(resolve, reject)
    })
  }

  private waitForServer(resolve: () => void, reject: (err: Error) => void): void {
    setTimeout(() => {
      if (this.retryCount > 0) {
        resolve()
        return
      }
      if (this.retryCount >= this.maxRetries) {
        reject(new Error('Backend failed to start'))
        return
      }
      this.retryCount++
      this.waitForServer(resolve, reject)
    }, 1000)
  }

  private findPython(): string {
    const candidates = [
      'python3',
      'python',
      join(app.getPath('userData'), 'python/python3')
    ]
    for (const candidate of candidates) {
      if (existsSync(candidate)) {
        return candidate
      }
    }
    return 'python3'
  }

  private findBackendPath(): string {
    if (app.isPackaged) {
      return join(process.resourcesPath!, 'app')
    }
    return join(__dirname, '../../..')
  }

  stop(): void {
    if (this.process) {
      log.info('Stopping backend...')
      this.process.kill('SIGTERM')
      this.process = null
    }
  }

  getPort(): number {
    return this.port
  }

  isRunning(): boolean {
    return this.process !== null
  }
}
