# Private-LAN deployment

## Access point

Use a dedicated 2.4 GHz AP or private router:

- Internet access is not required.
- Enable DHCP.
- Disable AP/client isolation.
- Keep the host and all nodes on one layer-2 subnet.
- Connect the host to the AP by Ethernet where possible.
- Use WPA2 or WPA3 and a non-public credential.
- For multiple wired APs, plan non-overlapping 2.4 GHz channels and keep
  client isolation disabled.

The nodes use DHCP and broadcast STATUS on UDP 40404, so static addresses are
not required. Permit UDP 40404 and host TCP 8080 in the host firewall.

## Host

1. Set LIGHTBEACON_PUBLIC_BASE_URL to the host's wired LAN address, such as
   http://192.168.50.2:8080.
2. Start the FastAPI service.
3. Open port 8080 only on the private LightBeacon network profile.
4. Open the control console and log in.
5. Confirm the host health, session and UDP port before commissioning nodes.

SQLite state, firmware uploads and rotating logs live under the configured data
and log directories. Back up the SQLite file to preserve layouts; active
effects intentionally do not resume after a host restart.

## Node commissioning

1. Attach the external antenna and power only the ESP32 development board.
2. Connect a phone or computer to LightBeacon-XXXXXX.
3. Open http://192.168.4.1.
4. Configure a unique node ID, AP credentials, the shared HMAC key, pixel counts
   and brightness cap.
5. Wait for the node to reboot and appear in the host node list.
6. Bind the node ID to a grid cell.
7. Test OFF and low-brightness blue before connecting the full LED supply.

If an ID conflict is detected, non-OFF commands to that ID are blocked. Hold
BOOT for five seconds while the firmware is running to erase its LightBeacon
configuration.

## Field acceptance

Run at least 1000 commands near the intended 100 m line-of-sight boundary.
Target at least 99% command completion and approximately -75 dBm RSSI or better.
If the target is missed, adjust antenna/AP placement or add wired-backhaul APs;
do not weaken protocol authentication.

