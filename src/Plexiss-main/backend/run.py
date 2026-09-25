"""Entry point for the Plexis backend."""
from app import create_app
from config import Config

app = create_app()

if __name__ == '__main__':
    print(f"=====================================")
    print(f" Starting Plexis Backend on port {Config.FLASK_PORT} ")
    print(f"=====================================")
    app.run(
        host='0.0.0.0',
        port=Config.FLASK_PORT,
        debug=Config.FLASK_DEBUG
    )
