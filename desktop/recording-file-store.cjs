'use strict';
// Main-only preflight. The worker repeats these checks and owns exclusive creation.
const fs=require('node:fs/promises'),path=require('node:path');
const MINIMUM_FREE_BYTES=256*1024*1024;
const failure=code=>Object.assign(Error(code),{code});
async function inspectRecordingPath(value,{minimumFreeBytes=MINIMUM_FREE_BYTES}={}){
  if(typeof value!=='string'||value.length>2048||!path.isAbsolute(value)||path.extname(value).toLowerCase()!=='.mkv'||/[\x00-\x1f]/.test(value)||!Number.isSafeInteger(minimumFreeBytes)||minimumFreeBytes<MINIMUM_FREE_BYTES)throw failure('invalid_recording_file');
  const resolved=path.resolve(value);
  try{
    try{await fs.lstat(resolved);throw failure('recording_file_exists');}catch(error){if(error.code!=='ENOENT')throw error;}
    let current=path.dirname(resolved);
    while(true){const info=await fs.lstat(current);if(!info.isDirectory()||info.isSymbolicLink())throw failure('invalid_recording_file');const real=await fs.realpath(current);if(path.resolve(real).toLowerCase()!==path.resolve(current).toLowerCase())throw failure('invalid_recording_file');const parent=path.dirname(current);if(parent===current)break;current=parent;}
    const space=await fs.statfs(path.dirname(resolved));if(Number(space.bavail)*Number(space.bsize)<minimumFreeBytes)throw failure('insufficient_recording_space');
  }catch(error){if(['invalid_recording_file','recording_file_exists','insufficient_recording_space'].includes(error.code))throw error;throw failure('recording_storage_unavailable');}
  return {path:resolved,minimumFreeBytes};
}
module.exports={inspectRecordingPath,MINIMUM_FREE_BYTES};
