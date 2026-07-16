# Signed OTA

The firmware uses two OTA app partitions, rollback support, SHA-256 verification
and ESP-IDF application signature verification. The host dispatches at most
five nodes at a time and provides a one-time HTTP token inside an authenticated
OTA_BEGIN packet.

## Signing mode

Release devices must be ESP32 revision 3.0 or later to use the RSA Secure Boot
v2 application-signing scheme planned for ESP32-WROOM-32UE.

In idf.py menuconfig:

1. Set the minimum ESP32 revision to 3.0 after confirming the real module.
2. Under Security features, select RSA app signing.
3. Enable CONFIG_SECURE_SIGNED_APPS_NO_SECURE_BOOT.
4. Keep CONFIG_SECURE_SIGNED_ON_UPDATE_NO_SECURE_BOOT enabled.
5. Enable signing binaries during build and select a private RSA-3072 key
   outside the repository.
6. Keep bootloader application rollback enabled.

Generate and protect the key using the official IDF workflow:

    idf.py secure-generate-signing-key path\outside\repo\ota_signing_key.pem

All initial USB-flashed apps and all OTA apps must be signed with the same key.
Do not commit, copy into firmware, or transmit the private key to nodes. The
software-only mode protects against remote replacement but not an attacker who
can rewrite device flash; production devices should evaluate full Secure Boot
and flash encryption separately.

## Release

1. Set the project version.
2. Build a signed application image.
3. Verify the signature with idf.py secure-verify-signature.
4. Upload the resulting application .bin from the OTA page.
5. Select no more than the intended target set and confirm every node's
   firmware version after reboot.

The node validates HTTP status/size, SHA-256, ESP image format, embedded version
and signature before selecting the new boot partition. A pending image is only
marked valid after LED initialization, NVS loading and Wi-Fi reconnection.
Failure, watchdog reset or power loss before confirmation triggers rollback.

Official reference:

- https://docs.espressif.com/projects/esp-idf/en/stable/esp32/security/secure-boot-v2.html

