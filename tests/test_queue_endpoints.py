"""HTTP-контракт очереди: реальные FastAPI/SQLite, искусственное чтение Sheets."""
from datetime import datetime, timezone
import time

import pytest
from fastapi.testclient import TestClient

import main
from grading.defense_queue.storage import QueueStore
from grading.defense_queue.sync import sync_group


@pytest.fixture
def queue_client(tmp_path, monkeypatch):
    monkeypatch.setenv('QUEUE_WORKER_ENABLED','0')
    monkeypatch.setattr(main.limiter,'enabled',False)
    now=int(time.time())
    course={'name':'Предмет','timezone':'UTC','google':{'student-name-column':1},
            'queue':{'enabled':True},'labs':{'1':{'short-name':'ЛР1'},'2':{'short-name':'ЛР2'}}}
    grid=[['','','GitHub','2026-11-01','2026-11-08'],['№','ФИО','','ЛР1','ЛР2'],
          ['1','Фамилия Имя Отчество','login','v','v']]
    store=QueueStore(tmp_path/'queue.db')
    def sync(*args,**kwargs):
        summary=sync_group(store,'c','g',course,grid,parse_deadline=lambda v:datetime.fromisoformat(v).replace(tzinfo=timezone.utc),now=now-60)
        return store,summary
    sync()
    store.create_session('future','c','g','teacher',starts_at=now+3600,ends_at=now+7200,local_date='2026-11-07',now=now-100)
    monkeypatch.setattr(main,'get_course_by_id',lambda _:course)
    monkeypatch.setattr(main,'_sync_defense_queue',sync)
    monkeypatch.setattr('grading.defense_queue.runtime.queue_store',lambda:store)
    client=TestClient(main.app)
    return client,store,course,now


def authenticate(client):
    client.cookies.set('admin_session',main.signer.sign(main.ADMIN_LOGIN.encode()).decode())


@pytest.mark.parametrize('method,path,body',[
    ('GET','/admin/queue/sessions',None),
    ('GET','/admin/courses/c/groups/g/queue?session_id=future',None),
    ('GET','/admin/courses/c/queue/settings',None),
    ('PUT','/admin/courses/c/queue/settings',{'random':False,'deadlines':{}}),
    ('POST','/admin/courses/c/groups/g/queue/actions',{'session_id':'future','action':'call_next'}),
    ('PATCH','/admin/courses/c/groups/g/queue/sessions/future',{'cancel':True}),
    ('PUT','/admin/courses/c/groups/g/queue/schedule',{'config':{'source':'manual'}}),
    ('POST','/admin/courses/c/groups/g/queue/schedule/refresh',None),
])
def test_teacher_routes_require_cookie(queue_client,method,path,body):
    client,*_=queue_client
    assert client.request(method,path,json=body).status_code==401


def test_student_can_confirm_without_regrading(queue_client):
    client,store,_,_=queue_client
    path='/courses/c/groups/g/queue'
    assert client.get(path).json()['entries'][0]['state']=='unconfirmed'
    body={'surname':'Фамилия','name':'Имя','patronymic':'Отчество','github':'LOGIN','session_id':'future','will_attend':True}
    assert client.post(path+'/attendance',json=body).status_code==200
    assert client.get(path).json()['entries'][0]['position']==1
    body['name']='Чужое имя'
    assert client.post(path+'/attendance',json=body).status_code==403


def test_freeze_and_teacher_result(queue_client):
    client,store,_,now=queue_client
    store.create_session('current','c','g','teacher',starts_at=now-30,ends_at=now+600,local_date='2026-11-07',now=now-100)
    with store.connection() as con: cid=con.execute("SELECT candidate_id FROM queue_candidates WHERE status='eligible'").fetchone()[0]
    store.attendance('current',cid,True,now=now-40)
    path='/courses/c/groups/g/queue'
    body={'surname':'Фамилия','name':'Имя','patronymic':'Отчество','github':'login','session_id':'current','will_attend':False}
    assert client.post(path+'/attendance',json=body).status_code==409
    assert client.get(path).json()['session']['session_id']=='future'
    authenticate(client)
    admin='/admin/courses/c/groups/g/queue'
    view=client.post(admin+'/actions',json={'session_id':'current','action':'call_next'})
    assert view.status_code==200
    eid=view.json()['current_entry_id']
    result=client.post(admin+'/actions',json={'session_id':'current','action':'result','entry_id':eid,'outcome':'failed'})
    assert result.status_code==200
    assert result.json()['stats']['failed']==1
    assert result.json()['stats']['waiting']==1
    assert result.json()['entries'][0]['attempt']['is_repeat']==1


def test_settings_and_manual_schedule_without_sheet_access(queue_client):
    client,store,_,now=queue_client
    authenticate(client)
    assert client.put('/admin/courses/c/queue/settings',json={'random':True,'deadlines':{'1':None}}).status_code==200
    response=client.post('/admin/courses/c/groups/g/queue/sessions',json={
        'session_id':'manual','teacher_key':'teacher','starts_at':datetime.fromtimestamp(now+8000,timezone.utc).isoformat(),
        'ends_at':datetime.fromtimestamp(now+9000,timezone.utc).isoformat()})
    assert response.status_code==200
    assert any(row['session_id']=='manual' for row in client.get('/admin/queue/sessions').json())
    with store.connection() as con:
        assert con.execute('SELECT random_override FROM queue_settings').fetchone()[0]==1


def test_queue_dates_support_iana_zone_and_explicit_offset():
    from grading.defense_queue.sync import parse_queue_deadline
    from grading.sheets_client import parse_deadline
    course={'timezone':'UTC+3','queue':{'timezone':'Asia/Tokyo'}}
    parsed=parse_queue_deadline('2026-11-07',course,parse_deadline)
    assert parsed.utcoffset().total_seconds()==9*3600
    assert parsed.hour==23
    explicit=parse_queue_deadline('2026-11-07T15:00:00+02:00',course,parse_deadline)
    assert explicit.utcoffset().total_seconds()==2*3600


@pytest.mark.parametrize('config',[
 {'source':'suai','group_id':'127.0.0.1/?x=','subject':'Предмет','week_anchor':'2026-11-02'},
 {'source':'suai','group_id':'123','subject':42,'week_anchor':'2026-11-02'},
 {'source':'import','lessons':[{}]},
 {'source':'import','lessons':[{'key':'x','starts_at':'2026-11-07T10:00','ends_at':'2026-11-07T11:00'}]},
 {'source':'import','lessons':[{'key':'x','starts_at':True,'ends_at':100}]},
])
def test_malformed_schedule_is_rejected_without_saving(queue_client,config):
    client,store,_,_=queue_client
    authenticate(client)
    response=client.put('/admin/courses/c/groups/g/queue/schedule',json={'config':config})
    assert response.status_code==422,response.text
    with store.connection() as con:
        assert con.execute('SELECT count(*) FROM queue_settings').fetchone()[0]==0


def test_teacher_can_add_newly_admitted_student_after_freeze(queue_client):
    client,store,_,now=queue_client
    authenticate(client)
    store.create_session('current','c','g','teacher',starts_at=now-30,ends_at=now+600,local_date='2026-11-07',now=now-100)
    path='/admin/courses/c/groups/g/queue'
    assert client.get(path+'?session_id=current').status_code==200
    sid=store.student('Новый Студент','new-user',now=now)
    cid=store.qualify('c','g',sid,'1',1,deadline_at=None,now=now)
    # The fixture's sheet sync would remove this synthetic new student; keep its admission snapshot here.
    from unittest.mock import patch
    with patch.object(main,'_sync_defense_queue',return_value=(store,{'deadlines_available':True})):
        view=client.get(path+'?session_id=current').json()
        assert cid in [r['candidate_id'] for r in view['available_candidates']]
        assert cid not in [r['candidate_id'] for r in view['entries']]
        response=client.post(path+'/actions',json={'session_id':'current','action':'add_tail','candidate_id':cid})
    assert response.status_code==200,response.text
    assert next(r for r in response.json()['entries'] if r['candidate_id']==cid)['attempt']['is_repeat']==1


def test_public_default_secret_cannot_forge_admin_cookie(queue_client):
    from itsdangerous import TimestampSigner
    client,*_=queue_client
    client.cookies.set('admin_session',TimestampSigner('super-secret-key').sign(main.ADMIN_LOGIN.encode()).decode())
    assert client.get('/admin/queue/sessions').status_code==401


def test_https_admin_cookie_is_secure(queue_client):
    from fastapi.testclient import TestClient
    with TestClient(main.app,base_url='https://testserver') as client:
        response=client.post('/admin/login',json={'login':main.ADMIN_LOGIN,'password':main.ADMIN_PASSWORD})
        assert response.status_code==200
        cookie=response.headers['set-cookie']
        assert 'Secure' in cookie and 'HttpOnly' in cookie and 'SameSite=lax' in cookie


def test_untrusted_origin_cannot_read_cookie_authenticated_queue(queue_client):
    client,*_=queue_client
    authenticate(client)
    blocked=client.options('/admin/queue/sessions',headers={'Origin':'https://attacker.invalid','Access-Control-Request-Method':'GET'})
    assert blocked.status_code==400
    assert 'access-control-allow-origin' not in blocked.headers
    allowed=client.options('/admin/queue/sessions',headers={'Origin':'http://localhost:5173','Access-Control-Request-Method':'GET'})
    assert allowed.status_code==200
    assert allowed.headers['access-control-allow-origin']=='http://localhost:5173'

@pytest.mark.parametrize('mark,eligible',[('v',1),('v-3',1),('x',0),('?',0),('vv',0)])
def test_real_grade_hook_reads_admission_without_writing_marks(tmp_path,monkeypatch,mark,eligible):
    from grading.defense_queue.storage import QueueStore
    monkeypatch.setenv('QUEUE_WORKER_ENABLED','0')
    store=QueueStore(tmp_path/'hook.db')
    monkeypatch.setattr('grading.defense_queue.runtime.queue_store',lambda:store)
    course={'name':'Предмет','timezone':'Europe/Moscow','google':{'student-name-column':1},'queue':{'enabled':True},'labs':{'1':{'short-name':'ЛР1'}}}
    class Sheet:
        def get_all_values(self): return [['','','GitHub','07.11.2026'],['№','ФИО','','ЛР1'],['1','Студент','login',mark]]
        def update_cell(self,*args): raise AssertionError('Queue must not write grades')
    main._after_grade_queue_sync('c','g',course,{'sheet':Sheet()})
    with store.connection() as con:
        assert con.execute("SELECT count(*) FROM queue_candidates WHERE status='eligible'").fetchone()[0]==eligible
        if eligible:
            assert con.execute('SELECT deadline_available FROM queue_candidates').fetchone()[0]==1
