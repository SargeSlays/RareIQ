'use strict';
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs');
class Backend{
  constructor(runtime,statePath){this.runtime=runtime;this.statePath=statePath;this.started=null;}
  command(action){
    const runtime=this.runtime;
    if(!runtime||!path.isAbsolute(runtime.projectRoot)||!path.isAbsolute(runtime.python)||!fs.existsSync(runtime.python))return Promise.reject(Error('Studio runtime is missing. Repair the local desktop installation.'));
    return new Promise((resolve,reject)=>{
      const environment={...process.env,PRODUCER_DESKTOP:'1',PYTHONDONTWRITEBYTECODE:'1'};let cwd=runtime.projectRoot;
      if(runtime.buildKind==='bundled-runtime'){
        if(!path.isAbsolute(runtime.dataRoot)||!Number.isSafeInteger(runtime.port))return reject(Error('Bundled desktop runtime is invalid.'));
        fs.mkdirSync(runtime.dataRoot,{recursive:true});cwd=runtime.dataRoot;environment.PRODUCER_DESKTOP_DATA_ROOT=runtime.dataRoot;environment.PRODUCER_DESKTOP_PYTHON=runtime.python;
        if(runtime.ffmpeg)environment.PATH=path.dirname(runtime.ffmpeg)+path.delimiter+(environment.PATH||'');
      }else{delete environment.PRODUCER_DESKTOP_DATA_ROOT;delete environment.PRODUCER_DESKTOP_PYTHON;}
      const args=['-B',path.join(runtime.projectRoot,'tools','desktop_backend.py'),action,'--state-path',this.statePath,'--timeout','45'];if(runtime.buildKind==='bundled-runtime')args.push('--port',String(runtime.port));
      const child=spawn(runtime.python,args,{cwd,windowsHide:true,env:environment});
      let output='',settled=false;const timer=setTimeout(()=>{child.kill();reject(Error('Studio startup timed out. Check the desktop logs and retry.'));},75000);
      child.stdout.on('data',data=>{output+=data.toString();if(output.length>65536){child.kill();output='';}});child.stderr.resume();
      child.on('error',()=>{clearTimeout(timer);if(!settled){settled=true;reject(Error('The studio runtime could not start.'));}});
      child.on('close',code=>{clearTimeout(timer);if(settled)return;settled=true;try{const lines=output.trim().split(/\r?\n/);const value=JSON.parse(lines.at(-1));if(code||value.ok===false)throw Error(value.reason||'Studio startup failed');resolve(value);}catch(_){reject(Error('Studio startup failed. The local runtime needs attention.'));}});
    });
  }
  async start(){this.started=await this.command('start');return this.started;}
  async close(){if(this.started)return this.command('stop');}
}
module.exports={Backend};
