'use strict';
const path=require('node:path'),fs=require('node:fs');
function resolveRuntime(value,resources,profile,{port}={}){
  if(!value||typeof value!=='object')throw Error('Studio runtime manifest is invalid.');
  if(value.buildKind!=='bundled-runtime')return value;
  const base=fs.realpathSync(resources);
  const inside=(relative,directory=false)=>{
    if(typeof relative!=='string'||!relative||path.isAbsolute(relative)||relative.split(/[\\/]/).some(part=>part==='..'||part===''))throw Error('Bundled runtime path is invalid.');
    const resolved=fs.realpathSync(path.resolve(base,relative)),difference=path.relative(base,resolved);
    if(!difference||difference==='..'||difference.startsWith('..'+path.sep)||path.isAbsolute(difference)||fs.statSync(resolved).isDirectory()!==directory)throw Error('Bundled runtime is incomplete.');
    return resolved;
  };
  const backendPort=port??value.port??8765;if(!Number.isSafeInteger(backendPort)||backendPort<1024||backendPort>65535)throw Error('Studio port is invalid.');
  if(!path.isAbsolute(profile))throw Error('Desktop data folder must be absolute.');
  return {...value,projectRoot:inside(value.projectRoot,true),python:inside(value.python),encoderWorker:inside(value.encoderWorker),...(value.sharedEncoderWorker?{sharedEncoderWorker:inside(value.sharedEncoderWorker)}:{}),pythonPackages:inside(value.pythonPackages,true),ffmpeg:value.ffmpeg?inside(value.ffmpeg):null,dataRoot:path.join(profile,'backend'),port:backendPort};
}
module.exports={resolveRuntime};
