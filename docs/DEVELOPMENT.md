# Development setup

## Host and web console

Windows PowerShell:

    python -m venv .venv
    .\.venv\Scripts\python -m pip install --upgrade pip
    .\.venv\Scripts\python -m pip install -e ".[dev]"
    cd web
    npm install
    npm run build
    cd ..
    python -m lightbeacon.cli generate-secrets
    python -m lightbeacon.cli hash-password

Copy .env.example to .env, replace all placeholders, paste the generated
secrets and password hash, and set LIGHTBEACON_PUBLIC_BASE_URL to the host
address reachable from the ESP32 network. Start the service with
scripts\run-host.ps1.

Linux uses the same repository and configuration:

    python3.12 -m venv .venv
    .venv/bin/pip install -e ".[dev]"
    (cd web && npm install && npm run build)
    scripts/run-host.sh

For front-end development, run npm run dev in web. Vite proxies HTTP and
WebSocket API requests to the FastAPI service on port 8080.

## ESP-IDF

Install ESP-IDF 6.0.2 through Espressif Installation Manager (EIM) or the
official ESP-IDF VS Code extension. Keep the ESP-IDF Python environment
separate from the host .venv. The verified Windows installation uses
`C:\Espressif\v6.0.2\esp-idf` and EIM's isolated Python environment.

Open an ESP-IDF terminal and run:

    cd firmware
    idf.py set-target esp32
    idf.py build
    idf.py -p COM_PORT flash monitor

From a normal Windows terminal, the repository wrapper activates the selected
EIM setup automatically:

    cd firmware
    powershell -ExecutionPolicy Bypass -File ..\scripts\idf.ps1 build
    powershell -ExecutionPolicy Bypass -File ..\scripts\idf.ps1 -p COM6 flash

The component manager downloads espressif/led_strip 3.0.3 during the first
build. Machine-specific IDF paths and COM ports belong in VS Code user settings,
not this repository.

### Brownout during first Wi-Fi start

If the serial log reaches `phy_init` and then prints `Brownout detector was
triggered`, the USB/3.3 V rail is dipping during RF calibration. Do not disable
the brownout detector. Disconnect LED power, use a short data-capable USB cable
and a motherboard USB port or a stable regulated development-board supply, then
reset and retry. The computer USB port must never power the WS2812B load.

## Checks

    .venv\Scripts\python -m pytest
    cd web
    npm run build

The Python integration test starts a real UDP controller and a virtual node.
Protocol golden vectors in protocol/golden_vectors.json must remain identical
between Python and the firmware C implementation.

Official references:

- https://docs.espressif.com/projects/esp-idf/en/stable/esp32/get-started/
- https://docs.espressif.com/projects/vscode-esp-idf-extension/en/latest/
- https://components.espressif.com/components/espressif/led_strip/versions/3.0.3
