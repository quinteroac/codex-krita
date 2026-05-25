from __future__ import annotations

import argparse

from .server import make_server


def main() -> None:
    parser = argparse.ArgumentParser(description="Run the Krita Codex local service.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", default=8765, type=int)
    parser.add_argument("--vision-model", default="gpt-5.5")
    parser.add_argument("--codex-model", default="gpt-5.4")
    args = parser.parse_args()

    server = make_server(args.host, args.port, args.vision_model, args.codex_model)
    print(f"krita-codex-service listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nkrita-codex-service stopped")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
