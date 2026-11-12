import os
import re
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta
from threading import Barrier
from uuid import uuid4

import psycopg
import pytest
from werkzeug.security import generate_password_hash

from app import create_app
from app.appointment_repository import AppointmentConflictError, AppointmentStateError
from app.database import Database
from app.postgres_appointments import PostgresAppointmentRepository, AppointmentPermissionError
from app.validation import COLOMBIA_TIMEZONE

ADMIN = os.environ.get("VITALIA_TEST_URL", "")
RUNTIME = os.environ.get("VITALIA_TEST_APP_URL", "")
pytestmark = pytest.mark.skipif(not ADMIN or not RUNTIME, reason="Requiere ambas conexiones de una base exclusiva _pruebas")
PASSWORD = "ClaveWebSoloPruebas_123!"


@pytest.fixture
def data():
    identifier = uuid4().hex
    user, other, doctor_user = uuid4(), uuid4(), uuid4()
    with psycopg.connect(ADMIN) as c:
        assert c.execute('SELECT current_database()').fetchone()[0].endswith('_pruebas')
        for actor, role in [(user,'RECEPCION'),(other,'FACTURACION'),(doctor_user,'MEDICO')]:
            c.execute("INSERT INTO clinica.usuarios(usuario_id,nombre_usuario,password_hash,rol_id) SELECT %s,%s,%s,rol_id FROM clinica.roles WHERE nombre=%s",
                      (actor, 'dev04_'+actor.hex[:15], generate_password_hash(PASSWORD), role))
        patient = c.execute("INSERT INTO clinica.pacientes(nombres,apellidos,tipo_documento,numero_documento,fecha_nacimiento) VALUES('Ana','Torres','CC',%s,'1990-01-01') RETURNING paciente_id", (str(uuid4().int)[:18],)).fetchone()[0]
        doctor = 'MED-'+identifier
        c.execute("INSERT INTO clinica.medicos(medico_id,nombre,registro_profesional,usuario_id) VALUES(%s,%s,%s,%s)", (doctor,'Dra. Catalina Torres '+identifier[:5],identifier,doctor_user))
    with psycopg.connect(RUNTIME) as c:
        name, login = c.execute('SELECT current_database(),current_user').fetchone()
        assert name.endswith('_pruebas') and login=='vitalia_app'
    config = {'DATA_BACKEND':'postgres','POSTGRES_URL':RUNTIME,'SECRET_KEY':'clave-estable-de-pruebas-agenda-persistente','TESTING':True}
    app = create_app(config=config)
    client = app.test_client()
    username = 'dev04_'+user.hex[:15]
    assert client.post('/login',data={'username':username,'password':PASSWORD}).status_code==302
    start = (datetime.now(COLOMBIA_TIMEZONE)+timedelta(days=3)).replace(hour=10,minute=0,second=0,microsecond=0)
    repo = PostgresAppointmentRepository(Database(RUNTIME),lambda:user)
    return dict(user=user,other=other,doctor_user=doctor_user,patient=patient,doctor=doctor,config=config,app=app,client=client,start=start,repo=repo)


def form(client):
    body=client.get('/agenda/nueva').get_data(as_text=True)
    return {key:re.search(r'name="'+key+r'" value="([^"]+)"',body).group(1) for key in ['_csrf_token','appointment_id']}


def book(data, start=None, identifier=None):
    start=start or data['start']
    return data['repo'].add(data['patient'],data['doctor'],start,start+timedelta(minutes=30),appointment_id=identifier)


def query(sql, parameters=()):
    with psycopg.connect(ADMIN) as c:
        return c.execute(sql,parameters).fetchall()


def historical(appointment, start, end):
    # Solo en la base temporal de pruebas: simula una reserva creada antes del reloj actual.
    with psycopg.connect(ADMIN) as c:
        c.execute('ALTER TABLE clinica.citas DISABLE TRIGGER tr_cita_fecha')
        c.execute('UPDATE clinica.citas SET inicio=%s,fin=%s WHERE cita_id=%s',(start,end,appointment.appointment_id))
        c.execute('ALTER TABLE clinica.citas ENABLE TRIGGER tr_cita_fecha')


def test_web_booking_real_restart_timezone_and_server_actor(data):
    client=data['client']; payload=form(client)
    payload.update(patient_id=data['patient'],doctor_id=data['doctor'],date=data['start'].strftime('%Y-%m-%d'),start_time='10:00',end_time='10:30',p_actor=str(data['other']))
    assert client.post('/agenda',data=payload).status_code==302
    assert client.post('/agenda',data=payload).status_code==302
    saved=query('SELECT inicio,creado_por FROM clinica.citas WHERE cita_id=%s',(payload['appointment_id'],))
    assert len(saved)==1 and saved[0][0]==data['start'] and saved[0][1]==data['user']
    assert query('SELECT count(*) FROM clinica.auditoria_citas WHERE cita_id=%s',(payload['appointment_id'],))[0][0]==1
    restarted=create_app(config=data['config']).test_client()
    restarted.set_cookie('session',client.get_cookie('session').value)
    html=restarted.get('/agenda').get_data(as_text=True)
    assert 'Catalina Torres' in html and '10:00' in html and data['patient'] in html
    assert 'Catalina Torres' in restarted.get('/pacientes').get_data(as_text=True)


def test_web_requires_csrf_and_server_generated_form_id(data):
    payload=form(data['client']); base=dict(patient_id=data['patient'],doctor_id=data['doctor'],date=data['start'].strftime('%Y-%m-%d'),start_time='10:00',end_time='10:30')
    assert data['client'].post('/agenda',data={**base,'appointment_id':payload['appointment_id']}).status_code==400
    assert data['client'].post('/agenda',data={**base,**payload,'appointment_id':'CIT-'+uuid4().hex}).status_code==400
    assert query('SELECT count(*) FROM clinica.citas WHERE paciente_id=%s',(data['patient'],))[0][0]==0


def test_reschedule_rollback_and_web_values_preserved(data):
    one=book(data);two=book(data,data['start']+timedelta(hours=1))
    original=query('SELECT inicio,fin,revision FROM clinica.citas WHERE cita_id=%s',(one.appointment_id,))[0]
    audit=query('SELECT count(*) FROM clinica.auditoria_citas WHERE cita_id=%s',(one.appointment_id,))[0][0]
    page=data['client'].get(f'/agenda/{one.appointment_id}/reprogramar').get_data(as_text=True)
    token=re.search(r'name="_csrf_token" value="([^"]+)"',page).group(1)
    response=data['client'].post(f'/agenda/{one.appointment_id}/reprogramar',data={'_csrf_token':token,'revision':str(one.revision),'date':data['start'].strftime('%Y-%m-%d'),'start_time':'11:00','end_time':'11:30'})
    assert response.status_code==400 and 'value="11:00"' in response.get_data(as_text=True)
    assert query('SELECT inicio,fin,revision FROM clinica.citas WHERE cita_id=%s',(one.appointment_id,))[0]==original
    assert query('SELECT count(*) FROM clinica.auditoria_citas WHERE cita_id=%s',(one.appointment_id,))[0][0]==audit
    changed=data['repo'].reschedule(one.appointment_id,data['start']+timedelta(hours=2),data['start']+timedelta(hours=2,minutes=30),one.revision)
    assert changed.revision==one.revision+1
    assert data['repo'].reschedule(one.appointment_id,data['start']+timedelta(hours=2),data['start']+timedelta(hours=2,minutes=30),one.revision).revision==changed.revision
    with pytest.raises(AppointmentStateError):
        data['repo'].reschedule(one.appointment_id,data['start']+timedelta(hours=3),data['start']+timedelta(hours=3,minutes=30),one.revision)


def test_cancellation_persists_idempotent_and_frees_interval(data):
    one=book(data)
    cancelled=data['repo'].change_status(one.appointment_id,'CANCELADA',expected_revision=one.revision)
    assert cancelled.status=='CANCELADA'
    data['repo'].change_status(one.appointment_id,'CANCELADA',expected_revision=one.revision)
    second=book(data)
    assert second.appointment_id!=one.appointment_id
    assert query('SELECT count(*) FROM clinica.auditoria_citas WHERE cita_id=%s',(one.appointment_id,))[0][0]==2
    assert query('SELECT estado FROM clinica.citas WHERE cita_id=%s',(one.appointment_id,))[0][0]=='CANCELADA'


def test_pending_expires_but_started_attention_requires_manual_closing(data):
    one=book(data)
    now=datetime.now(COLOMBIA_TIMEZONE)
    historical(one,now-timedelta(hours=2),now-timedelta(hours=1))
    closed=next(a for a in data['repo'].list_all() if a.appointment_id==one.appointment_id)
    assert closed.status=='CERRADA' and closed.closed_by_time
    with pytest.raises(AppointmentStateError):
        data['repo'].change_status(one.appointment_id,'EN_ATENCION',expected_revision=closed.revision)
    two=book(data,data['start']+timedelta(hours=1))
    historical(two,now-timedelta(minutes=10),now+timedelta(minutes=20))
    two=next(a for a in data['repo'].list_all() if a.appointment_id==two.appointment_id)
    started=data['repo'].change_status(two.appointment_id,'EN_ATENCION',expected_revision=two.revision)
    historical(started,now-timedelta(hours=2),now-timedelta(hours=1))
    started=next(a for a in data['repo'].list_all() if a.appointment_id==two.appointment_id)
    assert started.status=='EN_ATENCION'
    ended=data['repo'].change_status(started.appointment_id,'CERRADA',expected_revision=started.revision)
    assert ended.status=='CERRADA' and not ended.closed_by_time


@pytest.mark.parametrize('role',['MEDICO','FACTURACION'])
def test_roles_cannot_manage_agenda_in_web_or_sql(data,role):
    actor=data['doctor_user'] if role=='MEDICO' else data['other']
    client=create_app(config=data['config']).test_client()
    assert client.post('/login',data={'username':'dev04_'+actor.hex[:15],'password':PASSWORD}).status_code==302
    for path in ['/agenda','/agenda/nueva','/pacientes']:
        assert client.get(path).status_code==403
    assert client.post('/agenda',data={}).status_code==403
    unauthorized=PostgresAppointmentRepository(Database(RUNTIME),lambda:actor)
    with pytest.raises(AppointmentPermissionError):
        unauthorized.add(data['patient'],data['doctor'],data['start'],data['start']+timedelta(minutes=30))
    with pytest.raises(AppointmentPermissionError):unauthorized.list_all()


def test_administrator_can_manage_agenda(data):
    with psycopg.connect(ADMIN) as c:
        c.execute("UPDATE clinica.usuarios SET rol_id=(SELECT rol_id FROM clinica.roles WHERE nombre='ADMINISTRADOR') WHERE usuario_id=%s",(data['user'],))
    one=book(data)
    assert data['client'].get('/agenda').status_code==200
    assert data['repo'].change_status(one.appointment_id,'CANCELADA',expected_revision=one.revision).status=='CANCELADA'


def test_inactive_patient_and_doctor_rejected_and_catalog_is_sql(data):
    assert any(d.doctor_id==data['doctor'] and 'Catalina Torres' in d.name for d in data['repo'].list_doctors())
    with psycopg.connect(ADMIN) as c:c.execute('UPDATE clinica.pacientes SET activo=false WHERE paciente_id=%s',(data['patient'],))
    with pytest.raises(AppointmentStateError):book(data)
    with psycopg.connect(ADMIN) as c:
        c.execute('UPDATE clinica.pacientes SET activo=true WHERE paciente_id=%s',(data['patient'],))
        c.execute('UPDATE clinica.medicos SET activo=false WHERE medico_id=%s',(data['doctor'],))
    with pytest.raises(AppointmentStateError):book(data)
    assert not next(d for d in data['repo'].list_doctors() if d.doctor_id==data['doctor']).active
    assert data['doctor'] not in data['client'].get('/agenda/nueva').get_data(as_text=True)


def test_two_connections_overlapping_only_one_commits(data):
    barrier=Barrier(2)
    def add(offset):
        barrier.wait()
        try:return book(data,data['start']+timedelta(minutes=offset)).appointment_id
        except AppointmentConflictError:return None
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(add,[0,15]))
    assert sum(x is not None for x in result)==1
    assert query('SELECT count(*) FROM clinica.citas WHERE paciente_id=%s',(data['patient'],))[0][0]==1
    assert query('SELECT count(*) FROM clinica.auditoria_citas a JOIN clinica.citas c USING(cita_id) WHERE c.paciente_id=%s',(data['patient'],))[0][0]==1


def test_concurrent_rescheduling_detects_stale_screen(data):
    one=book(data);barrier=Barrier(2)
    def change(hours):
        barrier.wait()
        try:
            data['repo'].reschedule(one.appointment_id,data['start']+timedelta(hours=hours),data['start']+timedelta(hours=hours,minutes=30),one.revision)
            return True
        except AppointmentStateError:return False
    with ThreadPoolExecutor(max_workers=2) as pool:result=list(pool.map(change,[1,2]))
    assert sorted(result)==[False,True]
    assert query('SELECT revision FROM clinica.citas WHERE cita_id=%s',(one.appointment_id,))[0][0]==1


def test_rollback_removes_appointment_and_audit(data):
    identifier='CIT-'+uuid4().hex
    with psycopg.connect(RUNTIME) as c:
        c.execute('CALL pck_agenda.SP_agendar_cita(%s,%s,%s,%s,%s,%s)',(identifier,data['patient'],data['doctor'],data['start'],data['start']+timedelta(minutes=30),data['user']))
        c.rollback()
    assert query('SELECT cita_id FROM clinica.citas WHERE cita_id=%s',(identifier,))==[]
    assert query('SELECT cita_id FROM clinica.auditoria_citas WHERE cita_id=%s',(identifier,))==[]


def test_same_request_id_with_changed_data_is_rejected(data):
    identifier='CIT-'+uuid4().hex
    book(data,identifier=identifier)
    with pytest.raises(AppointmentStateError):book(data,data['start']+timedelta(hours=2),identifier=identifier)
    assert query('SELECT count(*) FROM clinica.citas WHERE cita_id=%s',(identifier,))[0][0]==1


def test_patient_and_doctor_do_not_change_when_rescheduling(data):
    one=book(data)
    payload=form(data['client'])
    response=data['client'].post(f'/agenda/{one.appointment_id}/reprogramar',data={
        '_csrf_token':payload['_csrf_token'],'revision':str(one.revision),'date':data['start'].strftime('%Y-%m-%d'),
        'start_time':'12:00','end_time':'12:30','patient_id':'inventado','doctor_id':'inventado',
    })
    assert response.status_code==303
    assert query('SELECT paciente_id,medico_id FROM clinica.citas WHERE cita_id=%s',(one.appointment_id,))[0]==(data['patient'],data['doctor'])
