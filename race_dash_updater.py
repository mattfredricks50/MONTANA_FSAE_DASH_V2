"""
Race Dash - Firmware & Software Updater

Handles update operations from the dashboard settings screen:

1. UPDATE PI SOFTWARE from GitHub:
   - Configures git remote from config (update.git_repo, update.git_branch)
   - Runs git pull in the project directory

2. BUILD FIRMWARE (optional):
   - If update.build_firmware is True and PlatformIO is installed,
     runs `pio run` to compile main.cpp → firmware.bin
   - If PlatformIO is not installed, uses pre-built firmware.bin from repo

3. FLASH STM32 over UART:
   - Pi controls STM32 BOOT0 and NRST pins via GPIO
   - Puts STM32 into ROM bootloader mode (BOOT0 HIGH + reset)
   - Runs stm32flash to write firmware.bin over /dev/ttyAMA0
   - Resets STM32 back into normal mode (BOOT0 LOW + reset)

WIRING (Pi GPIO → STM32):
  Pi GPIO17 (pin 11) → STM32 BOOT0
  Pi GPIO27 (pin 13) → STM32 NRST (active low, open-drain safe)

DEPENDENCIES:
  sudo apt install -y stm32flash git
  pip install platformio   (optional, for building firmware from source)
"""

import os
import subprocess
import threading
import time

from race_dash_config import config


# GPIO pin assignments (BCM numbering)
GPIO_BOOT0 = 17   # Pi GPIO17 → STM32 BOOT0 pin
GPIO_NRST  = 27   # Pi GPIO27 → STM32 NRST pin

# Paths
PROJECT_DIR  = os.path.dirname(os.path.abspath(__file__))
FIRMWARE_BIN = os.path.join(PROJECT_DIR, 'firmware.bin')
PIO_BUILD_BIN = os.path.join(PROJECT_DIR, '.pio', 'build', 'stm32_racedash', 'firmware.bin')
UART_PORT    = '/dev/ttyAMA0'


class Updater:
    """Manages STM32 flashing and Pi software updates.

    All operations run in background threads. Poll `status` and `busy`
    from the UI to show progress.
    """

    def __init__(self):
        self.status = "Ready"
        self.busy = False
        self._gpio_ok = False
        self._gpio = None
        self._init_gpio()

    def _init_gpio(self):
        """Set up GPIO pins for BOOT0 and NRST control."""
        try:
            import RPi.GPIO as GPIO
            self._gpio = GPIO
            try:
                GPIO.setmode(GPIO.BCM)
            except ValueError:
                pass  # Already set by main app
            GPIO.setup(GPIO_BOOT0, GPIO.OUT, initial=GPIO.LOW)
            GPIO.setup(GPIO_NRST, GPIO.OUT, initial=GPIO.HIGH)
            self._gpio_ok = True
        except (ImportError, RuntimeError):
            self._gpio_ok = False
            self.status = "No GPIO (PC mode)"

    def _reset_stm32(self):
        """Pulse NRST low to reset the STM32."""
        if not self._gpio_ok:
            return
        self._gpio.output(GPIO_NRST, self._gpio.LOW)
        time.sleep(0.1)
        self._gpio.output(GPIO_NRST, self._gpio.HIGH)
        time.sleep(0.2)

    def _enter_bootloader(self):
        """Put STM32 into UART bootloader mode (BOOT0 HIGH + reset)."""
        if not self._gpio_ok:
            return False
        self._gpio.output(GPIO_BOOT0, self._gpio.HIGH)
        time.sleep(0.05)
        self._reset_stm32()
        time.sleep(0.3)
        return True

    def _exit_bootloader(self):
        """Return STM32 to normal run mode (BOOT0 LOW + reset)."""
        if not self._gpio_ok:
            return
        self._gpio.output(GPIO_BOOT0, self._gpio.LOW)
        time.sleep(0.05)
        self._reset_stm32()

    # ── Git Remote Setup ──────────────────────────────────────────

    def _ensure_git_remote(self):
        """Set the git remote origin to match config."""
        repo_url = config.get('update', 'git_repo')
        branch = config.get('update', 'git_branch')
        if not repo_url:
            self.status = "ERROR: No git repo configured"
            return False

        # Check current remote
        result = subprocess.run(
            ['git', 'remote', 'get-url', 'origin'],
            cwd=PROJECT_DIR, capture_output=True, text=True
        )
        current_url = result.stdout.strip() if result.returncode == 0 else ''

        if current_url != repo_url:
            if current_url:
                # Update existing remote
                subprocess.run(
                    ['git', 'remote', 'set-url', 'origin', repo_url],
                    cwd=PROJECT_DIR, capture_output=True
                )
            else:
                # Add remote
                subprocess.run(
                    ['git', 'remote', 'add', 'origin', repo_url],
                    cwd=PROJECT_DIR, capture_output=True
                )

        # Make sure we're on the right branch
        result = subprocess.run(
            ['git', 'rev-parse', '--abbrev-ref', 'HEAD'],
            cwd=PROJECT_DIR, capture_output=True, text=True
        )
        current_branch = result.stdout.strip() if result.returncode == 0 else ''

        if current_branch != branch:
            result = subprocess.run(
                ['git', 'checkout', branch],
                cwd=PROJECT_DIR, capture_output=True, text=True
            )
            if result.returncode != 0:
                # Try fetching first then checkout
                subprocess.run(
                    ['git', 'fetch', 'origin', branch],
                    cwd=PROJECT_DIR, capture_output=True
                )
                result = subprocess.run(
                    ['git', 'checkout', branch],
                    cwd=PROJECT_DIR, capture_output=True, text=True
                )
                if result.returncode != 0:
                    self.status = f"ERROR: Can't switch to {branch}"
                    return False
        return True

    # ── Build Firmware ────────────────────────────────────────────

    def _build_firmware(self):
        """Build main.cpp into firmware.bin using PlatformIO.
        Returns path to firmware.bin or None on failure."""
        # Check if PlatformIO is installed
        pio_cmd = None
        for cmd in ['pio', 'platformio', os.path.expanduser('~/.platformio/penv/bin/pio')]:
            ret = subprocess.run(['which', cmd], capture_output=True)
            if ret.returncode == 0:
                pio_cmd = cmd
                break

        if not pio_cmd:
            # No PlatformIO — fall back to pre-built firmware.bin in repo
            if os.path.isfile(FIRMWARE_BIN):
                self.status = "No PlatformIO, using prebuilt .bin"
                return FIRMWARE_BIN
            self.status = "ERROR: No PlatformIO and no firmware.bin"
            return None

        self.status = "Building firmware..."
        result = subprocess.run(
            [pio_cmd, 'run'],
            cwd=PROJECT_DIR,
            capture_output=True, text=True, timeout=300
        )

        if result.returncode != 0:
            err = result.stderr.strip().split('\n')[-1] if result.stderr else "Build failed"
            if len(err) > 50:
                err = err[:50] + "..."
            self.status = f"Build FAILED: {err}"
            return None

        # PlatformIO outputs to .pio/build/<env>/firmware.bin
        if os.path.isfile(PIO_BUILD_BIN):
            return PIO_BUILD_BIN

        # Check if it went to a different env name
        pio_build_dir = os.path.join(PROJECT_DIR, '.pio', 'build')
        if os.path.isdir(pio_build_dir):
            for env_dir in os.listdir(pio_build_dir):
                candidate = os.path.join(pio_build_dir, env_dir, 'firmware.bin')
                if os.path.isfile(candidate):
                    return candidate

        self.status = "ERROR: Build succeeded but firmware.bin not found"
        return None

    # ── STM32 Flash ───────────────────────────────────────────────

    def flash_stm32(self, uart_thread=None):
        """Build (if enabled) and flash firmware to STM32. Runs in background thread."""
        if self.busy:
            return
        self.busy = True
        t = threading.Thread(target=self._do_flash, args=(uart_thread,), daemon=True)
        t.start()

    def _do_flash(self, uart_thread=None):
        try:
            # Check stm32flash is installed
            ret = subprocess.run(['which', 'stm32flash'], capture_output=True)
            if ret.returncode != 0:
                self.status = "ERROR: stm32flash not installed"
                self.busy = False
                return

            if not self._gpio_ok:
                self.status = "ERROR: No GPIO control"
                self.busy = False
                return

            # Build or locate firmware
            build_enabled = config.get('update', 'build_firmware')
            if build_enabled:
                fw_path = self._build_firmware()
            else:
                fw_path = FIRMWARE_BIN if os.path.isfile(FIRMWARE_BIN) else None

            if not fw_path:
                if not build_enabled:
                    self.status = "ERROR: firmware.bin not found"
                self.busy = False
                return

            # Stop UART reading thread so we can use the port
            if uart_thread:
                self.status = "Stopping UART thread..."
                uart_thread.stop()
                uart_thread.join(timeout=2.0)
                time.sleep(0.5)

            # Enter bootloader mode
            self.status = "Entering bootloader..."
            if not self._enter_bootloader():
                self.status = "ERROR: Failed to enter bootloader"
                self.busy = False
                return

            # Flash
            self.status = "Flashing STM32..."
            result = subprocess.run(
                ['stm32flash', '-w', fw_path, '-v', '-g', '0x0', UART_PORT],
                capture_output=True, text=True, timeout=120
            )

            if result.returncode == 0:
                self.status = "Flash OK! Resetting..."
            else:
                err = result.stderr.strip() or result.stdout.strip()
                if len(err) > 60:
                    err = err[:60] + "..."
                self.status = f"Flash FAILED: {err}"
                self._exit_bootloader()
                self.busy = False
                return

            # Exit bootloader and reset into normal firmware
            self._exit_bootloader()
            time.sleep(1.0)
            self.status = "STM32 flashed and running!"

        except subprocess.TimeoutExpired:
            self.status = "ERROR: Flash timed out"
            self._exit_bootloader()
        except Exception as e:
            self.status = f"ERROR: {e}"
            try:
                self._exit_bootloader()
            except Exception:
                pass
        finally:
            self.busy = False

    # ── Reset STM32 ───────────────────────────────────────────────

    def reset_stm32_action(self):
        """Reset the STM32 (no flash, just power cycle it)."""
        if self.busy:
            return
        if not self._gpio_ok:
            self.status = "No GPIO (PC mode)"
            return
        self.busy = True
        self.status = "Resetting STM32..."
        self._reset_stm32()
        time.sleep(0.5)
        self.status = "STM32 reset complete"
        self.busy = False

    # ── Pi Software Update ────────────────────────────────────────

    def update_pi_software(self):
        """Git pull latest code from GitHub. Runs in background thread."""
        if self.busy:
            return
        self.busy = True
        t = threading.Thread(target=self._do_git_pull, daemon=True)
        t.start()

    def _do_git_pull(self):
        try:
            ret = subprocess.run(['which', 'git'], capture_output=True)
            if ret.returncode != 0:
                self.status = "ERROR: git not installed"
                self.busy = False
                return

            # Ensure remote and branch match config
            self.status = "Configuring git remote..."
            if not self._ensure_git_remote():
                self.busy = False
                return

            branch = config.get('update', 'git_branch') or 'main'
            self.status = f"Pulling {branch}..."
            result = subprocess.run(
                ['git', 'pull', 'origin', branch, '--ff-only'],
                cwd=PROJECT_DIR,
                capture_output=True, text=True, timeout=60
            )

            if result.returncode == 0:
                output = result.stdout.strip()
                if 'Already up to date' in output:
                    self.status = "Already up to date"
                else:
                    lines = output.split('\n')
                    summary = lines[-1] if lines else "Updated"
                    if len(summary) > 50:
                        summary = summary[:50] + "..."
                    self.status = f"Updated! {summary}"
            else:
                err = result.stderr.strip()
                if len(err) > 60:
                    err = err[:60] + "..."
                self.status = f"Pull FAILED: {err}"

        except subprocess.TimeoutExpired:
            self.status = "ERROR: Git pull timed out"
        except Exception as e:
            self.status = f"ERROR: {e}"
        finally:
            self.busy = False

    # ── Restart App ───────────────────────────────────────────────

    def restart_app(self):
        """Restart this Python process (picks up new code after git pull)."""
        self.status = "Restarting..."
        import sys
        os.execv(sys.executable, [sys.executable] + sys.argv)

    # ── Cleanup ───────────────────────────────────────────────────

    def cleanup(self):
        """Release GPIO pins (call on app shutdown)."""
        if self._gpio_ok and self._gpio:
            try:
                self._gpio.output(GPIO_BOOT0, self._gpio.LOW)
                self._gpio.output(GPIO_NRST, self._gpio.HIGH)
            except Exception:
                pass
