#!/usr/bin/env python3
"""Install GIMP 3 plugins into the latest GIMP plug-ins directory.

Usage:
    python install.py              # interactive install
    python install.py --help       # show this message
    python install.py --dry-run    # preview without making changes
    python install.py --uninstall  # remove installed plugins
"""

import argparse
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

PLUGINS_DIR = Path(__file__).resolve().parent
PLUGIN_DIRS = sorted(
    d for d in PLUGINS_DIR.iterdir()
    if d.is_dir() and not d.name.startswith(".") and d.name != "__pycache__"
    and d.name != "test_plugin"
)
SKIP_DIRS = {"locale", "images", ".venv", "__pycache__"}


def _find_sd_repo() -> Path:
    """Return the path to stable-diffusion.cpp source, checking both common locations."""
    downloads = Path.home() / "Downloads"
    for candidate in (downloads / "stable-diffusion.cpp", downloads / "src/stable-diffusion.cpp"):
        if candidate.is_dir():
            return candidate
    if os.name == "nt":
        return downloads / "stable-diffusion.cpp"
    return downloads / "src/stable-diffusion.cpp"


PLUGIN_DEPS = {
    "bgremove": {
        "pip": ["numpy<2.5", "numba>=0.66.0", "backgroundremover"],
        "cli": [],
        "cmd": "pip install --user 'numpy<2.5' 'numba>=0.66.0' backgroundremover",
    },
    "upscale": {
        "pip": ["image_gen_aux", "diffusers", "torch", "pillow"],
        "cli": [],
        "cmd": "pip install --user image_gen_aux diffusers torch pillow",
    },
    "aiedit": {
        "pip": [],
        "cli": ["sd-cli"],
        "cmd": "sd-cli binary (see https://github.com/leejet/stable-diffusion.cpp)",
    },
    "sd-server": {
        "pip": ["requests"],
        "cli": [],
        "cmd": "pip install --user requests",
    },
}


# ── Logging ────────────────────────────────────────────────────────────────

def _log_info(msg: str) -> None:
    print(f"  \u00b7 {msg}")


def _log_ok(msg: str) -> None:
    print(f"  \u2713 {msg}")


def _log_fail(msg: str) -> None:
    print(f"  \u2717 {msg}")


def _log_warn(msg: str) -> None:
    print(f"  ! {msg}")


def _log_step(msg: str) -> None:
    print(f"\n  \u2192 {msg}")


def _log_action(msg: str) -> None:
    print(f"     {msg}")


# ── Platform helpers ──────────────────────────────────────────────────────

def _is_admin() -> bool:
    """Return True if the process has root/administrator privileges."""
    if os.name == "nt":
        try:
            import ctypes
            return ctypes.windll.shell32.IsUserAnAdmin() != 0
        except (ImportError, AttributeError):
            return False
    try:
        return os.geteuid() == 0
    except AttributeError:
        return False


def _platform_pkg_manager() -> str | None:
    """Detect the package manager on this system."""
    if sys.platform == "linux":
        for pm in ("apt", "dnf", "pacman", "zypper", "apk"):
            if shutil.which(pm):
                return pm
    elif sys.platform == "darwin":
        if shutil.which("brew"):
            return "brew"
        if shutil.which("port"):
            return "port"
    elif os.name == "nt":
        if shutil.which("winget"):
            return "winget"
        if shutil.which("choco"):
            return "choco"
        if shutil.which("scoop"):
            return "scoop"
    return None


def _install_cmd(pm: str, *packages: str) -> str | None:
    """Return the install command for a package manager and package list."""
    table = {
        "apt":    "apt install -y",
        "dnf":    "dnf install -y",
        "pacman": "pacman -S --noconfirm",
        "zypper": "zypper install -y",
        "apk":    "apk add",
        "brew":   "brew install",
        "port":   "port install",
        "winget": "winget install",
        "choco":  "choco install -y",
        "scoop":  "scoop install",
    }
    prefix = table.get(pm)
    if prefix is None:
        return None
    return prefix + " " + " ".join(packages)


def _pkg_name(pm: str | None, cmd: str) -> str:
    """Map command name to package name for the given package manager."""
    overrides = {
        "apt":    {"pip": "python3-pip", "pip3": "python3-pip"},
        "dnf":    {"pip": "python3-pip", "pip3": "python3-pip"},
        "zypper": {"pip": "python3-pip", "pip3": "python3-pip"},
        "apk":    {"pip": "py3-pip",     "pip3": "py3-pip"},
    }
    return overrides.get(pm, {}).get(cmd, cmd)


def _ensure_command(cmd: str, label: str | None = None) -> bool:
    """Check if a command is available.

    If missing, detect admin + package manager and offer to install.
    Returns True if the command is now available.
    """
    if shutil.which(cmd):
        return True

    label = label or cmd
    pm = _platform_pkg_manager()
    pkg = _pkg_name(pm, cmd)
    install_cmd_str = _install_cmd(pm, pkg) if pm else None

    _log_fail(f"{label} is required but was not found.")

    if install_cmd_str and _is_admin():
        if _prompt_yes_no(f"  Install {pkg} via `{install_cmd_str}`?"):
            try:
                result = subprocess.run(
                    install_cmd_str, shell=True, capture_output=True, text=True
                )
                if result.returncode == 0:
                    _log_ok(f"{pkg} installed.")
                    return shutil.which(cmd) is not None
                _log_fail(f"Installation failed (exit {result.returncode}).")
                if result.stderr.strip():
                    _log_action(result.stderr.strip()[:200])
            except OSError as e:
                _log_fail(f"Could not run installer: {e}")
        else:
            _log_action(f"Run manually: {install_cmd_str}")
    elif install_cmd_str:
        _log_action(f"Run (as admin): {install_cmd_str}")
    else:
        _log_action(f"Install {pkg} using your system's package manager.")

    return False


# ── Dependency checks ─────────────────────────────────────────────────────

def _check_pip() -> bool:
    return shutil.which("pip") is not None or shutil.which("pip3") is not None


def _pip_installed(pkg: str) -> bool:
    pip_cmd = "pip" if shutil.which("pip") else "pip3"
    if not pip_cmd:
        return False
    try:
        result = subprocess.run(
            [pip_cmd, "show", pkg],
            capture_output=True, text=True, timeout=15,
        )
        return result.returncode == 0
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return False


def _run_pip_install(cmd: str, dry_run: bool = False) -> bool:
    """Run a pip install command. Returns True on success."""
    if not _check_pip():
        _log_fail("pip is not available; cannot install Python packages.")
        return False
    if dry_run:
        _log_info(f"Would run: {cmd}")
        return True
    try:
        result = subprocess.run(cmd, shell=True)
        return result.returncode == 0
    except OSError as e:
        _log_fail(f"Failed to run pip: {e}")
        return False


def _check_plugin_deps(plugin_name: str) -> dict:
    deps = PLUGIN_DEPS.get(plugin_name)
    if deps is None:
        return {"status": "unknown", "missing": [], "cmd": None}

    results = {}
    for pkg in deps["pip"]:
        results[pkg] = _pip_installed(pkg)
    for binary in deps["cli"]:
        results[binary] = shutil.which(binary) is not None

    missing = [name for name, ok in results.items() if not ok]
    if not missing:
        return {"status": "ok", "missing": [], "cmd": deps["cmd"]}
    return {"status": "missing", "missing": missing, "cmd": deps["cmd"]}


def _prompt_yes_no(prompt: str) -> bool:
    while True:
        try:
            answer = input(f"{prompt} [y/N] ").strip().lower()
        except (EOFError, KeyboardInterrupt):
            print()
            return False
        if answer in ("y", "yes"):
            return True
        if answer in ("", "n", "no"):
            return False


# ── sd-cli build (aiedit) ──────────────────────────────────────────────────

def _detect_accelerator() -> str | None:
    """Detect the best available GPU accelerator for sd-cli."""
    if shutil.which("nvcc"):
        return "cuda"
    if shutil.which("rocminfo"):
        return "hipblas"
    if sys.platform == "darwin" and os.path.exists(
        "/System/Library/Frameworks/Metal.framework"
    ):
        return "metal"
    if shutil.which("vulkaninfo") or shutil.which("glslc"):
        return "vulkan"
    if shutil.which("icpx"):
        return "sycl"
    if shutil.which("pkg-config") and not subprocess.run(
        ["pkg-config", "--exists", "openblas"],
        capture_output=True, text=True, timeout=10,
    ).returncode:
        return "openblas"
    return None


def _build_sd_cli(dry_run: bool = False) -> bool:
    """Download, build, and install sd-cli. Returns True on success."""
    if not _ensure_command("git", "git"):
        return False

    sd_repo = _find_sd_repo()

    if not sd_repo.exists():
        _log_step("Cloning stable-diffusion.cpp...")
        if dry_run:
            _log_info("Would clone https://github.com/leejet/stable-diffusion.cpp")
        else:
            try:
                result = subprocess.run(
                    ["git", "clone", "--recursive",
                     "https://github.com/leejet/stable-diffusion.cpp", str(sd_repo)],
                    capture_output=True, text=True, timeout=300,
                )
                if result.returncode != 0:
                    _log_fail("Clone failed.")
                    if result.stderr.strip():
                        _log_action(result.stderr.strip()[:300])
                    return False
                _log_ok("Repository cloned.")
            except subprocess.TimeoutExpired:
                _log_fail("Clone timed out after 5 minutes.")
                return False
            except OSError as e:
                _log_fail(f"Clone error: {e}")
                return False

    if not _ensure_command("cmake", "cmake"):
        return False

    build_dir = sd_repo / "build"
    if build_dir.exists():
        if dry_run:
            _log_info("Would clean build directory")
        else:
            try:
                shutil.rmtree(build_dir)
            except OSError as e:
                _log_fail(f"Could not clean build directory: {e}")
                return False

    if dry_run:
        _log_info("Would configure and build sd-cli from source")
        return True

    # Detect accelerator and build
    accel = _detect_accelerator()
    cmake_flags = "-DCMAKE_CXX_FLAGS=-w"

    if accel == "cuda":
        _log_step("Building with CUDA acceleration...")
        cmake_flags += " -DSD_CUDA=ON"
    elif accel == "hipblas":
        _log_step("Building with AMD ROCm/HipBLAS acceleration...")
        gfx_name = None
        try:
            result = subprocess.run(
                ["rocminfo"], capture_output=True, text=True, timeout=30
            )
            match = re.search(r"Name:\s+(gfx\S+)", result.stdout)
            if match:
                gfx_name = match.group(1)
                _log_info(f"Detected GPU: {gfx_name}")
        except (FileNotFoundError, subprocess.TimeoutExpired):
            pass
        cmake_flags += " -DSD_HIPBLAS=ON"
        if gfx_name:
            cmake_flags += f" -DGPU_TARGETS={gfx_name} -DAMDGPU_TARGETS={gfx_name}"
    elif accel == "metal":
        _log_step("Building with Metal acceleration...")
        cmake_flags += " -DSD_METAL=ON"
    elif accel == "vulkan":
        _log_step("Building with Vulkan acceleration...")
        cmake_flags += " -DSD_VULKAN=ON"
    elif accel == "sycl":
        _log_step("Building with Intel SYCL acceleration...")
        cmake_flags += " -DSD_SYCL=ON"
    elif accel == "openblas":
        _log_step("Building with OpenBLAS acceleration...")
        cmake_flags += " -DGGML_OPENBLAS=ON"
    else:
        _log_step("Building for CPU only (no GPU accelerator detected)...")

    # cmake configure
    _log_info("Configuring build...")
    try:
        result = subprocess.run(
            f"cmake -B build {cmake_flags}", shell=True, cwd=sd_repo,
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            _log_fail("cmake configuration failed.")
            tail = result.stderr.strip().splitlines()[-5:]
            for line in tail:
                _log_action(line)
            return False
    except subprocess.TimeoutExpired:
        _log_fail("cmake configuration timed out.")
        return False
    except OSError as e:
        _log_fail(f"cmake error: {e}")
        return False

    # cmake build
    _log_info("Compiling (this may take a while)...")
    try:
        result = subprocess.run(
            ["cmake", "--build", "build", "--config", "Release"],
            cwd=sd_repo, capture_output=True, text=True, timeout=600,
        )
        if result.returncode != 0:
            _log_fail("Build failed.")
            tail = result.stderr.strip().splitlines()[-5:]
            for line in tail:
                _log_action(line)
            return False
    except subprocess.TimeoutExpired:
        _log_fail("Build timed out after 10 minutes.")
        return False
    except OSError as e:
        _log_fail(f"Build error: {e}")
        return False

    # cmake install
    _log_info("Installing to ~/.local/bin...")
    try:
        result = subprocess.run(
            ["cmake", "--install", "build", "--prefix", str(Path.home() / ".local")],
            cwd=sd_repo, capture_output=True, text=True, timeout=60,
        )
        if result.returncode != 0:
            _log_fail("Install failed.")
            if result.stderr.strip():
                _log_action(result.stderr.strip()[:200])
            return False
    except OSError as e:
        _log_fail(f"Install error: {e}")
        return False

    found = shutil.which("sd-cli") is not None
    if found:
        _log_ok("sd-cli built and installed.")
    else:
        _log_warn("sd-cli was installed but is not on PATH. Add ~/.local/bin to your PATH.")
    return found


def _handle_aiedit_deps(dry_run: bool = False) -> bool:
    """Handle the sd-cli dependency for aiedit. Returns True if satisfied."""
    if shutil.which("sd-cli"):
        return True

    _log_step("sd-cli is required by aiedit but was not found on PATH.")
    _log_action(f"Source repo: {_find_sd_repo()}")
    print()

    if not _prompt_yes_no("Download and build stable-diffusion.cpp?"):
        _log_info("Skipped. You can get sd-cli from:")
        _log_action("https://github.com/leejet/stable-diffusion.cpp/releases")
        return False

    if dry_run:
        _log_info("Would build sd-cli from source")
        return True

    accel = _detect_accelerator()

    if accel == "cuda":
        _log_info("Detected: nvcc (CUDA) + cmake")
        if not _prompt_yes_no("Build sd-cli with CUDA acceleration?"):
            return False
        return _build_sd_cli()

    if accel == "hipblas":
        _log_info("Detected: ROCm (AMD GPU) + cmake")
        if not _prompt_yes_no("Build sd-cli with AMD ROCm/HipBLAS acceleration?"):
            return False
        return _build_sd_cli()

    if accel:
        accel_name = {
            "metal": "Metal (Apple GPU)",
            "vulkan": "Vulkan",
            "sycl": "Intel SYCL",
            "openblas": "OpenBLAS",
        }.get(accel, accel)
        _log_info(f"Detected: {accel_name} + cmake")
        if _prompt_yes_no(f"Build sd-cli with {accel_name} acceleration?"):
            return _build_sd_cli()
        print()
        if _prompt_yes_no("Build for CPU instead (slower)?"):
            return _build_sd_cli()
        return False

    _log_info("No GPU accelerator detected.")
    if _prompt_yes_no("Build sd-cli for CPU only (slower)?"):
        return _build_sd_cli()

    _log_warn("Consider installing accelerated drivers for your GPU:")
    if sys.platform == "linux":
        _log_action("NVIDIA: apt install nvidia-cuda-toolkit")
        _log_action("AMD:    https://rocm.docs.amd.com")
        _log_action("Intel:  https://www.intel.com/oneapi")
    elif sys.platform == "darwin":
        _log_action("Apple:  xcode-select --install")
    elif sys.platform == "win32":
        _log_action("NVIDIA: https://developer.nvidia.com/cuda-downloads")
        _log_action("AMD:    https://rocm.docs.amd.com")
    _log_info("Then re-run this installer.")
    return False


# ── pip dependency installation ───────────────────────────────────────────

def _prompt_install_deps(plugins: list[Path], dry_run: bool = False) -> list[tuple[str, bool]]:
    """Prompt and install missing pip dependencies.

    Returns list of (plugin_name, success) for each attempted install.
    """
    has_pip = _check_pip()

    install_commands: list[tuple[str, str]] = []
    results: list[tuple[str, bool]] = []

    for plugin in plugins:
        info = _check_plugin_deps(plugin.name)
        if info["status"] == "ok" or not info["missing"]:
            _log_ok(f"{plugin.name} \u2014 dependencies satisfied")
        else:
            _log_fail(f"{plugin.name} \u2014 missing: {', '.join(info['missing'])}")
            if info["cmd"]:
                install_commands.append((plugin.name, info["cmd"]))

    if not install_commands:
        return results

    print()
    for name, cmd in install_commands:
        _log_info(f"{name}: {cmd}")
    print()

    if not _prompt_yes_no("Install missing pip dependencies now?"):
        for name, _ in install_commands:
            results.append((name, False))
        return results

    if not has_pip:
        _log_fail("pip is not available; cannot install Python packages.")
        for name, _ in install_commands:
            results.append((name, False))
        return results

    for name, cmd in install_commands:
        _log_step(f"Installing {name} dependencies...")
        if _run_pip_install(cmd, dry_run=dry_run):
            _log_ok(f"{name} dependencies installed.")
            results.append((name, True))
        else:
            _log_fail(f"{name} installation failed.")
            results.append((name, False))

    return results


# ── GIMP directory discovery ─────────────────────────────────────────────

def _scan_gimp_dir(base: Path, candidates: list[Path]) -> None:
    gimp_dir = base / "GIMP"
    if gimp_dir.is_dir():
        for child in gimp_dir.iterdir():
            plugins = child / "plug-ins"
            if plugins.is_dir():
                candidates.append(plugins)


def find_gimp_plugins_dir() -> Path | None:
    candidates: list[Path] = []

    _scan_gimp_dir(
        Path(os.environ.get("XDG_CONFIG_HOME", Path.home() / ".config")), candidates
    )

    if os.name == "nt":
        for var in ("APPDATA", "LOCALAPPDATA"):
            val = os.environ.get(var)
            if val:
                _scan_gimp_dir(Path(val), candidates)
        _scan_gimp_dir(Path.home() / ".config", candidates)

    try:
        result = subprocess.run(
            ["locate", "-r", r"GIMP/.*/plug-ins$"],
            capture_output=True, text=True, timeout=10,
        )
        for path in result.stdout.strip().splitlines():
            p = Path(path)
            if p.is_dir():
                candidates.append(p)
    except (FileNotFoundError, subprocess.TimeoutExpired, subprocess.CalledProcessError):
        pass

    flatpak = Path.home() / ".var/app/org.gimp.GIMP/config/GIMP"
    if flatpak.is_dir():
        for child in flatpak.iterdir():
            plugins = child / "plug-ins"
            if plugins.is_dir():
                candidates.append(plugins)

    if not candidates:
        return None

    def version_key(p: Path) -> tuple:
        match = re.search(r"(\d+)\.(\d+)", str(p.parent))
        if match:
            return int(match.group(1)), int(match.group(2))
        return (0, 0)

    return max(set(candidates), key=version_key)


# ── Plugin file installation ─────────────────────────────────────────────

def symlink_plugin(src: Path, dst_dir: Path, dry_run: bool = False) -> bool:
    """Install a plugin as a symlink. Returns True on success."""
    dst = dst_dir / src.name
    if dst.is_symlink() or dst.exists():
        if dst.resolve() == src.resolve():
            _log_ok(f"{src.name} (already installed)")
            return True
        _log_warn(f"{src.name} exists at {dst}, replacing")
        if dry_run:
            _log_info("Would remove existing installation")
            return True
        try:
            if dst.is_symlink() or dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
        except OSError as e:
            _log_fail(f"Could not remove existing {dst}: {e}")
            return False
    if dry_run:
        _log_ok(f"{src.name} (would symlink)")
        return True
    try:
        os.symlink(src, dst, target_is_directory=True)
        _log_ok(src.name)
        return True
    except OSError:
        return False


def copy_plugin(src: Path, dst_dir: Path, dry_run: bool = False) -> bool:
    """Install a plugin by copying. Returns True on success."""
    dst = dst_dir / src.name
    # Remove any existing destination (file, symlink, directory, or dangling symlink)
    if dst.is_symlink() or dst.exists() or dst.is_symlink():
        if dry_run:
            _log_info("Would remove existing installation")
        else:
            try:
                dst.unlink()
            except OSError:
                try:
                    shutil.rmtree(dst)
                except OSError as e:
                    _log_fail(f"Could not remove existing {dst}: {e}")
                    return False
    if dry_run:
        _log_ok(f"{src.name} (would copy)")
        return True
    try:
        shutil.copytree(
            src, dst,
            ignore=shutil.ignore_patterns(".venv", "__pycache__", "__pycache__"),
        )
        # Also copy locale directories since they are needed for i18n
        src_locale = src / "locale"
        dst_locale = dst / "locale"
        if src_locale.is_dir() and not dst_locale.is_dir():
            try:
                shutil.copytree(src_locale, dst_locale)
            except OSError as e:
                _log_warn(f"Could not copy locale directory: {e}")
        _log_ok(src.name)
        return True
    except OSError as e:
        _log_fail(f"Failed to copy {src.name}: {e}")
        return False


def _uninstall_plugins(plugins: list[Path], dest: Path) -> None:
    """Remove previously installed plugins from the GIMP plug-ins directory."""
    _log_step("Removing installed plugins...")
    for plugin in plugins:
        dst = dest / plugin.name
        if not (dst.is_symlink() or dst.exists() or dst.is_symlink()):
            _log_info(f"{plugin.name} (not installed)")
            continue
        try:
            if dst.is_symlink() or dst.is_file():
                dst.unlink()
            else:
                shutil.rmtree(dst)
            _log_ok(f"{plugin.name} removed")
        except OSError as e:
            _log_fail(f"Could not remove {plugin.name}: {e}")


# ── Main ─────────────────────────────────────────────────────────────────

def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Install GIMP 3 plugins into the latest GIMP plug-ins directory.",
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Preview what would be done without making changes.",
    )
    parser.add_argument(
        "--uninstall", action="store_true",
        help="Remove installed plugins instead of installing.",
    )
    parser.add_argument(
        "--dest", type=str, default=None,
        help="Target GIMP plug-ins directory (skip auto-detection).",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    args = _parse_args(argv)
    dry_run = args.dry_run
    uninstall = args.uninstall

    print("GIMP 3 Plugin Installer")
    print("=" * 40)
    if dry_run:
        print("  DRY RUN — no changes will be made")
    print()

    # pip check
    if not _check_pip():
        _log_warn("pip is not found on this system.")
        _ensure_command("pip3", "pip") or _ensure_command("pip", "pip")
        if not _check_pip():
            _log_warn("pip is not available; Python package dependencies will be skipped.")
        print()

    # Discover plugins
    plugins = [d for d in PLUGIN_DIRS if d.name not in SKIP_DIRS]
    if not plugins:
        _log_fail("No plugin directories found to install.")
        _log_action(f"Expected plugin directories in: {PLUGINS_DIR}")
        sys.exit(1)

    _log_info(f"Found {len(plugins)} plugin(s): {', '.join(p.name for p in plugins)}")
    print()

    # Check if aiedit needs sd-cli build
    aiedit_needs_build = (
        any(p.name == "aiedit" for p in plugins)
        and not shutil.which("sd-cli")
    )

    # Handle pip dependencies
    _log_step("Checking Python package dependencies...")
    pip_results = _prompt_install_deps(plugins, dry_run=dry_run)

    # Handle sd-cli build for aiedit
    sd_cli_ok = True
    if aiedit_needs_build:
        _log_step("Checking sd-cli (aiedit dependency)...")
        sd_cli_ok = _handle_aiedit_deps(dry_run=dry_run)
        if not sd_cli_ok:
            _log_warn("sd-cli not installed; aiedit will not function.")
        print()

    # Find GIMP plug-ins directory
    dest: Path | None = None
    if args.dest:
        dest = Path(args.dest).expanduser().resolve()
        if not dest.is_dir():
            _log_fail(f"Directory does not exist: {dest}")
            sys.exit(1)
    else:
        _log_step("Locating GIMP plug-ins directory...")
        dest = find_gimp_plugins_dir()

    if dest is None:
        _log_warn("Could not locate GIMP plug-ins directory automatically.")
        try:
            user_path = input("  Enter path to GIMP plug-ins directory: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            _log_fail("Aborted.")
            sys.exit(1)
        if not user_path:
            _log_fail("No path provided. Aborted.")
            sys.exit(1)
        dest = Path(user_path).expanduser().resolve()
        if not dest.is_dir():
            _log_fail(f"Directory does not exist: {dest}")
            sys.exit(1)

    _log_ok(f"Target: {dest}")
    print()

    if uninstall:
        _uninstall_plugins(plugins, dest)
        print()
        _log_step("Restart GIMP to unload the plugins.")
        return

    # Install plugins
    _log_step("Installing plugins...")
    for plugin in plugins:
        if symlink_plugin(plugin, dest, dry_run=dry_run):
            continue
        _log_warn(f"symlink failed for {plugin.name}, copying instead")
        copy_plugin(plugin, dest, dry_run=dry_run)

    # Summary
    print()
    print("  " + "=" * 36)
    print("  Summary")
    print("  " + "=" * 36)
    print(f"  Plugins installed to: {dest}")
    pip_ok = [name for name, ok in pip_results if ok]
    pip_fail = [name for name, ok in pip_results if not ok]
    if pip_ok:
        _log_ok(f"pip deps installed: {', '.join(pip_ok)}")
    if pip_fail:
        _log_fail(f"pip deps failed: {', '.join(pip_fail)}")
    if aiedit_needs_build:
        if sd_cli_ok:
            _log_ok("sd-cli: built and installed")
        else:
            _log_fail("sd-cli: not installed (see messages above)")
    print("  " + "=" * 36)
    _log_step("Restart GIMP to load the plugins.")


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        print("\n")
        _log_info("Installation cancelled by user.")
        sys.exit(130)
    except Exception as e:
        print()
        _log_fail(f"Unexpected error: {e}")
        _log_info("Please report this issue with the full error output above.")
        sys.exit(1)