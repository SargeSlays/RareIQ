'use strict';
const {spawn}=require('node:child_process'),path=require('node:path'),fs=require('node:fs');
class Backend{
  constructor(runtime,statePath){this.runtime=runtime;this.statePath=statePath;this.started=null;}
  command(action){
    const runtime=this.runtime;
    if(!runtime||!path.isAbsolute(runtime.projectRoot)||!path.isAbsolute(runtime.python)||!fs.existsSync(runtime.python))return Promise.reject(Error('Studio runtime is missing. Repair the local desktop installation.'));
    return new Promise((resolve,reject)=>{
      const child=spawn(runtime.python,['-B',path.join(runtime.projectRoot,'tools','desktop_backend.py'),action,'--state-path',this.statePath,'--timeout','45'],{cwd:runtime.projectRoot,windowsHide:true,env:{...process.env,PRODUCER_DESKTOP:'1',PYTHONDONTWRITEBYTECODE:'1'}});
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
