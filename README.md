# LightBeacon

LightBeacon is a private-LAN control system for 10–50 ESP32-WROOM-32UE light
nodes. Each node drives a 288-pixel side strip and a 64-pixel top matrix as one
synchronized logical beacon.

The repository contains:

- `host/`: FastAPI, SQLite, UDP controller, authentication, OTA coordination,
  protocol tools, and the multi-node simulator.
- `web/`: React/TypeScript operator console.
- `firmware/`: ESP-IDF firmware for ESP32-WROOM-32UE.
- `protocol/`: versioned wire protocol and cross-language golden vectors.
- `docs/`: development, wiring, deployment, and OTA instructions.

## Quick start without hardware

1. Copy `.env.example` to `.env`, replace all `CHANGE_ME` values, and generate
   the password hash with `python -m lightbeacon.cli hash-password` after the
   package is installed.
2. Create a Python 3.12 virtual environment and run `pip install -e ".[dev]"`.
3. In `web/`, run `npm install` followed by `npm run build`.
4. Start the host with `python -m lightbeacon.cli host`.
5. In another terminal, start simulated nodes with
   `python -m lightbeacon.simulator --count 10`.
6. Open `http://127.0.0.1:8080`.

See [Development](docs/DEVELOPMENT.md), [Hardware](docs/HARDWARE.md),
[Deployment](docs/DEPLOYMENT.md), [Chinese operator guide](docs/OPERATOR_GUIDE_ZH.md),
and [Protocol](protocol/SPEC.md) for details.

## Safety

Do not power 352 WS2812B pixels from a development board or computer USB port.
Use an independently protected 5 V supply, common ground, proper power
injection, and 5 V AHCT data-level conversion. The firmware brightness limit is
not a substitute for correct electrical design.
