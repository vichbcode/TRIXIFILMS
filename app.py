"""
TRIXIFILMS — Application Flask de catalogue de films
Point d'entrée principal
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()

from app import create_app

app = create_app()

if __name__ == "__main__":
    is_prod = os.environ.get("FLASK_ENV", "") == "production"
    run_debug = not is_prod and (os.environ.get("FLASK_DEBUG", "0") == "1")
    app.run(debug=run_debug, host="0.0.0.0", port=int(os.environ.get("PORT", 5000)))
