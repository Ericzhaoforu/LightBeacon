# Hardware and wiring

## Node signals

| Function | ESP32 pin | Driver |
|---|---:|---|
| 288-pixel side strip | GPIO18 | SPI2 with DMA |
| 64-pixel top matrix | GPIO19 | RMT |
| Factory reset while running | GPIO0 / BOOT | Hold low for 5 seconds |

Pins and pixel counts can be changed in idf.py menuconfig. Both outputs use
WS2812B GRB ordering and always display the same logical effect in version 1.

Each data path is:

    ESP32 GPIO -> 5 V 74AHCT125 -> approximately 330 ohm series resistor -> DIN

Place the level converter near the ESP32 and the series resistor near the first
pixel. The ESP32, level converter, matrix, strip and 5 V supply must share
ground.

## Power safety

352 WS2812B pixels can theoretically approach 21.1 A at 5 V under a full-white
60 mA/pixel fault condition. Size the supply, connectors, fuses, wiring and
injection points for the actual electrical design rather than relying on the
firmware's 25% default brightness cap.

- Never power the complete LED load from USB or the ESP32 regulator.
- Prevent the external 5 V rail from feeding back into the computer USB port.
- Add bulk capacitance at the node input and local decoupling at the level
  converter.
- Inject power along the two-metre 144 LED/m strip to control voltage drop.
- Fuse each branch appropriately.
- Verify polarity and ground continuity before connecting ESP32 data.

## Radio

ESP32-WROOM-32UE requires a compatible 2.4 GHz antenna on its U.FL/IPEX
connector. Mount the antenna away from metal surfaces, LED power wiring,
DC/DC converters and large current loops. Do not assume a sealed metal enclosure
will provide acceptable 100 m coverage.

