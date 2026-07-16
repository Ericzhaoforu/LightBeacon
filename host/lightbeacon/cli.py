from __future__ import annotations

import argparse
import getpass
import secrets

import uvicorn

from .app import create_app
from .auth import hash_password
from .config import Settings


def host_main() -> None:
    settings = Settings.from_env()
    uvicorn.run(create_app(settings), host=settings.bind_host, port=settings.http_port)


def main() -> None:
    parser = argparse.ArgumentParser(prog="lightbeacon")
    subparsers = parser.add_subparsers(dest="command", required=True)
    subparsers.add_parser("host", help="start the LightBeacon host service")
    subparsers.add_parser("hash-password", help="generate a scrypt administrator password hash")
    subparsers.add_parser("generate-secrets", help="generate HMAC and session secrets")
    args = parser.parse_args()
    if args.command == "host":
        host_main()
    elif args.command == "hash-password":
        password = getpass.getpass("Administrator password: ")
        confirmation = getpass.getpass("Confirm password: ")
        if password != confirmation:
            raise SystemExit("Passwords do not match")
        print(hash_password(password))
    elif args.command == "generate-secrets":
        print(f"LIGHTBEACON_HMAC_KEY={secrets.token_hex(32)}")
        print(f"LIGHTBEACON_SESSION_SECRET={secrets.token_hex(32)}")


if __name__ == "__main__":
    main()

