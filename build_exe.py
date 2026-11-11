"""Собирает автономный Windows EXE в папку dist."""
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parent

if __name__ == '__main__':
    subprocess.run([
        sys.executable, '-m', 'PyInstaller', '--noconfirm', '--onefile',
        '--windowed', '--name', 'EquipmentInventory',
        '--distpath', str(ROOT / 'dist'), '--workpath', str(ROOT / 'build'),
        '--specpath', str(ROOT / 'build'),
        *[arg for name in ('schema.sql', 'demo.sql', 'queries.sql')
          for arg in ('--add-data', f'{ROOT / name}:.')],
        str(ROOT / 'gui.py'),
    ], cwd=ROOT, check=True)
