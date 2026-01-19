#!/usr/bin/env python
"""
DeepTutor Installation Checker

Verifies that all required dependencies are correctly installed.
Run this script to diagnose installation issues.
"""

import importlib.metadata
import os
from pathlib import Path
import shutil
import subprocess
import sys

# Set Windows console UTF-8 encoding
if sys.platform == "win32":
    import io

    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8")


# Color codes for terminal output
class Colors:
    RED = "\033[0;31m"
    GREEN = "\033[0;32m"
    YELLOW = "\033[1;33m"
    BLUE = "\033[0;34m"
    CYAN = "\033[0;36m"
    NC = "\033[0m"  # No Color

    @classmethod
    def disable(cls):
        """Disable colors for non-TTY output"""
        cls.RED = cls.GREEN = cls.YELLOW = cls.BLUE = cls.CYAN = cls.NC = ""


# Disable colors if not a TTY
if not sys.stdout.isatty():
    Colors.disable()


def print_header(message: str):
    """Print section header"""
    print(f"\n{'=' * 60}")
    print(f"📋 {message}")
    print("=" * 60)


def print_success(message: str):
    """Print success message"""
    print(f"{Colors.GREEN}✅ {message}{Colors.NC}")


def print_error(message: str):
    """Print error message"""
    print(f"{Colors.RED}❌ {message}{Colors.NC}")


def print_warning(message: str):
    """Print warning message"""
    print(f"{Colors.YELLOW}⚠️  {message}{Colors.NC}")


def print_info(message: str):
    """Print info message"""
    print(f"{Colors.CYAN}ℹ️  {message}{Colors.NC}")


def get_package_version(package_name: str) -> str | None:
    """Get installed package version"""
    try:
        return importlib.metadata.version(package_name)
    except importlib.metadata.PackageNotFoundError:
        return None


def check_python_environment() -> bool:
    """Check Python environment"""
    print_header("Python Environment")

    all_ok = True

    # Python version
    py_version = sys.version_info
    print_info(f"Python version: {py_version.major}.{py_version.minor}.{py_version.micro}")

    if py_version >= (3, 10):
        print_success(f"Python {py_version.major}.{py_version.minor} meets requirement (>=3.10)")
    else:
        print_error(f"Python {py_version.major}.{py_version.minor} is below requirement (>=3.10)")
        all_ok = False

    # Python executable
    print_info(f"Python executable: {sys.executable}")

    # Virtual environment
    in_venv = hasattr(sys, "real_prefix") or (
        hasattr(sys, "base_prefix") and sys.base_prefix != sys.prefix
    )
    conda_env = os.environ.get("CONDA_DEFAULT_ENV")

    if conda_env:
        print_success(f"Conda environment: {conda_env}")
    elif in_venv:
        print_success(f"Virtual environment: {sys.prefix}")
    else:
        print_warning("No isolated environment detected (recommended: use conda or venv)")

    return all_ok


def check_backend_packages() -> tuple[bool, int, int]:
    """Check backend Python packages"""
    print_header("Backend Dependencies")

    # Required packages: (pip_name, import_name, min_version, is_optional)
    packages = [
        # Core
        ("python-dotenv", "dotenv", "1.0.0", False),
        ("PyYAML", "yaml", "6.0", False),
        ("tiktoken", "tiktoken", "0.5.0", False),
        ("jinja2", "jinja2", "3.1.0", False),
        # HTTP & API
        ("requests", "requests", "2.32.0", False),
        ("openai", "openai", "1.30.0", False),
        ("anthropic", "anthropic", "0.30.0", False),
        ("aiohttp", "aiohttp", "3.9.0", False),
        ("httpx", "httpx", "0.27.0", False),
        # Async
        ("nest-asyncio", "nest_asyncio", "1.5.8", False),
        ("tenacity", "tenacity", "8.0.0", False),
        # Web framework
        ("fastapi", "fastapi", "0.100.0", False),
        ("uvicorn", "uvicorn", "0.24.0", False),
        ("websockets", "websockets", "12.0", False),
        ("pydantic", "pydantic", "2.0.0", False),
        # RAG
        ("lightrag-hku", "lightrag", "1.0.0", False),
        ("raganything", "raganything", "0.1.0", False),
        ("llama-index", "llama_index", "0.14.0", False),
        # Document parsing
        ("docling", "docling", "2.31.0", True),  # Optional
        ("PyMuPDF", "fitz", "1.26.0", False),
        # Academic
        ("arxiv", "arxiv", "2.0.0", False),
        # Optional API clients
        ("perplexityai", "perplexity", "0.1.0", True),
        ("dashscope", "dashscope", "1.14.0", True),
    ]

    installed = 0
    missing = 0
    all_ok = True

    for pip_name, import_name, min_version, is_optional in packages:
        try:
            __import__(import_name)
            version = get_package_version(pip_name)
            version_str = f" (v{version})" if version else ""
            print_success(f"  ✓ {pip_name}{version_str}")
            installed += 1
        except ImportError:
            if is_optional:
                print_warning(f"  ⚠ {pip_name} not installed (optional)")
            else:
                print_error(f"  ✗ {pip_name} not installed")
                all_ok = False
                missing += 1

    return all_ok, installed, missing


def check_frontend_packages(project_root: Path) -> tuple[bool, int, int]:
    """Check frontend Node.js packages"""
    print_header("Frontend Dependencies")

    web_dir = project_root / "web"
    node_modules = web_dir / "node_modules"
    package_json = web_dir / "package.json"

    installed = 0
    missing = 0
    all_ok = True

    # Check npm
    npm_path = shutil.which("npm")
    if npm_path:
        try:
            result = subprocess.run(
                ["npm", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            npm_version = result.stdout.strip()
            print_success(f"npm available (v{npm_version})")
        except Exception:
            print_warning("npm found but version check failed")
    else:
        print_error("npm not found - Node.js is required for frontend")
        all_ok = False

    # Check node
    node_path = shutil.which("node")
    if node_path:
        try:
            result = subprocess.run(
                ["node", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            node_version = result.stdout.strip()
            print_success(f"Node.js available ({node_version})")
        except Exception:
            print_warning("Node.js found but version check failed")
    else:
        print_error("Node.js not found")
        all_ok = False

    # Check package.json exists
    if not package_json.exists():
        print_error(f"package.json not found: {package_json}")
        return False, 0, 0

    # Check node_modules
    if not node_modules.exists():
        print_error("node_modules directory does not exist")
        print_info("Run 'npm install' in web/ directory to install dependencies")
        return False, 0, 0

    # Check key packages
    key_packages = [
        "next",
        "react",
        "react-dom",
        "typescript",
        "tailwindcss",
        "@radix-ui/react-dialog",
        "lucide-react",
    ]

    print_info("Checking key frontend packages...")

    for pkg in key_packages:
        pkg_dir = node_modules / pkg
        if pkg_dir.exists():
            # Try to get version from package.json
            pkg_json = pkg_dir / "package.json"
            version = ""
            if pkg_json.exists():
                try:
                    import json

                    with open(pkg_json) as f:
                        data = json.load(f)
                        version = f" (v{data.get('version', '?')})"
                except Exception:
                    pass
            print_success(f"  ✓ {pkg}{version}")
            installed += 1
        else:
            print_error(f"  ✗ {pkg} not installed")
            missing += 1
            all_ok = False

    return all_ok, installed, missing


def check_system_tools() -> bool:
    """Check system tools and utilities"""
    print_header("System Tools")

    all_ok = True

    # Git
    git_path = shutil.which("git")
    if git_path:
        try:
            result = subprocess.run(
                ["git", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            git_version = result.stdout.strip()
            print_success(f"{git_version}")
        except Exception:
            print_warning("git found but version check failed")
    else:
        print_warning("git not found (optional but recommended)")

    # uv (fast Python package manager)
    uv_path = shutil.which("uv")
    if uv_path:
        try:
            result = subprocess.run(
                ["uv", "--version"],
                capture_output=True,
                text=True,
                timeout=10,
            )
            uv_version = result.stdout.strip()
            print_success(f"uv available ({uv_version})")
        except Exception:
            print_warning("uv found but version check failed")
    else:
        print_info("uv not found (optional, for faster package installation)")

    return all_ok


def check_env_file(project_root: Path) -> bool:
    """Check .env file configuration"""
    print_header("Environment Configuration")

    env_file = project_root / ".env"
    env_example = project_root / ".env.example"

    if env_file.exists():
        print_success(".env file exists")

        # Check for required keys (without revealing values)
        required_keys = [
            "OPENAI_API_KEY",
        ]
        optional_keys = [
            "ANTHROPIC_API_KEY",
            "PERPLEXITY_API_KEY",
            "DASHSCOPE_API_KEY",
        ]

        try:
            with open(env_file) as f:
                content = f.read()
                lines = content.split("\n")
                env_vars = {}
                for line in lines:
                    line = line.strip()
                    if line and not line.startswith("#") and "=" in line:
                        key = line.split("=")[0].strip()
                        value = line.split("=", 1)[1].strip() if "=" in line else ""
                        env_vars[key] = value

            for key in required_keys:
                if key in env_vars and env_vars[key]:
                    print_success(f"  ✓ {key} is set")
                else:
                    print_warning(f"  ⚠ {key} is not set (required for most features)")

            for key in optional_keys:
                if key in env_vars and env_vars[key]:
                    print_success(f"  ✓ {key} is set")
                else:
                    print_info(f"  ○ {key} is not set (optional)")

        except Exception as e:
            print_warning(f"Could not read .env file: {e}")

        return True
    else:
        print_warning(".env file not found")
        if env_example.exists():
            print_info("Copy .env.example to .env and configure your API keys")
        else:
            print_info("Create a .env file with your API keys (e.g., OPENAI_API_KEY)")
        return False


def main():
    """Main function"""
    print("\n" + "=" * 60)
    print("🔍 DeepTutor Installation Checker")
    print("=" * 60)
    print("Checking all dependencies and configurations...")

    # Get project root
    script_dir = Path(__file__).parent
    project_root = script_dir.parent

    print_info(f"Project root: {project_root}")

    # Track overall status
    all_checks_passed = True
    summary = []

    # 1. Python environment
    if check_python_environment():
        summary.append(("Python Environment", "✅ OK"))
    else:
        summary.append(("Python Environment", "❌ Issues found"))
        all_checks_passed = False

    # 2. Backend packages
    backend_ok, backend_installed, backend_missing = check_backend_packages()
    if backend_ok:
        summary.append(("Backend Dependencies", f"✅ OK ({backend_installed} packages)"))
    else:
        summary.append(
            ("Backend Dependencies", f"❌ {backend_missing} missing, {backend_installed} installed")
        )
        all_checks_passed = False

    # 3. Frontend packages
    frontend_ok, frontend_installed, frontend_missing = check_frontend_packages(project_root)
    if frontend_ok:
        summary.append(("Frontend Dependencies", f"✅ OK ({frontend_installed} packages)"))
    else:
        summary.append(
            (
                "Frontend Dependencies",
                f"❌ {frontend_missing} missing, {frontend_installed} installed",
            )
        )
        all_checks_passed = False

    # 4. System tools
    check_system_tools()
    summary.append(("System Tools", "✅ Checked"))

    # 5. Environment configuration
    if check_env_file(project_root):
        summary.append(("Environment Config", "✅ .env exists"))
    else:
        summary.append(("Environment Config", "⚠️ .env missing"))

    # Print summary
    print_header("Summary")

    for item, status in summary:
        print(f"  {item}: {status}")

    print("")
    if all_checks_passed:
        print_success("All required dependencies are installed!")
        print_info("You can start DeepTutor with: python scripts/start_web.py")
    else:
        print_error("Some dependencies are missing!")
        print_info("Run: python scripts/install_all.py")
        print_info("Or manually install missing packages")

    print("=" * 60 + "\n")

    return 0 if all_checks_passed else 1


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\n⚠️  Check interrupted by user")
        sys.exit(1)
    except Exception as e:
        print_error(f"\n❌ Unexpected error: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
