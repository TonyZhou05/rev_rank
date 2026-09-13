"""Run the local React/FastAPI stack and clean up both children on exit."""
from __future__ import annotations

import argparse
import importlib.util
import os
from pathlib import Path
import shutil
import signal
import subprocess
import sys
import time

ROOT = Path(__file__).resolve().parents[1]


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--api-port', type=int, default=8000)
    parser.add_argument('--web-port', type=int, default=5173)
    parser.add_argument('--built', action='store_true', help='Serve frontend/dist from FastAPI only')
    args = parser.parse_args()
    if not all(1 <= p <= 65535 for p in (args.api_port, args.web_port)):
        parser.error('Ports must be between 1 and 65535.')
    if importlib.util.find_spec('uvicorn') is None:
        parser.error('Install dependencies first: .venv/bin/python -m pip install -r requirements.txt')
    if args.built and not (ROOT / 'frontend/dist/index.html').exists():
        parser.error('Build the frontend first: npm --prefix frontend run build')
    if not args.built and not (ROOT / 'frontend/node_modules').exists():
        parser.error('Install frontend dependencies first: npm --prefix frontend ci')
    npm = shutil.which('npm')
    if not args.built and not npm:
        parser.error('npm is not on PATH.')
    children: list[subprocess.Popen] = []

    def stop(_signum=None, _frame=None):
        raise KeyboardInterrupt

    signal.signal(signal.SIGTERM, stop)
    env = dict(os.environ, REVRANK_API_URL=f'http://127.0.0.1:{args.api_port}')
    try:
        api = [sys.executable, '-m', 'uvicorn', 'backend.app.main:app',
               '--host', '127.0.0.1', '--port', str(args.api_port)]
        if not args.built:
            # Vite hot-reloads the page; reload the API too so the two never drift apart.
            api += ['--reload', '--reload-dir', str(ROOT / 'backend')]
        children.append(subprocess.Popen(api, cwd=ROOT, env=env, start_new_session=True))
        if not args.built:
            web = [npm, 'run', 'dev', '--', '--host', '127.0.0.1',
                   '--port', str(args.web_port), '--strictPort']
            children.append(subprocess.Popen(web, cwd=ROOT / 'frontend', env=env, start_new_session=True))
        print(f'RevRank: http://127.0.0.1:{args.api_port if args.built else args.web_port}', flush=True)
        print('Press Ctrl+C to stop all RevRank processes.', flush=True)
        while all(child.poll() is None for child in children):
            time.sleep(0.25)
        return next((child.returncode for child in children if child.returncode), 0)
    except KeyboardInterrupt:
        return 0
    finally:
        for child in children:
            if child.poll() is None:
                try:
                    os.killpg(child.pid, signal.SIGTERM)
                except ProcessLookupError:
                    pass
        for child in children:
            try:
                child.wait(timeout=5)
            except subprocess.TimeoutExpired:
                try:
                    os.killpg(child.pid, signal.SIGKILL)
                except ProcessLookupError:
                    pass
                child.wait()


if __name__ == '__main__':
    raise SystemExit(main())
