#!/usr/bin/env python3
"""Find which SDL video drivers work on this Pi."""

import os

drivers = ['fbcon', 'kmsdrm', 'directfb', 'x11', 'wayland', 'eglfs', 'linuxfb', 'dummy']

for d in drivers:
    os.environ['SDL_VIDEODRIVER'] = d
    try:
        import importlib
        import pygame
        importlib.reload(pygame)
        pygame.display.quit()
        pygame.display.init()
        print(f'{d}: WORKS')
        pygame.display.quit()
    except Exception as e:
        print(f'{d}: no  ({e})')

# Also check what SDL2 reports
os.environ.pop('SDL_VIDEODRIVER', None)
try:
    import pygame
    pygame.display.quit()
    pygame.display.init()
    print(f'\nDefault driver: {pygame.display.get_driver()}')
    pygame.display.quit()
except Exception as e:
    print(f'\nDefault driver failed: {e}')

# Check if /dev/fb0 exists
import pathlib
fb = pathlib.Path('/dev/fb0')
print(f'\n/dev/fb0 exists: {fb.exists()}')
if fb.exists():
    import stat
    s = fb.stat()
    print(f'/dev/fb0 permissions: {oct(s.st_mode)}')

# Check groups
import subprocess
result = subprocess.run(['groups'], capture_output=True, text=True)
print(f'\nUser groups: {result.stdout.strip()}')

# Check if DRM devices exist
drm = pathlib.Path('/dev/dri')
if drm.exists():
    print(f'\nDRM devices: {list(drm.iterdir())}')
else:
    print('\n/dev/dri does not exist')