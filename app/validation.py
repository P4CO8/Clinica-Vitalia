import re
import unicodedata
from datetime import date, datetime
from zoneinfo import ZoneInfo

DOCUMENT_TYPES = ("CC", "TI", "CE", "PAS")
DOCUMENT_PATTERN = re.compile(r"[A-Za-z0-9]{3,20}")
NUMERIC_DOCUMENT_PATTERN = re.compile(r"[0-9]{3,20}")
PHONE_PATTERN = re.compile(r"[0-9]{7,15}")
ISO_DATE_PATTERN = re.compile(r"[0-9]{4}-[0-9]{2}-[0-9]{2}")
BLOOD_TYPES = {"A+", "A-", "B+", "B-", "AB+", "AB-", "O+", "O-", ""}
COLOMBIA_TIMEZONE = ZoneInfo("America/Bogota")


def local_today():
    return datetime.now(COLOMBIA_TIMEZONE).date()


def normalize_name(value):
    return unicodedata.normalize("NFC", value.strip())


def valid_name(value):
    # Los separadores unen grupos de letras y nunca sustituyen un nombre.
    return all(part.isalpha() for part in re.split(r"[ '’\-]", value))


def patient_age(birth_date):
    today = local_today()
    age = today.year - birth_date.year
    if (today.month, today.day) < (birth_date.month, birth_date.day):
        age -= 1
    return age


def validate_patient_form(first_names, last_names, document_type, document_number,
                          birth_date="", phone="", blood_type=""):
    errors = {}
    for field_name, value in (("first_names", first_names), ("last_names", last_names)):
        if not value:
            errors[field_name] = "Este campo es obligatorio."
        elif len(value) > 100:
            errors[field_name] = "Usa máximo 100 caracteres."
        elif not valid_name(value):
            errors[field_name] = "Escribe el nombre con letras."

    if document_type not in DOCUMENT_TYPES:
        errors["document_type"] = "Selecciona un tipo de documento."
    if not document_number:
        errors["document_number"] = "Verifica que el documento esté completo."
    elif len(document_number) > 20:
        errors["document_number"] = "El documento es demasiado largo."
    elif len(document_number) < 3:
        errors["document_number"] = "El documento debe tener mínimo 3 caracteres."
    elif document_type == "PAS":
        if not DOCUMENT_PATTERN.fullmatch(document_number):
            errors["document_number"] = "El pasaporte debe tener entre 3 y 20 letras o números."
    elif not NUMERIC_DOCUMENT_PATTERN.fullmatch(document_number):
        errors["document_number"] = "El documento debe contener solo números."

    if not birth_date:
        errors["birth_date"] = "Escribe la fecha de nacimiento."
    else:
        try:
            if not ISO_DATE_PATTERN.fullmatch(birth_date):
                raise ValueError
            parsed_birth_date = date.fromisoformat(birth_date)
            if parsed_birth_date > local_today() or patient_age(parsed_birth_date) > 120:
                raise ValueError
        except ValueError:
            errors["birth_date"] = "Esta fecha es incorrecta."

    if phone and not PHONE_PATTERN.fullmatch(phone):
        errors["phone"] = "El teléfono debe contener entre 7 y 15 números."
    if blood_type not in BLOOD_TYPES:
        errors["blood_type"] = "Selecciona un grupo sanguíneo válido."
    return errors
