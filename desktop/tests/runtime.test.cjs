const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),os=require('node:os');
const {resolveRuntime}=require('../runtime.cjs');
function fixture(t){
  const parent=path.resolve(os.tmpdir());
  const base=fs.mkdtempSync(path.join(parent,'producer-runtime-'));
  t.after(()=>{assert.equal(path.dirname(path.resolve(base)),parent);fs.rmSync(base,{recursive:true,force:true});});
  for(const name of ['backend','python/Lib/site-packages'])fs.mkdirSync(path.join(base,name),{recursive:true});
  for(const name of ['python/python.exe','encoder_worker.py'])fs.writeFileSync(path.join(base,name),'synthetic');
  return {base,profile:path.join(base,'profile'),manifest:{buildKind:'bundled-runtime',projectRoot:'backend',python:'python/python.exe',encoderWorker:'encoder_worker.py',pythonPackages:'python/Lib/site-packages'}};
}
test('bundled paths resolve against app resources with an independent writable profile',t=>{const f=fixture(t),value=resolveRuntime(f.manifest,f.base,f.profile,{port:8767});assert.equal(value.python,path.join(f.base,'python/python.exe'));assert.equal(value.dataRoot,path.join(f.profile,'backend'));assert.equal(value.port,8767);assert.equal(value.ffmpeg,null);});
test('bundled manifest rejects missing files, escapes, invalid ports and relative data',t=>{const f=fixture(t);for(const relative of ['../outside.exe','python/missing.exe',path.join(f.base,'python/python.exe')])assert.throws(()=>resolveRuntime({...f.manifest,python:relative},f.base,f.profile));assert.throws(()=>resolveRuntime(f.manifest,f.base,f.profile,{port:99999}));assert.throws(()=>resolveRuntime(f.manifest,f.base,'relative'));});
test('existing local development runtime keeps its explicit paths',()=>{const original={buildKind:'local-development-runtime',projectRoot:'original',python:'existing'};assert.equal(resolveRuntime(original,'unused','unused'),original);});
test('a resource junction resolving exactly to its parent is rejected',t=>{const f=fixture(t),realpath=fs.realpathSync;fs.realpathSync=value=>path.resolve(value)===path.join(f.base,'backend')?path.dirname(f.base):realpath(value);try{assert.throws(()=>resolveRuntime(f.manifest,f.base,f.profile),/incomplete/);}finally{fs.realpathSync=realpath;}});

test('shared worker resolves inside packaged resources and rejects missing or escaped helpers',t=>{
  const f=fixture(t);fs.writeFileSync(path.join(f.base,'shared_encoder_worker.py'),'synthetic');
  assert.equal(resolveRuntime({...f.manifest,sharedEncoderWorker:'shared_encoder_worker.py'},f.base,f.profile).sharedEncoderWorker,path.join(f.base,'shared_encoder_worker.py'));
  for(const name of ['missing.py','../outside.py',path.join(f.base,'shared_encoder_worker.py')])assert.throws(()=>resolveRuntime({...f.manifest,sharedEncoderWorker:name},f.base,f.profile));
});

test('desktop UI and launch sources are valid UTF8 before packaging',()=>{
  const folder=path.resolve(__dirname,'..'),decoder=new TextDecoder('utf-8',{fatal:true});
  for(const name of fs.readdirSync(folder).filter(n=>/\.(cjs|js|css|html)$/.test(n)))assert.doesNotThrow(()=>decoder.decode(fs.readFileSync(path.join(folder,name))),name+' must remain valid UTF8');
});
