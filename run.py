"""Start the gallery with Flask's built-in server (fine for a trusted local network)."""
import argparse

from app import create_app


def main():
    parser = argparse.ArgumentParser(description="Run the gallery site")
    parser.add_argument("--host", default="127.0.0.1",
                        help="Use 0.0.0.0 to let other devices on your network connect")
    parser.add_argument("--port", type=int, default=8000)
    args = parser.parse_args()
    app = create_app()
    app.run(host=args.host, port=args.port, debug=False)


if __name__ == "__main__":
    main()
