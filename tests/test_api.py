import io
import json
import time
import zipfile
from fastapi.testclient import TestClient
from mqc_qcr.app import create_app


def wait(client,rid):
    for _ in range(150):
        run=client.get('/api/runs/'+rid).json()
        if run['status'] not in ('queued','running'):
            return run
        time.sleep(.05)
    raise AssertionError('local task did not finish')


def test_api_edit_compile_manual_rescore_export_and_secrets(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        assert client.get('/').status_code==200
        assert client.get('/static/app.js').status_code==200
        secret='api-security-test-key'
        cfg={'ocr':{'api_key':secret},'text':{}}
        assert client.put('/api/config',json=cfg).status_code==200
        assert secret not in client.get('/api/config').text
        rid=client.post('/api/runs',data={'mode':'replay','document_id':'DOC-A-0001'}).json()['run_id']
        assert wait(client,rid)['status']=='completed'
        payload=client.get('/api/samples/input').json()
        payload['materials']=payload['materials'][:2]
        first=client.post(f'/api/runs/{rid}/score',json=payload).json()
        run=wait(client,rid)
        name=run['scores'][0]['artifact']
        old=client.get(f'/api/runs/{rid}/artifacts/{name}').content
        rules=client.get(f'/api/runs/{rid}/artifacts/rules-v1.json').json()['data']['rules']
        rules[0]['checks'][0]['expected_value']='NEVER-MATCH'
        rules[0]['checks'][0]['operator']='equals'
        response=client.put(f'/api/runs/{rid}/rules',json=rules)
        assert response.status_code==200
        run=wait(client,rid)
        assert run['revision']==2 and run['compiled_revision']==2
        assert len(run['scores'])==1  # no automatic scoring
        assert client.get(f'/api/runs/{rid}/artifacts/{name}').content==old
        client.post(f'/api/runs/{rid}/score',json=payload)
        run=wait(client,rid)
        assert len(run['scores'])==2
        latest=client.get(f"/api/runs/{rid}/artifacts/{run['scores'][-1]['artifact']}").json()
        assert latest['data']['results'][0]['scores_0_to_1']['necessity']==0
        export=client.get(f'/api/runs/{rid}/export')
        archive=zipfile.ZipFile(io.BytesIO(export.content))
        assert all(n.endswith('.json') for n in archive.namelist())
        assert all(secret.encode() not in archive.read(n) for n in archive.namelist())
        assert client.get(f'/api/runs/{rid}/pages/3').headers['content-type']=='image/png'
        assert client.get('/api/schemas').status_code==200


def test_invalid_credentials_not_echoed_and_cross_origin_blocked(tmp_path):
    with TestClient(create_app(tmp_path)) as client:
        response=client.put('/api/config',json={'ocr':{'api_key':'secret-unit','timeout_seconds':'bad'}})
        assert response.status_code==422 and 'secret-unit' not in response.text
        response=client.put('/api/config',json={},headers={'Origin':'https://untrusted.example'})
        assert response.status_code==403
        response=client.get('/api/runs/invalid')
        assert response.status_code==400


def test_interrupted_run_keeps_artifacts(tmp_path):
    app=create_app(tmp_path)
    rid=app.state.store.create('live','DOC',{})
    app.state.store.stage(rid,'ocr',{'pages':[{'page_num':1,'text_content':'saved'}]},status='running')
    with TestClient(app) as client:
        assert client.get('/api/runs/'+rid).json()['status']=='interrupted'
        assert client.get(f'/api/runs/{rid}/artifacts/ocr.json').json()['data']['pages'][0]['text_content']=='saved'
