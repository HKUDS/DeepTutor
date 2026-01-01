import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

# Force unbuffered output for the main process
os.environ["PYTHONUNBUFFERED"] = "1"
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(line_buffering=True)


def print_flush(*args, **kwargs):
    """Print with flush=True by default"""
    kwargs.setdefault("flush", True)
    print(*args, **kwargs)


def terminate_process_tree(process, name="Process", timeout=5):
    """
    Terminate a process and all its children (process group).

    On Unix: Uses process group (PGID) to kill all children including uvicorn workers.
    On Windows: Uses taskkill /T to kill the process tree.

    Args:
        process: subprocess.Popen object
        name: Display name for logging
        timeout: Seconds to wait for graceful termination before SIGKILL
    """
    if process is None or process.poll() is not None:
        return  # Process already terminated

    pid = process.pid
    print_flush(f"🛑 Stopping {name} (PID: {pid})...")

    try:
        if os.name == "nt":
            # Windows: Use taskkill with /T to kill process tree
            subprocess.run(
                ["taskkill", "/F", "/T", "/PID", str(pid)],
                check=False,
                stderr=subprocess.DEVNULL,
                stdout=subprocess.DEVNULL,
            )
        else:
            # Unix: Kill the entire process group
            pgid = os.getpgid(pid)

            # Step 1: Send SIGTERM to the process group for graceful shutdown
            try:
                os.killpg(pgid, signal.SIGTERM)
                print_flush(f"   Sent SIGTERM to process group {pgid}")
            except ProcessLookupError:
                print_flush(f"   Process group {pgid} already terminated")
                return
            except PermissionError:
                # Fallback: try to terminate just the main process
                print_flush("   Cannot kill process group, trying single process")
                process.terminate()

            # Step 2: Wait for graceful termination
            try:
                process.wait(timeout=timeout)
                print_flush(f"   ✅ {name} terminated gracefully")
                return
            except subprocess.TimeoutExpired:
                print_flush(f"   ⚠️ {name} did not terminate in {timeout}s, sending SIGKILL...")

            # Step 3: Force kill with SIGKILL
            try:
                os.killpg(pgid, signal.SIGKILL)
                process.wait(timeout=2)
                print_flush(f"   ✅ {name} force killed")
            except ProcessLookupError:
                print_flush("   Process group already terminated")
            except Exception as e:
                print_flush(f"   ⚠️ Error during force kill: {e}")
                # Last resort: try to kill just the main process
                try:
                    process.kill()
                    process.wait(timeout=2)
                except Exception:
                    pass

    except Exception as e:
        print_flush(f"   ⚠️ Error stopping {name}: {e}")


def start_backend():
    print_flush(f"🚀 Starting FastAPI Backend using {sys.executable}...")
    base_dir = os.path.dirname(os.path.abspath(__file__))
    project_root = os.path.dirname(base_dir)
    print_flush(f"📁 Working directory: {base_dir}")
    print_flush(f"📁 Project root: {project_root}")

    # Ensure project root is in Python path
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Get port from configuration
    try:
        from src.core.setup import get_backend_port

        backend_port = get_backend_port(Path(project_root))
        print_flush(f"✅ Backend port configured: {backend_port}")
    except SystemExit:
        # Port configuration error already printed
        raise
    except Exception as e:
        print_flush(f"❌ Failed to get backend port: {e}")
        from src.core.setup import print_port_config_tutorial

        print_port_config_tutorial()
        raise

    # Check if api.main can be imported
    try:
        print_flush("✅ Backend module import successful")
    except Exception as e:
        print_flush(f"❌ Failed to import backend module: {e}")
        import traceback

        traceback.print_exc()
        raise

    # Use custom startup script for better reload handling
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    run_server_script = os.path.join(project_root, "src", "api", "run_server.py")
    cmd = [sys.executable, run_server_script]

    # Set environment variables for encoding and unbuffered output
    env = os.environ.copy()
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    env["PYTHONUNBUFFERED"] = "1"
    if os.name == "nt":
        env["PYTHONLEGACYWINDOWSSTDIO"] = "0"

    # Use start_new_session=True on Unix to create a new process group
    # This allows us to kill all child processes (including uvicorn workers) at once
    popen_kwargs = {
        "cwd": project_root,  # Run in project root directory, not scripts directory
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "shell": False,
        "encoding": "utf-8",
        "errors": "replace",
        "env": env,
    }

    # On Unix, create a new session so we can kill the entire process group
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    process = subprocess.Popen(cmd, **popen_kwargs)

    # Start a thread to output logs in real-time
    import threading

    def log_output():
        try:
            for line in iter(process.stdout.readline, ""):
                if line:
                    print_flush(f"[Backend]  {line.rstrip()}")
        except Exception as e:
            print_flush(f"[Backend]  Log output error: {e}")

    log_thread = threading.Thread(target=log_output, daemon=True)
    log_thread.start()

    print_flush(f"✅ Backend process started (PID: {process.pid})")
    if os.name != "nt":
        print_flush(f"   Process group ID (PGID): {os.getpgid(process.pid)}")
    return process


def start_frontend():
    print_flush("🚀 Starting Next.js Frontend...")
    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    web_dir = os.path.join(project_root, "web")

    # Ensure project root is in Python path
    if project_root not in sys.path:
        sys.path.insert(0, project_root)

    # Get port from configuration
    try:
        from pathlib import Path

        from src.core.setup import get_frontend_port

        frontend_port = get_frontend_port(Path(project_root))
        print_flush(f"✅ Frontend port configured: {frontend_port}")
    except SystemExit:
        # Port configuration error already printed
        raise
    except Exception as e:
        print_flush(f"❌ Failed to get frontend port: {e}")
        from src.core.setup import print_port_config_tutorial

        print_port_config_tutorial()
        raise

    # Check if npm is available
    npm_path = shutil.which("npm")
    if not npm_path:
        print_flush("❌ Error: 'npm' command not found!")
        print_flush("   Please install Node.js and npm first.")
        print_flush("   You can install it from: https://nodejs.org/")
        print_flush("   Or use a package manager like Homebrew: brew install node")
        raise RuntimeError("npm is not installed or not in PATH")

    print_flush(f"✅ Found npm at: {npm_path}")

    # Check if node_modules exists
    if not os.path.exists(os.path.join(web_dir, "node_modules")):
        print_flush("📦 Installing frontend dependencies...")
        print_flush("   This may take a few minutes, please wait...")
        try:
            npm_cmd = shutil.which("npm") or "npm"
            process = subprocess.Popen(
                [npm_cmd, "install"],
                cwd=web_dir,
                shell=False,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            for line in iter(process.stdout.readline, ""):
                if line:
                    if any(
                        keyword in line.lower()
                        for keyword in ["error", "failed", "added", "audited", "vulnerabilities"]
                    ):
                        print_flush(f"   {line.rstrip()}")

            process.wait()

            if process.returncode != 0:
                if os.path.exists(os.path.join(web_dir, "node_modules")):
                    print_flush("✅ Frontend dependencies installed (with warnings)")
                else:
                    print_flush(
                        f"❌ Failed to install frontend dependencies (exit code: {process.returncode})"
                    )
                    raise RuntimeError(f"npm install failed with exit code {process.returncode}")
            else:
                print_flush("✅ Frontend dependencies installed successfully")
        except Exception as e:
            print_flush(f"❌ Failed to install frontend dependencies: {e}")
            raise

    print_flush("🚀 Starting Next.js development server...")
    # Get backend port for frontend API configuration
    from pathlib import Path

    from src.core.setup import get_backend_port

    backend_port = get_backend_port(Path(project_root))

    # Generate/update .env.local file with port configuration
    # This ensures Next.js can read the backend port even if environment variables are not passed
    env_local_path = os.path.join(web_dir, ".env.local")
    try:
        with open(env_local_path, "w", encoding="utf-8") as f:
            f.write("# ============================================\n")
            f.write("# Auto-generated by start_web.py\n")
            f.write("# ============================================\n")
            f.write("# This file is automatically updated based on config/main.yaml\n")
            f.write("# Do not manually edit this file - it will be overwritten on startup\n")
            f.write("# To change the backend port, edit config/main.yaml instead\n")
            f.write("# ============================================\n\n")
            f.write(f"NEXT_PUBLIC_API_BASE=http://localhost:{backend_port}\n")
        print_flush(f"✅ Updated .env.local with backend port: {backend_port}")
    except Exception as e:
        print_flush(f"⚠️ Warning: Failed to update .env.local: {e}")
        print_flush("   Continuing with environment variables only...")

    # Set environment variables for Next.js (as backup)
    env = os.environ.copy()
    env["PORT"] = str(frontend_port)
    env["NEXT_PUBLIC_API_BASE"] = f"http://localhost:{backend_port}"
    # Set encoding environment variables for Windows
    env["PYTHONIOENCODING"] = "utf-8"
    env["PYTHONUTF8"] = "1"
    if os.name == "nt":
        env["PYTHONLEGACYWINDOWSSTDIO"] = "0"

    npm_cmd = shutil.which("npm") or "npm"

    # Use start_new_session=True on Unix to create a new process group
    # This allows us to kill all child processes (including Next.js workers) at once
    popen_kwargs = {
        "cwd": web_dir,
        "shell": False,
        "stdout": subprocess.PIPE,
        "stderr": subprocess.STDOUT,
        "text": True,
        "bufsize": 1,
        "env": env,
        "encoding": "utf-8",
        "errors": "replace",
    }

    # On Unix, create a new session so we can kill the entire process group
    if os.name != "nt":
        popen_kwargs["start_new_session"] = True

    frontend_process = subprocess.Popen(
        [npm_cmd, "run", "dev", "--", "-p", str(frontend_port)],
        **popen_kwargs,
    )

    # Start a thread to output frontend logs in real-time
    import threading

    def log_frontend_output():
        try:
            for line in iter(frontend_process.stdout.readline, ""):
                if line:
                    print_flush(f"[Frontend] {line.rstrip()}")
        except Exception as e:
            print_flush(f"[Frontend] Log output error: {e}")

    log_thread = threading.Thread(target=log_frontend_output, daemon=True)
    log_thread.start()

    print_flush(f"✅ Frontend process started (PID: {frontend_process.pid})")
    if os.name != "nt":
        print_flush(f"   Process group ID (PGID): {os.getpgid(frontend_process.pid)}")
    return frontend_process


if __name__ == "__main__":
    print_flush("=" * 50)
    print_flush("DeepTutor Web Platform Launcher")
    print_flush("=" * 50)

    # Initialize user data directories
    try:
        project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
        if project_root not in sys.path:
            sys.path.insert(0, project_root)
        from pathlib import Path

        from src.core.setup import init_user_directories

        init_user_directories(Path(project_root))
    except Exception as e:
        print_flush(f"⚠️ Warning: Failed to initialize user directories: {e}")
        print_flush("   Continuing anyway...")

    backend = None
    frontend = None

    try:
        backend = start_backend()

        # Get backend port for health check
        from pathlib import Path

        from src.core.setup import get_backend_port

        backend_port = get_backend_port(
            Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )

        print_flush("⏳ Waiting for backend to start...")
        for i in range(10):
            time.sleep(1)
            if backend.poll() is not None:
                print_flush(f"❌ Backend process exited with code {backend.returncode}")
                if backend.stdout:
                    output = backend.stdout.read()
                    if output:
                        print_flush(f"Backend output:\n{output}")
                break

            import socket

            try:
                sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
                result = sock.connect_ex(("localhost", backend_port))
                sock.close()
                if result == 0:
                    print_flush(f"✅ Backend is running on port {backend_port}!")
                    break
            except:
                pass

        if backend.poll() is not None:
            print_flush("❌ Backend failed to start. Please check the error messages above.")
            sys.exit(1)

        frontend = start_frontend()

        # Get ports for display
        from pathlib import Path

        from src.core.setup import get_ports

        backend_port, frontend_port = get_ports(
            Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
        )

        print_flush("")
        print_flush("=" * 50)
        print_flush("✅ Services are running!")
        print_flush("=" * 50)
        print_flush(f"   - Backend:  http://localhost:{backend_port}/docs")
        print_flush(f"   - Frontend: http://localhost:{frontend_port}")
        print_flush("=" * 50)
        print_flush("")
        print_flush("Press Ctrl+C to stop all services.")

        while True:
            if backend.poll() is not None:
                print_flush(
                    f"\n❌ Backend process exited unexpectedly (code: {backend.returncode})"
                )
                break
            time.sleep(1)

    except KeyboardInterrupt:
        print_flush("\n🛑 Stopping services...")
    except Exception as e:
        print_flush(f"\n❌ Error: {e}")
        import traceback

        traceback.print_exc()
    finally:
        # Use terminate_process_tree to properly kill all child processes
        # including uvicorn workers and Next.js child processes
        terminate_process_tree(backend, name="Backend", timeout=5)
        terminate_process_tree(frontend, name="Frontend", timeout=5)

        print_flush("✅ All services stopped.")
