-- Autor: Francisco Salom Zuluaga
-- Fecha de creación: 2025-06-12
-- Versión: 1.0
-- Descripción: Vistas y funciones de consulta relacional.
CREATE VIEW clinica.v_cartera AS
SELECT f.factura_id, f.paciente_id, f.fecha_emision, f.estado,
       pck_facturacion.fn_total_factura(f.factura_id) AS total,
       pck_facturacion.fn_saldo_factura(f.factura_id) AS saldo
FROM clinica.facturas f;

CREATE VIEW clinica.v_facturas_pendientes AS
SELECT * FROM clinica.v_cartera WHERE estado = 'EMITIDA' AND saldo > 0;

CREATE VIEW clinica.v_pacientes_frecuentes AS
SELECT p.paciente_id, p.nombres, p.apellidos, count(a.atencion_id) AS atenciones
FROM clinica.pacientes p JOIN clinica.citas c USING (paciente_id)
JOIN clinica.atenciones a USING (cita_id)
GROUP BY p.paciente_id, p.nombres, p.apellidos;

CREATE FUNCTION clinica.fn_citas_periodo(p_desde timestamptz, p_hasta timestamptz)
RETURNS TABLE (cita_id varchar, paciente_id varchar, medico_id varchar,
               inicio timestamptz, fin timestamptz, estado varchar)
LANGUAGE sql STABLE SET search_path = pg_catalog, clinica AS $$
    SELECT c.cita_id, c.paciente_id, c.medico_id, c.inicio, c.fin, c.estado
    FROM clinica.citas c WHERE c.inicio >= p_desde AND c.inicio < p_hasta ORDER BY c.inicio;
$$;

CREATE FUNCTION clinica.fn_ingresos_periodo(p_desde timestamptz, p_hasta timestamptz)
RETURNS TABLE (fecha date, ingresos numeric, cantidad_pagos bigint)
LANGUAGE sql STABLE SET search_path = pg_catalog, clinica AS $$
    SELECT (p.fecha_pago AT TIME ZONE 'America/Bogota')::date, sum(p.monto), count(*)
    FROM clinica.pagos p WHERE p.fecha_pago >= p_desde AND p.fecha_pago < p_hasta
    GROUP BY 1 ORDER BY 1;
$$;

-- Ejemplo de cursor, registro y variable. Consulta de cartera por paciente.
CREATE FUNCTION clinica.fn_cartera_paciente(p_paciente_id varchar)
RETURNS numeric LANGUAGE plpgsql STABLE SET search_path = pg_catalog, clinica AS $$
DECLARE
    c_facturas CURSOR FOR SELECT factura_id FROM clinica.facturas
        WHERE paciente_id = p_paciente_id AND estado = 'EMITIDA';
    r_factura record;
    V_total numeric := 0;
BEGIN
    FOR r_factura IN c_facturas LOOP
        V_total := V_total + pck_facturacion.fn_saldo_factura(r_factura.factura_id);
    END LOOP;
    RETURN V_total;
END;
$$;
