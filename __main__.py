import sys
import os

PORT = int(os.getenv("PORT", 8080))

if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "server":
        from api.server import run_server
        run_server(host="0.0.0.0", port=PORT)
    else:
        from cli.main import main
        main()
