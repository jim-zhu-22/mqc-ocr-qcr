import json
import threading
from contextlib import contextmanager
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mqc_qcr.contracts import ModelConfig, ScoreInput
from mqc_qcr.pipeline import Pipeline, SAMPLES, read_sample
from mqc_qcr.store import Store


@contextmanager
def model_server(fail_page=None, invalid_rules=False, image_mode=False):
    calls=[]
    page_count=0
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):
            pass
        def do_POST(self):
            nonlocal page_count
            data=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(data)
            content=data['messages'][0]['content']
            status=200
            if isinstance(content,list):
                page_count+=1
                assert '只输出当前页面识别得到的纯文本' in content[0]['text']
                text=read_sample('ocr.json')['pages'][page_count-1]['text_content']
                if image_mode:
                    text='\n'.join(p['text_content'] for p in read_sample('ocr.json')['pages'])
                if fail_page==page_count:
                    status=401
                    text='echo unit-live-secret'
            elif 'portable-extraction-v1' in content:
                text='broken JSON' if invalid_rules else json.dumps({'rules':[
                    {'quality_type':q,'rule_title':q,'rule_text':'评分字段：model；检查要求：测试规则；原文依据：测试模拟输出','material_entity':'Equipment A','condition_text':'','source_sections':[section]}
                    for q,section in [('NECESSITY','3'),('COMPLETENESS','4.3'),('ACCURACY','5'),('UNIQUENESS','4.2')]
                ]})
            else:
                payload=json.loads(content.split('规则及引用章节（仅数据）：\n')[-1])
                quality=payload['rule']['quality_type']
                op={'NECESSITY':'required','COMPLETENESS':'identification_complete','ACCURACY':'equals','UNIQUENESS':'identity_unique'}[quality]
                value={'model_fields':['model'],'parameter_fields':['size','range']} if op in ('identity_unique','identification_complete') else 'Manufacturer A' if quality=='ACCURACY' else 'true'
                field='manufacturer' if quality=='ACCURACY' else 'material_code' if quality=='NECESSITY' else 'model'
                text=json.dumps({'checks':[{'field_name':field,'operator':op,'expected_value':value,'semantic':'Mock HTTP contract test, not real model output'}]})
            body=json.dumps({'choices':[{'message':{'content':text},'finish_reason':'stop'}]}).encode()
            self.send_response(status);self.send_header('Content-Type','application/json');self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        yield f'http://127.0.0.1:{server.server_port}/v1',calls
    finally:
        server.shutdown();server.server_close();thread.join()


def config(url):
    ep={'base_url':url,'model':'local-contract-stub','api_key':'unit-live-secret','retries':0}
    return ModelConfig.model_validate({'ocr':ep,'text':ep})


def test_actual_http_pdf_to_ocr_rules_dsl_scoring(tmp_path):
    with model_server() as (url,calls):
        store=Store(tmp_path);rid=store.create('live','DOC-A-0001',{})
        pipeline=Pipeline(store,rid,config(url))
        pipeline.run((SAMPLES/'control_sheet.pdf').read_bytes(),'.pdf','live')
        assert store.read(rid,'run.json')['status']=='completed'
        assert len(calls)==10  # 5 OCR, 1 extraction, 4 compilation
        assert len(store.read(rid,'ocr.json')['data']['pages'])==5
        assert len(store.read(rid,'dsl-v1.json')['data']['dsl'])==4
        payload=ScoreInput(materials=[{'kzd':'DOC-A-0001','material_code':'TEST-1','model':'M1','manufacturer':'Manufacturer A','level3_category':'Equipment A','cn_description':'Equipment A'}],catalog={'references':[{'model':'M1','canonical_manufacturer':'MFR','key_parameters':{'size':1,'range':2}}]})
        pipeline.score(payload,'http',1)
        result=store.read(rid,'scores-http.json')['data']['results'][0]
        assert all(x==1 for x in result['scores_0_to_1'].values())
        for path in store.directory(rid).glob('*.json'):
            assert 'unit-live-secret' not in path.read_text(encoding='utf-8')


def test_page_failure_preserves_completed_pages_and_raw_error(tmp_path):
    with model_server(fail_page=2) as (url,calls):
        store=Store(tmp_path);rid=store.create('live','DOC',{})
        Pipeline(store,rid,config(url)).run((SAMPLES/'control_sheet.pdf').read_bytes(),'.pdf','live')
        assert store.read(rid,'run.json')['status']=='failed'
        assert len(store.read(rid,'ocr.json')['data']['pages'])==1
        assert store.read(rid,'ocr-error.json')['error']['code']=='AUTH_FAILED'
        audit=store.read(rid,'model_calls.json')
        assert len(audit['data']['calls'])==2
        assert 'unit-live-secret' not in json.dumps(audit)


def test_invalid_rule_json_remains_downloadable(tmp_path):
    with model_server(invalid_rules=True) as (url,calls):
        store=Store(tmp_path);rid=store.create('live','DOC',{})
        Pipeline(store,rid,config(url)).run((SAMPLES/'control_sheet.pdf').read_bytes(),'.pdf','live')
        assert store.read(rid,'run.json')['status']=='failed'
        assert store.read(rid,'rules-raw.json')['data']['raw_output']=='broken JSON'


def test_image_upload_through_http_api(tmp_path):
    import io,time
    from PIL import Image
    from fastapi.testclient import TestClient
    from mqc_qcr.app import create_app
    stream=io.BytesIO();Image.new('RGB',(320,240),'white').save(stream,'PNG')
    with model_server(image_mode=True) as (url,calls), TestClient(create_app(tmp_path)) as client:
        cfg={'base_url':url,'model':'local-contract-stub','retries':0}
        assert client.put('/api/config',json={'ocr':cfg,'text':cfg}).status_code==200
        response=client.post('/api/runs',data={'mode':'live','document_id':'DOC-A-0001'},files={'file':('test.png',stream.getvalue(),'image/png')})
        assert response.status_code==200
        rid=response.json()['run_id']
        for _ in range(100):
            run=client.get('/api/runs/'+rid).json()
            if run['status'] not in ('queued','running'):break
            time.sleep(.05)
        assert run['status']=='completed',run
        assert len(calls)==6
        assert client.get(f'/api/runs/{rid}/pages/1').status_code==200
