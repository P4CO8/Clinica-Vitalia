// Ejecutar como administrador autorizado en clinica_documental.
const documental = db.getSiblingDB("clinica_documental");
const modelos = {
  evoluciones_clinicas: {
    bsonType: "object",
    required: ["pacienteId", "medicoId", "citaId", "autorId", "fecha", "tipo", "datos", "version"],
    properties: {
      pacienteId: { bsonType: "string", minLength: 1 },
      medicoId: { bsonType: "string", minLength: 1 },
      citaId: { bsonType: "string", minLength: 1 },
      autorId: { bsonType: "string", minLength: 1 },
      fecha: { bsonType: "date" },
      tipo: { enum: ["EVOLUCION", "LABORATORIO", "SEGUIMIENTO"] },
      datos: { bsonType: "object", minProperties: 1 },
      version: { bsonType: "int", minimum: 1 },
      pruebaId: { bsonType: "string" }
    }
  },
  eventos_auditoria: {
    bsonType: "object",
    required: ["actorId", "accion", "recursoId", "fecha", "resultado"],
    properties: {
      actorId: { bsonType: "string", minLength: 1 },
      accion: { bsonType: "string", minLength: 1 },
      recursoId: { bsonType: "string", minLength: 1 },
      fecha: { bsonType: "date" },
      resultado: { enum: ["OK", "ERROR", "DENEGADO"] }
    }
  }
};
for (const [nombre, esquema] of Object.entries(modelos)) {
  if (documental.getCollectionNames().includes(nombre)) {
    assert.commandWorked(documental.runCommand({
      collMod: nombre, validator: { $jsonSchema: esquema }, validationLevel: "strict", validationAction: "error"
    }));
  } else {
    assert.commandWorked(documental.createCollection(nombre, {
      validator: { $jsonSchema: esquema }, validationLevel: "strict", validationAction: "error"
    }));
  }
}
documental.evoluciones_clinicas.createIndex({ pacienteId: 1, fecha: -1 }, { name: "ix_evoluciones_paciente_fecha" });
documental.evoluciones_clinicas.createIndex({ citaId: 1 }, { name: "ix_evoluciones_cita" });
documental.eventos_auditoria.createIndex({ actorId: 1, fecha: -1 }, { name: "ix_eventos_actor_fecha" });
print("Modelo documental e índices preparados.");
