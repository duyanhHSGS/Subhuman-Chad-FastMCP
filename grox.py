"""Forward the configured local port using ngrok."""

import time
from pathlib import Path

import ngrok
import yaml

config = yaml.safe_load(
    Path(__file__).with_name("config.yaml").read_text(encoding="utf-8")
)
tunnel = ngrok.forward(
    f"127.0.0.1:{config['port']}",
    authtoken=config["ngrok_authtoken"],
    domain=config["ngrok_domain"],
)
print(tunnel.url(), flush=True)
try:
    while True:
        time.sleep(3600)
except KeyboardInterrupt:
    pass
finally:
    ngrok.disconnect(tunnel.url())
