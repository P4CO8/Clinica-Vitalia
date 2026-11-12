// Antes de ejecutar, verificar en PostgreSQL las referencias y sus permisos.
// Variables del entorno: PACIENTE_ID, MEDICO_ID, CITA_ID, AUTOR_ID.
const documental = db.getSiblingDB("clinica_documental");
const pacienteId = process.env.PACIENTE_ID;
const medicoId = process.env.MEDICO_ID;
const citaId = process.env.CITA_ID;
const autorId = process.env.AUTOR_ID;
if (![pacienteId, medicoId, citaId, autorId].every(Boolean)) {
  throw new Error("Define PACIENTE_ID, MEDICO_ID, CITA_ID y AUTOR_ID con referencias verificadas.");
}
const pruebaId = new ObjectId().toString();
const coleccion = documental.evoluciones_clinicas;
try {
  const resultado = coleccion.insertMany([
    { pacienteId, medicoId, citaId, autorId, pruebaId, fecha: new Date("2030-01-10T14:00:00Z"),
      tipo: "EVOLUCION", version: NumberInt(1), datos: { nota: "Control de prueba", signosVitales: { pulso: 72 } } },
    { pacienteId, medicoId, citaId, autorId, pruebaId, fecha: new Date("2030-01-10T14:30:00Z"),
      tipo: "LABORATORIO", version: NumberInt(1), datos: { examen: "Resultado de prueba", resultado: "Registrado" } }
  ]);
  assert.eq(coleccion.countDocuments({ pruebaId }), 2);
  const encontrado = coleccion.find({
    pruebaId, pacienteId, fecha: { $gte: new Date("2030-01-01T00:00:00Z"), $lt: new Date("2030-02-01T00:00:00Z") },
    "datos.signosVitales.pulso": { $gte: 60, $lte: 100 }
  }).toArray();
  assert.eq(encontrado.length, 1);
  const primero = resultado.insertedIds[0];
  assert.eq(coleccion.updateOne(
    { _id: primero, pruebaId, version: NumberInt(1) },
    { $set: { "datos.nota": "Seguimiento actualizado" }, $inc: { version: NumberInt(1) } }
  ).modifiedCount, 1);
  assert.eq(coleccion.findOne({ _id: primero }).version, 2);
  const resumen = coleccion.aggregate([
    { $match: { pruebaId } },
    { $group: {
      _id: { tipo: "$tipo", mes: { $dateToString: { format: "%Y-%m", date: "$fecha", timezone: "America/Bogota" } } },
      total: { $sum: 1 }
    } },
    { $sort: { "_id.tipo": 1 } }
  ]).toArray();
  assert.eq(resumen.length, 2);
  printjson({ consultaAnidada: encontrado.length, resumen });
  assert.eq(coleccion.deleteOne({ _id: primero, pruebaId }).deletedCount, 1);
  assert.eq(coleccion.countDocuments({ pruebaId }), 1);
  print("CRUD, filtro anidado y agregación correctos.");
} finally {
  coleccion.deleteMany({ pruebaId });
}
