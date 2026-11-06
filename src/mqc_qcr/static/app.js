const $ = id => document.getElementById(id);
let active = null, current = null, preview = '', results = [], selectedArtifact = '', polling = false;
const message = (text, error=false) => { $('notice').textContent=text; $('notice').className=error?'error':''; };
async function api(path, options={}) {
  const response = await fetch(path, options);
  const data = await response.json();
  if (!response.ok) throw new Error(data.message || data.error || data.detail || `HTTP ${response.status}`);
  return data;
}
const jsonOptions = (method,data) => ({method,headers:{'Content-Type':'application/json'},body:JSON.stringify(data)});
function action(id, fn) { $(id).addEventListener('click', async()=>{ $(id).disabled=true; try { await fn(); } catch(e){message(e.message,true);} finally {$(id).disabled=false;} }); }
function configValue() {
  const data={};
  for(const kind of ['ocr','text']) data[kind]={base_url:$(kind+'-url').value,api_key:$(kind+'-key').value,model:$(kind+'-model').value,timeout_seconds:Number($(kind+'-timeout').value),retries:Number($(kind+'-retries').value),max_tokens:Number($(kind+'-tokens').value)};
  return data;
}
async function saveConfig(){await api('/api/config',jsonOptions('PUT',configValue()));$('config-status').textContent='连接设置已应用；密钥不会写入文件或导出产物。';}
action('save-config',async()=>{await saveConfig();message('模型配置已应用。');});
action('clear-config',async()=>{for(const k of ['ocr','text'])$(k+'-key').value='';await saveConfig();message('服务内存中的密钥已清除。');});
for(const kind of ['ocr','text'])action('check-'+kind,async()=>{await saveConfig();message('正在发送真实连接检查请求…');const d=await api('/api/config/check/'+kind,{method:'POST'});message(`${kind} 连接成功：${d.response}`);});
$('mode').addEventListener('change',()=>{$('mode-note').textContent=$('mode').value==='replay'?'重放不调用模型。使用脱敏五页控制单和已保存的识别结果；评分仍实际执行。':'此模式将所选文件逐页发送到你配置的视觉服务，再调用文本模型提取与编译规则。';});
action('start',async()=>{const mode=$('mode').value; if(mode==='live')await saveConfig();const form=new FormData();form.append('mode',mode);form.append('document_id',$('document-id').value);if($('document-file').files[0])form.append('file',$('document-file').files[0]);const d=await api('/api/runs',{method:'POST',body:form});active=d.run_id;selectedArtifact='';message('任务已创建，阶段产物会逐步保存。');await refresh();});
async function refresh(){const d=await api('/api/runs');$('runs').replaceChildren();for(const run of d.runs){const b=document.createElement('button');b.className='run'+(active===run.id?' selected':'');b.textContent=run.document_id+' · '+(run.mode==='replay'?'重放':'真实调用');const meta=document.createElement('small');meta.textContent=run.status+' / '+run.stage+' · '+run.id.slice(0,8);b.append(meta);b.onclick=async()=>{active=run.id;selectedArtifact='';try{await refresh();}catch(e){message(e.message,true);}};$('runs').append(b);}if(active)await loadRun();}
async function loadRun(){current=await api('/api/runs/'+active);$('run-state').textContent=`${current.document_id} · ${current.id} · ${current.mode} · ${current.status} / ${current.stage} · 规则版本 ${current.revision}`;
  if(current.error && current.status==='failed')message(current.error.message,true);
  $('export').hidden=false;$('export').href=`/api/runs/${active}/export`;
  const previous=selectedArtifact; $('artifact').replaceChildren();for(const name of current.artifacts){const o=new Option(name,name);$('artifact').add(o);}selectedArtifact=current.artifacts.includes(previous)?previous:(current.artifacts.find(n=>n===`dsl-v${current.revision}.json`)||'run.json');$('artifact').value=selectedArtifact;await loadArtifact();
  const old=$('score-history').value;$('score-history').replaceChildren();if(!current.scores.length)$('score-history').add(new Option('暂无评分',''));for(const s of current.scores)$('score-history').add(new Option(`规则 v${s.revision} · ${s.id}`,s.artifact));if(current.scores.length){$('score-history').value=current.scores.some(s=>s.artifact===old)?old:current.scores.at(-1).artifact;await loadScores();}
}
async function loadArtifact(){if(!active)return;selectedArtifact=$('artifact').value;const d=await api(`/api/runs/${active}/artifacts/${selectedArtifact}`);preview=JSON.stringify(d,null,2);showPreview();$('download').hidden=false;$('download').href=`/api/runs/${active}/artifacts/${selectedArtifact}?download=true`;}
function showPreview(){const term=$('search').value.toLowerCase();const lines=preview.split('\n');const matches=term?lines.filter(l=>l.toLowerCase().includes(term)):lines;$('preview').textContent=matches.join('\n');$('search-count').textContent=term?`找到 ${matches.length} 行；下载始终包含完整JSON`:'';}
$('search').addEventListener('input',showPreview);$('artifact').addEventListener('change',()=>loadArtifact().catch(e=>message(e.message,true)));action('refresh',refresh);
action('load-rules',async()=>{if(!active)throw Error('请先选择任务');const d=await api(`/api/runs/${active}/artifacts/rules-v${current.revision}.json`);$('rules-editor').value=JSON.stringify(d.data.rules,null,2);message('规则已加载；编辑后保存生成新版本。');});
action('save-rules',async()=>{if(!active)throw Error('请先选择任务');const d=await api(`/api/runs/${active}/rules`,jsonOptions('PUT',JSON.parse($('rules-editor').value)));message(d.message);await refresh();});
action('load-sample',async()=>{const data=await api('/api/samples/input');$('materials').value=JSON.stringify(data,null,2);message('50条合成物料及显式合成参考证据已加载；尚未评分。');});
$('materials-file').addEventListener('change',async()=>{try{const f=$('materials-file').files[0];if(f){const v=JSON.parse(await f.text());$('materials').value=JSON.stringify(Array.isArray(v)?{materials:v,catalog:{}}:v,null,2);message('物料输入已加载；请手动发起评分。');}}catch(e){message('JSON解析失败：'+e.message,true);}});
action('score',async()=>{if(!active)throw Error('请先选择任务');const d=await api(`/api/runs/${active}/score`,jsonOptions('POST',JSON.parse($('materials').value)));message(`评分已启动，使用规则版本 ${d.rule_revision}。`);await refresh();});
async function loadScores(){const name=$('score-history').value;if(!name)return;const d=await api(`/api/runs/${active}/artifacts/${name}`);results=d.data.results;$('score-summary').textContent=`${results.length} 条记录 · 规则版本 ${d.data.rule_revision} · 分数范围 0–100，JSON为0–1。点击记录查看规则依据。`;$('scores').querySelector('tbody').replaceChildren();for(const r of results){const tr=document.createElement('tr');for(const v of [r.sample_id,...['necessity','completeness','accuracy','uniqueness','final'].map(k=>(100*r.scores_0_to_1[k]).toFixed(2))]){const td=document.createElement('td');td.textContent=v;tr.append(td);}tr.onclick=()=>showDetails(r);$('scores').querySelector('tbody').append(tr);}}
$('score-history').addEventListener('change',()=>loadScores().catch(e=>message(e.message,true)));
function showDetails(r){$('details').replaceChildren();const h=document.createElement('h3');h.textContent=r.sample_id+' · 规则明细';$('details').append(h);for(const d of r.details){const box=document.createElement('div');box.className='check '+d.result;const title=document.createElement('strong');title.textContent=`${d.dsl_id} · ${d.rule_title}`;const p=document.createElement('p');p.textContent=`${d.quality_type} · ${d.result} · ${d.included_in_score?'计入分母':'不适用'} · 得分 ${d.score} · ${d.reason}`;const b=document.createElement('button');b.className='secondary';b.textContent=`查看 ${d.rule_id} / 页 ${d.source_pages.join(', ')}`;b.onclick=()=>showSource(d);box.append(title,p,b);$('details').append(box);}}
function showSource(d){$('source-panel').hidden=false;$('source-text').textContent=`${d.rule_title}\n章节 ${d.source_sections.join(', ')}\n${d.source_text}`;$('source-pages').replaceChildren();for(const page of d.source_pages){const a=document.createElement('a');a.href=`/api/runs/${active}/pages/${page}`;a.target='_blank';a.rel='noopener';const image=document.createElement('img');image.src=a.href;image.alt=`控制单第${page}页`;a.append(image);$('source-pages').append(a);}$('source-panel').scrollIntoView({behavior:'smooth'});}
async function init(){const cfg=await api('/api/config');for(const k of ['ocr','text']){for(const [field,key]of[['url','base_url'],['model','model'],['timeout','timeout_seconds'],['retries','retries'],['tokens','max_tokens']])$(k+'-'+field).value=cfg[k][key];}if(cfg.ocr.key_configured||cfg.text.key_configured)$('config-status').textContent='服务内存中已有密钥；修改配置时请重新填写密钥。';await refresh();}
init().catch(e=>message(e.message,true));
setInterval(async()=>{if(polling||!active||!current||!['queued','running'].includes(current.status))return;polling=true;try{await refresh();}catch(e){message(e.message,true);}finally{polling=false;}},1800);
