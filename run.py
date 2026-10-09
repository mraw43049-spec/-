"""Railway launcher: serve the Mini App/API and run the Telegram bot in one service."""
import os
import threading
import uvicorn


def serve_api():
    from main import app
    port = int(os.environ.get("PORT", "8080"))
    uvicorn.run(app, host="0.0.0.0", port=port, log_level="info")


if __name__ == "__main__":
    api_thread = threading.Thread(target=serve_api, name="miniapp-api", daemon=True)
    api_thread.start()
    # Import only after starting the API thread; bot.py keeps its existing handlers and DB.
    import bot
    bot.main()
