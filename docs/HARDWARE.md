# Hardware and wiring

This document describes the verified LightBeacon node wiring using an
ESP32-WROOM-32UE and an
[Adafruit Pixel Shifter, product 6066](https://learn.adafruit.com/adafruit-pixel-shifter/pinouts).
Disconnect the battery, USB cable and all external power before changing any
wiring.

For the complete Chinese field procedure, see
[OPERATOR_GUIDE_ZH.md](OPERATOR_GUIDE_ZH.md).

## Node signals

| Function | ESP32 pin | Firmware driver |
|---|---:|---|
| 288-pixel side strip | GPIO18 | SPI2 with DMA |
| 64-pixel top matrix / second strip | GPIO19 | RMT |
| Factory reset while running | GPIO0 / BOOT | Hold low for 5 seconds |

Pins and pixel counts can be changed in `idf.py menuconfig`. Both LED outputs
use WS2812B `GRB` ordering and display the same logical effect in version 1.

## Power topology

The current node uses a 12 V LiFePO4 battery followed by a DC-DC converter set
to 5.0 V. The 12 V battery must never be connected directly to the ESP32, Pixel
Shifter or LEDs.

```text
12 V LiFePO4 battery
  positive -> main fuse -> main switch -> DC-DC IN+
  negative -----------------------------> DC-DC IN-

DC-DC OUT+ (5.0 V)
  +-> protected branch -> ESP32 5V/VIN
  +-> protected branch -> side-strip +5V injection points
  +-> protected branch -> top matrix / second-strip +5V

DC-DC OUT- (common GND)
  +-> ESP32 GND
  +-> 6066 G
  +-> side-strip GND injection points
  +-> top matrix / second-strip GND
```

The LED 5 V supply goes directly from the protected DC-DC branches to the LED
power inputs. LED current must not pass through the ESP32 or the 6066 module.

## Exact Adafruit 6066 wiring

The 6066 provides two independent non-inverting level-shifter channels. In this
project, the terminal labelled `CLK/C5` is repurposed as the second WS2812B data
channel; it is **not** a clock signal. Both LED outputs remain one-wire WS2812B
data streams.

```text
ESP32                         Adafruit 6066              WS2812B LEDs

3V3  ----------------------> V
GND  ----------------------> G -----------------------> common GND

GPIO18 --------------------> DAT
                              D5 ---- 330 ohm --------> side strip DIN

GPIO19 --------------------> CLK
                              C5 ---- 330 ohm --------> top matrix DIN

                              !D5 --------------------> leave unconnected
```

| From | To | Requirement |
|---|---|---|
| ESP32 `3V3` | 6066 `V` | Power the 6066 from the ESP32 logic voltage |
| ESP32 `GND` | 6066 `G` | Must also connect to DC-DC `OUT-` and both LED grounds |
| ESP32 `GPIO18` | 6066 `DAT` | Side-strip data input to the first shifter channel |
| 6066 `D5` | 330 ohm resistor, then side-strip `DIN` | Non-inverted 5 V logic output |
| ESP32 `GPIO19` | 6066 `CLK` | Second LED data input; not a clock in LightBeacon |
| 6066 `C5` | 330 ohm resistor, then top-matrix `DIN` | Second non-inverted 5 V logic output |
| 6066 `!D5` | No connection | Inverted output; do not use for these WS2812B LEDs |
| DC-DC `OUT+` | Both LED `+5V` inputs | Use protected branches and side-strip injection points |
| DC-DC `OUT-` | Both LED grounds | Common signal and power reference |

Each output needs its own approximately 330 ohm series resistor. The resistors
are non-polarized and should be placed close to the first LED's `DIN`. Connect
data to `DIN`, never `DOUT`; the arrows on a strip must point away from the
controller toward the end of the strip.

The 6066 `V` pin accepts the microcontroller-side supply and should be connected
to ESP32 `3V3` in this build. The module generates the shifted 5 V output logic
internally. Do not connect 12 V to any 6066 terminal.

## Grounding and signal integrity

- ESP32 GND, 6066 `G`, DC-DC `OUT-`, side-strip GND and top-matrix GND must all
  be connected.
- Keep the 6066 close to the ESP32 and keep the paths from `D5/C5` to the first
  LEDs short.
- Route a reliable ground reference alongside each data connection.
- Do not connect or disconnect LED data wiring while the node is powered.
- Add approximately 470-1000 uF of bulk capacitance across `+5V` and `GND` near
  each LED power input. Observe electrolytic capacitor polarity.
- Inject both `+5V` and `GND` together at multiple points along the two-metre,
  144 LED/m side strip.

## Power safety

352 WS2812B pixels can theoretically approach 21.1 A at 5 V under a full-white
60 mA/pixel fault condition. Size the DC-DC converter, connectors, fuses,
wiring and injection points for the actual electrical design rather than
relying on the firmware's 25% default brightness cap.

- Put a main fuse close to the battery positive terminal and protect each 5 V
  output branch appropriately.
- Set and verify the DC-DC output at 5.0 V with a multimeter before connecting
  the ESP32 or LEDs.
- Never power the complete LED load from USB or the ESP32 regulator.
- Prevent the external 5 V rail from feeding back into the computer USB port.
- Verify power polarity, absence of shorts and ground continuity before
  connecting ESP32 data.

## Pre-power checklist

- [ ] No 12 V wire is connected to the ESP32, 6066 or LEDs.
- [ ] DC-DC output is 5.0 V with the correct polarity.
- [ ] ESP32, 6066 and both LED outputs share common ground.
- [ ] ESP32 `3V3 -> 6066 V` and `GND -> G` are correct.
- [ ] `GPIO18 -> DAT -> D5 -> 330 ohm -> side DIN` is correct.
- [ ] `GPIO19 -> CLK -> C5 -> 330 ohm -> top DIN` is correct.
- [ ] `!D5` is unconnected.
- [ ] Both LED power inputs and all injection points have correct polarity.
- [ ] The external ESP32 antenna is connected before radio testing.

For the first powered LED test, select only one node and request 5% brightness.

## Radio

ESP32-WROOM-32UE requires a compatible 2.4 GHz antenna on its U.FL/IPEX
connector. Mount the antenna away from metal surfaces, LED power wiring, DC-DC
converters and large current loops. Do not assume a sealed metal enclosure will
provide acceptable 100 m coverage.
