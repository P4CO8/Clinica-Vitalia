from dataclasses import dataclass, field
from uuid import uuid4


@dataclass(frozen=True)
class Patient:
    first_names: str = ""
    last_names: str = ""
    document_type: str = ""
    document_number: str = ""
    birth_date: str = ""
    phone: str = ""
    blood_type: str = ""
    internal_id: str = field(default_factory=lambda: f"PAC-{uuid4().hex[:8].upper()}")
    active: bool = True

    @property
    def name(self):
        return " ".join(part for part in (self.first_names, self.last_names) if part).strip()

    @property
    def document(self):
        return self.document_number


class DuplicateDocumentError(ValueError):
    pass


class PatientValidationError(ValueError):
    def __init__(self, errors):
        super().__init__("Verifica los datos del paciente.")
        self.errors = errors


class DuplicateNameError(ValueError):
    pass


class InMemoryPatientRepository:
    def __init__(self):
        self._patients = []

    def list_all(self):
        return list(self._patients)

    def set_active(self, internal_id, active):
        for index, patient in enumerate(self._patients):
            if patient.internal_id == internal_id:
                updated = Patient(
                    first_names=patient.first_names, last_names=patient.last_names,
                    document_type=patient.document_type, document_number=patient.document_number,
                    birth_date=patient.birth_date, phone=patient.phone, blood_type=patient.blood_type,
                    internal_id=patient.internal_id, active=active,
                )
                self._patients[index] = updated
                return updated
        return None

    def update(self, internal_id, **values):
        for index, patient in enumerate(self._patients):
            if patient.internal_id == internal_id:
                updated = Patient(**values, internal_id=internal_id, active=patient.active)
                self._patients[index] = updated
                return updated
        return None

    def add(
        self,
        first_names="",
        last_names="",
        document_type="",
        document_number="",
        birth_date="",
        phone="",
        blood_type="",
        name=None,
        document=None,
    ):
        if name is not None:
            first_names, last_names = name, ""
        if document is not None:
            document_number = document
        normalized_type = document_type.casefold()
        normalized_number = document_number.casefold()
        if any(
            patient.document_type.casefold() == normalized_type
            and patient.document_number.casefold() == normalized_number
            for patient in self._patients
        ):
            raise DuplicateDocumentError
        patient = Patient(
            first_names=first_names,
            last_names=last_names,
            document_type=document_type,
            document_number=document_number,
            birth_date=birth_date,
            phone=phone,
            blood_type=blood_type,
        )
        self._patients.append(patient)
        return patient
