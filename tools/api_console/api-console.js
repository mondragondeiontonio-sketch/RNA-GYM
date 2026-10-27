'use strict';
const $ = id => document.getElementById(id);
let tasks = [], pollTimer = null;
const terminal = new Set(['EXECUTED','FAILED','BLOCKED','NOT_APPLICABLE','CANCELLED','INTERRUPTED']);
function key() { return 'console-' + crypto.randomUUID(); }
function show(method,path,body,status,result) {
  $('traffic-status').textContent = new Date().toLocaleTimeString() + ' · HTTP ' + status;
  $('response').textContent = method + ' ' + path + '\n' + (body ? JSON.stringify(body,null,2) + '\n' : '') + '\nHTTP ' + status + '\n' + JSON.stringify(result,null,2);
}
async function api(method,path,body=null,idempotency=null) {
  const headers = {'Authorization':'Bearer ' + $('token').value};
  if (body !== null) headers['Content-Type'] = 'application/json';
  if (idempotency) headers['Idempotency-Key'] = idempotency;
  const response = await fetch(path,{method,headers,body:body===null ? undefined : JSON.stringify(body)});
  const result = await response.json();
  show(method,path,body,response.status,result);
  if (result.run_id) $('run-id').value = result.run_id;
  return {status:response.status,result};
}
async function health() {
  const {status,result} = await api('GET','/v1/health');
  $('health').textContent = status===200 ? result.status + ' · ' + result.task_count + ' tasks · ' + result.gpu_devices.join(', ') + ' · FM CPU fallback: disabled' : result.reason;
}
function render() {
  const needle = $('filter').value.toLowerCase();
  const rows = tasks.filter(t => JSON.stringify(t).toLowerCase().includes(needle));
  $('task-count').textContent = rows.length + ' / ' + tasks.length;
  $('task-rows').replaceChildren();
  for (const t of rows) {
    const tr = document.createElement('tr');
    const first = document.createElement('td'); first.textContent = t.task_id;
    const family = document.createElement('small'); family.textContent = t.source_family_id || 'source unresolved'; first.append(family);
    const button = document.createElement('button'); button.textContent = '提交试跑';
    button.addEventListener('click', () => action(async () => { const r=await api('POST','/v1/tasks/'+t.task_id+'/pilot',{},key()); if(r.result.run_id) autoPoll(r.result.run_id); })); first.append(button);
    const state = document.createElement('td'); state.className = 'status ' + t.status; state.textContent = t.status;
    const registered = document.createElement('small'); registered.textContent = t.registered_state; state.append(registered);
    const issue = document.createElement('td'); issue.textContent = t.issues.join(' / ') || 'READY';
    const next = document.createElement('small'); next.textContent = t.next_action || ''; issue.append(next);
    tr.append(first,state,issue); $('task-rows').append(tr);
  }
}
async function loadTasks() { const r=await api('GET','/v1/tasks'); if(r.status===200){tasks=r.result.tasks;render();} }
async function poll() { const id=$('run-id').value; if(!/^RUN_[0-9a-f]{32}$/.test(id)) throw Error('请先选择有效 Run ID'); return api('GET','/v1/runs/'+id); }
function autoPoll(id) {
  clearTimeout(pollTimer);
  const tick = async () => {
    if($('run-id').value!==id) return;
    try { const r=await poll(); if(r.status===200 && !terminal.has(r.result.state)) pollTimer=setTimeout(tick,1200); }
    catch(e) { $('traffic-status').textContent=e.message; }
  }; pollTimer=setTimeout(tick,500);
}
async function action(fn) { try { await fn(); } catch(e) { $('traffic-status').textContent='请求失败：'+e.message; } }
$('connect').addEventListener('click',()=>action(health));
$('tasks').addEventListener('click',()=>action(loadTasks));
$('filter').addEventListener('input',render);
$('all-pilots').addEventListener('click',()=>action(async()=>{
  if(!confirm('通过 API 提交全部登记任务。未准入任务将 BLOCKED；不会绕过 gate。继续？')) return;
  await api('POST','/v1/tasks/pilots',{task_ids:'all'},key());
}));
$('submit').addEventListener('click',()=>action(async()=>{
  const kind=$('mode').value;
  const body=kind==='checks' ? {kind,suite:$('suite').value} : {kind,initialization:$('init').value,seed:Number($('seed').value)};
  if(kind==='encoder') body.records=$('sequence').value.split('\n').map((sequence,i)=>({observation_id:'interactive_'+i,sequence}));
  const r=await api('POST','/v1/runs',body,key()); if(r.result.run_id) autoPoll(r.result.run_id);
}));
$('poll').addEventListener('click',()=>action(poll));
for(const name of ['result','events','cancel','resume','replay']) {
  $(name).addEventListener('click',()=>action(async()=>{
    clearTimeout(pollTimer);
    const id=$('run-id').value;if(!/^RUN_[0-9a-f]{32}$/.test(id)) throw Error('无效 Run ID');
    const get=['result','events'].includes(name);
    const r=await api(get?'GET':'POST','/v1/runs/'+id+'/'+name,get?null:{},name==='resume'?key():null);
    if(name==='resume' && r.status===200) autoPoll(id);
  }));
}
