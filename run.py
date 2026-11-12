
from app import create_app
from app.database import ConfigurationError, DatabaseUnavailable


if __name__ == "__main__":
    try:
        app = create_app()
    except (ConfigurationError, DatabaseUnavailable) as error:
        raise SystemExit(
            f"{error}\nRevisa la VM, el túnel y ejecuta python configurar.py."
        ) from None
    app.run(debug=False)
else:
    app = create_app()
