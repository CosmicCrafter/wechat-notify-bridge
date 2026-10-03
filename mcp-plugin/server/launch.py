"""Portable MCP entrypoint; start the configured local Python environment."""
import os
import json
from pathlib import Path
import subprocess
import sys

if __name__=='__main__':
    interpreter=os.environ.get('WECHAT_NOTIFY_PYTHON')
    if not interpreter:
        config=Path(os.environ.get('WECHAT_NOTIFY_CREDENTIAL_FILE') or Path.home()/'.config/wechat-notify-bridge/client.json').expanduser()
        if config.suffix=='.json' and config.is_file():
            try:
                interpreter=json.loads(config.read_text(encoding='utf-8')).get('python')
            except Exception:
                print('Invalid local client configuration',file=sys.stderr)
                raise SystemExit(1)
    interpreter=interpreter or sys.executable
    raise SystemExit(subprocess.call([interpreter,str(Path(__file__).with_name('http_bridge.py'))]))
