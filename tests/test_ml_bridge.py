import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from mqc_qcr.contracts import ModelConfig, ScoreInput
from mqc_qcr.pipeline import Pipeline, sample_input
from mqc_qcr.store import Store


def test_enabled_ml_http_raw_response_and_key_redaction(tmp_path):
    secret='ml-test-secret-only'
    calls=[]
    class Handler(BaseHTTPRequestHandler):
        def log_message(self,*args):pass
        def do_POST(self):
            request=json.loads(self.rfile.read(int(self.headers['Content-Length'])))
            calls.append(request)
            assert self.headers['Authorization']=='Bearer '+secret
            body=json.dumps({'score':0.5,'model_version':'CONTRACT-STUB-NOT-TRAINED','evidence':{'test':'mock bridge'},'echo':secret}).encode()
            self.send_response(200);self.send_header('Content-Length',str(len(body)));self.end_headers();self.wfile.write(body)
    server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
    thread=threading.Thread(target=server.serve_forever,daemon=True);thread.start()
    try:
        store=Store(tmp_path);rid=store.create('replay','DOC-A-0001',{})
        worker=Pipeline(store,rid,ModelConfig());worker.run(b'','.pdf','replay')
        data=sample_input();data['materials']=data['materials'][:1]
        data['ml']={'necessity':{'enabled':True,'weight':0.4,'endpoint':{'base_url':f'http://127.0.0.1:{server.server_port}/predict','api_key':secret}}}
        worker.score(ScoreInput.model_validate(data),'ml',1)
        result=store.read(rid,'scores-ml.json')['data']['results'][0]
        assert result['scores_0_to_1']['necessity']==0.8
        assert result['ml_evidence']['necessity']['status']=='completed'
        assert 'raw_response' in result['ml_evidence']['necessity']['response']
        assert len(calls)==1
        for file in store.directory(rid).glob('*.json'):
            assert secret not in file.read_text(encoding='utf-8')
    finally:
        server.shutdown();server.server_close();thread.join()
