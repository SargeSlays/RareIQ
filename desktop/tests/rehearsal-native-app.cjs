'use strict';
const {app,BrowserWindow,ipcMain}=require('electron');
const http=require('node:http'),path=require('node:path'),fs=require('node:fs'),{spawn}=require('node:child_process');
const {NativeBroadcast}=require('../broadcast.cjs'),{RehearsalCoordinator}=require('../rehearsal.cjs'),{SharedEncoderGroup}=require('../shared-encoder.cjs'),{createOutputCapture}=require('../output-capture.cjs');
const evidence=process.env.PRODUCER_REHEARSAL_NATIVE_EVIDENCE,root=path.resolve(__dirname,'../..'),python=path.join(root,'.venv/Scripts/python.exe');
if(!evidence||!path.isAbsolute(evidence))throw Error('Isolated evidence required');
app.setPath('userData',path.join(evidence,'profile'));app.commandLine.appendSwitch('autoplay-policy','no-user-gesture-required');
let server,child,coordinator,broadcast;let sequence=0;
const delay=ms=>new Promise(resolve=>setTimeout(resolve,ms));
app.whenReady().then(async()=>{
 child=spawn(python,['-B',path.join(root,'tools/qa_rehearsal_fixture.py'),path.join(evidence,'backend')],{cwd:root,windowsHide:true,stdio:['ignore','pipe','ignore']});
 let line='';const backend=await new Promise((resolve,reject)=>{const timer=setTimeout(()=>reject(Error('isolated_backend_timeout')),12000);child.stdout.on('data',chunk=>{line+=chunk;if(line.includes('\n')){clearTimeout(timer);try{resolve('http://127.0.0.1:'+JSON.parse(line.split('\n')[0]).port);}catch(_){reject(Error('isolated_backend_invalid'));}}});child.on('exit',()=>{clearTimeout(timer);reject(Error('isolated_backend_exited'));});});
 const identity=await fetch(backend+'/__qa__/identity').then(r=>r.json());if(identity.isolated!==true)throw Error('fixture_identity_required');delete identity.isolated;delete identity.hardware;delete identity.providers;
 const request=async(url,body)=>{if(url.startsWith('/api/production/native-preflight'))return {preflight:{ready:true,generation:1,blockers:[]}};const response=await fetch(backend+url,{method:body?'POST':'GET',headers:body?{'Content-Type':'application/json',Origin:backend}:{},body:body?JSON.stringify(body):undefined,signal:AbortSignal.timeout(12000)});const value=await response.json();if(!response.ok||value.ok===false)throw Object.assign(Error(value.reason||'fixture_failed'),{code:value.reason});return value;};
 const wave=Buffer.alloc(44+48000*5*2);wave.write('RIFF');wave.writeUInt32LE(wave.length-8,4);wave.write('WAVEfmt ',8);wave.writeUInt32LE(16,16);wave.writeUInt16LE(1,20);wave.writeUInt16LE(1,22);wave.writeUInt32LE(48000,24);wave.writeUInt32LE(96000,28);wave.writeUInt16LE(2,32);wave.writeUInt16LE(16,34);wave.write('data',36);wave.writeUInt32LE(wave.length-44,40);for(let i=0;i<48000*5;i++)wave.writeInt16LE(Math.round(Math.sin(i*2*Math.PI*440/48000)*6000),44+i*2);
 const base='<!doctype html><html><head><meta charset="utf-8"><style>html,body,main{margin:0;width:100%;height:100%;overflow:hidden;background:#121a25}iframe{border:0;width:100%;height:100%}</style>';
 let external=0,privateLookups=0;
 server=http.createServer(async(req,res)=>{try{
  const route=new URL(req.url,'http://127.0.0.1').pathname;
  if(route==='/api/guest/rehearsal'){const r=await fetch(backend+route);res.writeHead(r.status,{'Content-Type':'application/json','Cache-Control':'no-store'});return res.end(await r.text());}
  if(route==='/static/rehearsal_room.js'||route==='/static/rehearsal_room.css'){res.setHeader('Content-Type',route.endsWith('.js')?'text/javascript':'text/css');return res.end(fs.readFileSync(path.join(root,'rareiq/web',route)));}
  if(route==='/tone.wav'){res.writeHead(200,{'Content-Type':'audio/wav'});return res.end(wave);}
  res.setHeader('Content-Type','text/html');
  if(route==='/output/studio')return res.end(base+'<link rel="stylesheet" href="/static/rehearsal_room.css"><script defer src="/static/rehearsal_room.js"></script></head><body><main aria-label="Clean Studio Program output"><iframe class="program" src="/program" allow="autoplay"></iframe></main></body></html>');
  if(route==='/program')return res.end(base+'</head><body><canvas width="1280" height="720" style="width:100%;height:100%"></canvas><audio data-audio-source="guest:'+ 'a'.repeat(32)+':microphone" src="/tone.wav" autoplay loop></audio><script>window.ProducerProgramOutput={snapshot:()=>({peerId:"synthetic-rehearsal-peer",generation:1,rendered:true,browserReviewOpen:false,readySources:["camera:1"],audioBlocked:false})};let i=0,c=document.querySelector("canvas").getContext("2d");setInterval(()=>{c.fillStyle=i++%2?"#184860":"#153548";c.fillRect(0,0,1280,720);c.fillStyle="white";c.font="36px sans-serif";c.fillText("LOCAL REHEARSAL TEST",60,120);},100);</script></body></html>');
  res.statusCode=404;res.end('Unavailable');
 }catch(_){res.statusCode=500;res.end('fixture_failed');}});await new Promise(resolve=>server.listen(0,'127.0.0.1',resolve));const origin='http://127.0.0.1:'+server.address().port;
 const output={id:'synthetic-saved',name:'Local test',format:'hd',fps:30,videoBitrateKbps:1000,codec:'libx264',keyframeSeconds:2,audioBitrateKbps:96,twitchVod:true,audioRouting:{}};
 broadcast=new NativeBroadcast({destinations:{getPrivateDestination:async()=>{privateLookups++;throw Error('private_destination_forbidden');}},outputProfiles:{getProfile:async()=>structuredClone(output)},identity,ownerPid:process.pid,request,canPublish:()=>coordinator.canPublish(),confirm:async()=>{external++;throw Error('public_broadcast_forbidden');},createCapture:dimensions=>createOutputCapture({BrowserWindow,ipcMain,origin,...dimensions,onError:code=>{if(coordinator?.active())void coordinator.stop(code);}})});
 coordinator=new RehearsalCoordinator({broadcast,identity,ownerPid:process.pid,request,createEncoderGroup:onState=>new SharedEncoderGroup({python,pythonPackages:'F:/Caches/ProducerPlease/python-packages',onState})});
 await coordinator.refresh();await broadcast.prepare({profileId:output.id});
 const envelope=()=>({requestId:'native-'+(++sequence),revision:coordinator.status().room.revision,generation:coordinator.status().room.generation});
 globalThis.rehearsalFixture={ready:true,broadcast,coordinator,origin,status:()=>coordinator.status(),enter:()=>coordinator.enter((({requestId,revision})=>({requestId,revision}))(envelope())),start:()=>coordinator.start({...envelope(),profileId:output.id}),stop:()=>coordinator.stop(),mark:()=>coordinator.mark({...envelope(),checkId:'video',status:'passed'}),exit:()=>coordinator.exit(envelope()),route:routing=>broadcast.setLiveAudio({outputId:broadcast.audioSession.status().outputId,expectedRevision:broadcast.audioSession.status().revision,requestId:'audio-'+(++sequence),audioRouting:routing}),proof:()=>({external,privateLookups,outputMuted:broadcast.capture.status().locallyMuted}),async close(){await coordinator.close();await broadcast.close();server.close();child.kill();app.quit();}};
}).catch(error=>{globalThis.rehearsalFixtureError=error.code||error.message;child?.kill();});
app.on('window-all-closed',()=>{});app.on('before-quit',()=>child?.kill());
