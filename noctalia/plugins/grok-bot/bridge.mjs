import net from 'node:net';
import fs from 'node:fs';
import path from 'node:path';
import {spawn} from 'node:child_process';
const dir=path.join(process.env.XDG_STATE_HOME||path.join(process.env.HOME,'.local/state'),'noctalia-grok-bridge');
const socketPath=path.join(dir,'bridge.sock');
fs.mkdirSync(dir,{recursive:true,mode:0o700}); fs.chmodSync(dir,0o700);
if(process.argv[2]==='request'){
 const req=process.argv[3]==='--file'?JSON.parse(fs.readFileSync(process.argv[4],'utf8')):{method:process.argv[3]||'health'};
 await new Promise(resolve=>{
  const socket=net.createConnection(socketPath);let text='';
  socket.setEncoding('utf8');
  socket.setTimeout(25000);
  socket.on('connect',()=>socket.end(JSON.stringify(req)+'\n'));
  socket.on('data',chunk=>text+=chunk);
  socket.on('end',()=>{process.stdout.write(text);resolve();});
  socket.on('timeout',()=>socket.destroy(Error('Bridge request timed out; do not resend automatically')));
  socket.on('error',e=>{console.log(JSON.stringify({ok:false,error:e.message}));resolve();});
 });
 process.exit();
}
const ensure=process.argv[2]==='ensure';
const forwardArgs=process.argv.slice(3);
if(!ensure&&process.argv[2]!=='serve')throw Error('Use serve, ensure, or request');
if(fs.existsSync(socketPath)){
 const alive=await new Promise(resolve=>{const s=net.createConnection(socketPath);s.on('connect',()=>{s.destroy();resolve(true)});s.on('error',()=>resolve(false));});
 if(alive){if(!ensure)spawn('/usr/bin/grok-bot',forwardArgs,{detached:true,stdio:'ignore'}).unref();process.exit(0);}
 fs.unlinkSync(socketPath);
}
const lockPath=path.join(dir,'owner.lock');
try{fs.writeFileSync(lockPath,String(process.pid),{flag:'wx',mode:0o600});}
catch(e){
 if(e.code!=='EEXIST')throw e;
 let live=false;try{process.kill(Number(fs.readFileSync(lockPath,'utf8')),0);live=true;}catch{}
 if(live)process.exit(0);
 fs.unlinkSync(lockPath);fs.writeFileSync(lockPath,String(process.pid),{flag:'wx',mode:0o600});
}
process.on('exit',()=>{try{if(fs.readFileSync(lockPath,'utf8')===String(process.pid))fs.unlinkSync(lockPath);}catch{}});
const app=spawn('/usr/bin/grok-bot',['--remote-debugging-pipe',...forwardArgs],{stdio:['ignore','ignore','ignore','pipe','pipe']});
let buffer='',seq=0,closed=false,session=null,pollBusy=false;
const pending=new Map(),sends=new Map();
function rpc(method,params={},sessionId){
 return new Promise((resolve,reject)=>{
  const id=++seq;const timer=setTimeout(()=>{pending.delete(id);reject(Error('CDP timeout'))},20000);
  pending.set(id,{resolve,reject,timer});
  app.stdio[3].write(JSON.stringify({id,method,params,...sessionId?{sessionId}:{}})+'\0');
 });
}
app.stdio[4].on('data',chunk=>{
 buffer+=chunk.toString();let i;
 while((i=buffer.indexOf('\0'))>=0){
  const line=buffer.slice(0,i);buffer=buffer.slice(i+1);if(!line)continue;
  const reply=JSON.parse(line);const call=pending.get(reply.id);
  if(call){pending.delete(reply.id);clearTimeout(call.timer);reply.error?call.reject(Error(reply.error.message)):call.resolve(reply.result);}
 }
});
const findClient=`function findClient(){
 const pending=[],seen=new Set();
 for(const el of document.querySelectorAll('body,#root,#app,body > div'))for(const key of Object.keys(el))if(key.startsWith('__reactContainer$')||key.startsWith('__reactFiber$')){const root=el[key];if(root)pending.push(root.stateNode?.current||root);}
 while(pending.length&&seen.size<12000){const f=pending.pop();if(!f||seen.has(f))continue;seen.add(f);const v=f.memoizedProps?.value;if(v&&v.sendJournal&&v.roster&&v.transcript)return v;if(f.child)pending.push(f.child);if(f.sibling)pending.push(f.sibling);}
 throw Error('Application client not ready');
}`;
async function evaluate(body){
 if(!session){const targets=await rpc('Target.getTargets');const target=targets.targetInfos.find(t=>t.type==='page'&&t.url.includes('/renderer/')&&t.url.startsWith('file:'));if(!target)throw Error('Renderer not ready');session=(await rpc('Target.attachToTarget',{targetId:target.targetId,flatten:true})).sessionId;}
 try{
  const result=await rpc('Runtime.evaluate',{expression:`(async()=>{${findClient}\nconst client=findClient();${body}})()`,awaitPromise:true,returnByValue:true,timeout:18000},session);
  if(result.exceptionDetails)throw Error(result.exceptionDetails.exception?.description||'Application operation failed');
  return result.result?.value;
 }catch(e){session=null;throw e;}
}
async function status(){return evaluate(`const s=client.roster.snapshots.get();return {ok:true,complete:s.hasCompleteRoster,loadState:s.loadState,updated:Date.now(),agents:(s.agents?.rows||[]).filter(a=>!a.isHiddenFromSidebar&&!a.isRemovedFromSidebar).map(a=>({id:a.id,name:a.name,isRunning:!!a.isRunning,isComposingMessage:!!a.isComposingMessage,waiting:!!a.awaitingUserResponse}))};`);}
async function send(req){
 if(!/^[0-9a-f-]{36}$/i.test(req.agentId||'')||typeof req.text!=='string'||!req.text.trim()||req.text.length>12000||!/^[0-9a-z-]{12,100}$/i.test(req.requestId||''))throw Error('Invalid message request');
 const fingerprint=JSON.stringify([req.agentId,req.text]);
 if(sends.has(req.requestId)){const prior=sends.get(req.requestId);if(prior.fingerprint!==fingerprint)throw Error('Request id reused with different content');return prior.promise;}
 const promise=evaluate(`const id=${JSON.stringify(req.agentId)},text=${JSON.stringify(req.text)};const s=client.roster.snapshots.get();if(!(s.agents?.rows||[]).some(a=>a.id===id&&!a.isHiddenFromSidebar&&!a.isRemovedFromSidebar))throw Error('Agent unavailable');let nonce=null;await client.sendJournal.sendPrompt({agentId:id,prompt:text,onNonceAssigned:e=>{nonce=e.nonce;}});return {ok:true,status:'journaled',nonce};`);
 sends.set(req.requestId,{fingerprint,promise});while(sends.size>128)sends.delete(sends.keys().next().value);
 return promise;
}
const server=net.createServer({allowHalfOpen:true},socket=>{
 socket.setEncoding('utf8');
 let input='',handled=false;socket.setTimeout(30000,()=>socket.destroy());
 socket.on('error',()=>{});
 socket.on('data',async chunk=>{
  input+=chunk;if(input.length>70000){socket.destroy();return;}
  if(!input.includes('\n')||handled)return;handled=true;
  try{
   const req=JSON.parse(input.split('\n')[0]);let response;
   if(req.method==='health')response={ok:true,pid:process.pid,appPid:app.pid,transport:'cdp-pipe'};
   else if(req.method==='status')response=await status();
   else if(req.method==='send')response=await send(req);
   else throw Error('Unsupported bridge method');
   socket.end(JSON.stringify(response)+'\n');
  }catch(e){socket.end(JSON.stringify({ok:false,error:String(e.message).slice(0,400),retryAutomatically:false})+'\n');}
 });
});
server.listen(socketPath,()=>fs.chmodSync(socketPath,0o600));
const timer=setInterval(async()=>{
 if(pollBusy)return;pollBusy=true;
 try{const s=await status();const tmp=path.join(dir,'status.tmp');fs.writeFileSync(tmp,JSON.stringify(s),{mode:0o600});fs.renameSync(tmp,path.join(dir,'status.json'));}
 catch(e){fs.writeFileSync(path.join(dir,'status.json'),JSON.stringify({ok:false,updated:Date.now(),error:String(e.message).slice(0,200)}),{mode:0o600});}
 finally{pollBusy=false;}
},1500);
function cleanup(){if(closed)return;closed=true;clearInterval(timer);server.close();try{fs.unlinkSync(socketPath)}catch{};}
app.on('exit',()=>{cleanup();process.exitCode=0;});
app.on('error',e=>{cleanup();console.error(e.message);process.exitCode=1;});
process.on('SIGTERM',()=>{cleanup();app.kill('SIGTERM');});
process.on('SIGINT',()=>{cleanup();app.kill('SIGTERM');});
