'use strict';
const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs/promises'),path=require('node:path'),os=require('node:os'),{spawnSync}=require('node:child_process'),{createHash}=require('node:crypto');
const {captureSourceTree,captureBaseCommit,parseBuildArguments,validateSourceTree,stageDesktopSource}=require('../build-source.cjs');
function git(project,args,input){const result=spawnSync('git',args,{cwd:project,input,encoding:'utf8',windowsHide:true});assert.equal(result.status,0,result.stderr);return result.stdout.trim();}
async function fixture(t){
  const parent=path.resolve(os.tmpdir()),root=await fs.mkdtemp(path.join(parent,'producer-build-source-')),project=path.join(root,'project'),destination=path.join(root,'stage');
  t.after(async()=>{assert.equal(path.dirname(path.resolve(root)),parent);await fs.rm(root,{recursive:true,force:true});});await fs.mkdir(project);git(project,['init','-q']);
  const files={'desktop/main.cjs':'immutable desktop UI','desktop/settings.html':'immutable settings','desktop/package.json':'{"name":"synthetic","version":"1.0.0"}','desktop/build.cjs':'never ship build driver','desktop/build-source.cjs':'never ship build helper','desktop/tests/private.cjs':'never ship tests','desktop/encoder_worker.py':'worker handled by Python packager','rareiq/web/static/brand/producer-please-v2/producer-please.tokens.css':'immutable theme','rareiq/web/static/brand/producer-please-v2/icon-192.png':Buffer.from([0,255,1,2]),'rareiq/web/static/brand/producer-please-v2/icon-512.png':Buffer.from([3,254,4,5])};
  for(const [name,value] of Object.entries(files)){const output=path.join(project,name);await fs.mkdir(path.dirname(output),{recursive:true});await fs.writeFile(output,value);}git(project,['add','--all']);return {project,destination,files};
}
test('one captured tree stages indexed desktop modules and binary brand assets despite later index and working-copy drift',async t=>{
  const f=await fixture(t),tree=captureSourceTree(f.project);await fs.writeFile(path.join(f.project,'desktop/main.cjs'),'later indexed UI');git(f.project,['add','desktop/main.cjs']);await fs.writeFile(path.join(f.project,'desktop/settings.html'),'dirty settings');await fs.writeFile(path.join(f.project,'desktop/untracked.js'),'do not package');
  const result=await stageDesktopSource({...f,sourceTree:tree});assert.equal(result.sourceTree,tree);assert.equal(await fs.readFile(path.join(f.destination,'main.cjs'),'utf8'),'immutable desktop UI');assert.equal(await fs.readFile(path.join(f.destination,'settings.html'),'utf8'),'immutable settings');assert.deepEqual(await fs.readFile(path.join(f.destination,'assets/icon-192.png')),f.files['rareiq/web/static/brand/producer-please-v2/icon-192.png']);
  const listed=await fs.readdir(f.destination);for(const name of ['build.cjs','build-source.cjs','untracked.js','encoder_worker.py','tests'])assert.equal(listed.includes(name),false);
  for(const item of result.files)assert.equal(item.sha256,createHash('sha256').update(f.files[item.path]).digest('hex'));assert.notEqual(captureSourceTree(f.project),tree);
});
test('source inputs require an actual immutable tree rather than a branch, blob or injected argument',async t=>{
  const f=await fixture(t),blob=git(f.project,['hash-object','-w','--stdin'],'not a tree');for(const value of ['HEAD','--all','a'.repeat(39),null,blob])assert.throws(()=>validateSourceTree(f.project,value));
});
test('build source override accepts only a single explicit tree for a bundled build, with no source-folder override',()=>{
  const tree='a'.repeat(40);assert.deepEqual(parseBuildArguments([]),{bundled:false,sourceTree:null});assert.deepEqual(parseBuildArguments(['--bundled']),{bundled:true,sourceTree:null});assert.deepEqual(parseBuildArguments(['--bundled','--source-tree',tree]),{bundled:true,sourceTree:tree});
  for(const args of [['--source-tree',tree],['--bundled','--source-tree','HEAD'],['--bundled','--source-tree'],['--bundled','--source-tree',tree,'--source-tree',tree],['--bundled','--root','F:/arbitrary'],['--bundled','--bundled']])assert.throws(()=>parseBuildArguments(args),/desktop_build_arguments_invalid/);
});
test('candidate provenance captures the current base commit independently from its source overlay tree',async t=>{
  const f=await fixture(t),tree=captureSourceTree(f.project),commit=git(f.project,['-c','user.name=Synthetic fixture','-c','user.email=fixture@invalid','commit-tree',tree],'Synthetic base\n');git(f.project,['update-ref','HEAD',commit]);assert.equal(captureBaseCommit(f.project),commit);
  await fs.writeFile(path.join(f.project,'desktop/main.cjs'),'uncommitted tested overlay');git(f.project,['add','desktop/main.cjs']);assert.notEqual(captureSourceTree(f.project),tree);assert.equal(captureBaseCommit(f.project),commit);
});
test('index symlinks are rejected without reading their working-copy target',async t=>{
  const f=await fixture(t),blob=git(f.project,['hash-object','-w','--stdin'],'../../private');git(f.project,['update-index','--add','--cacheinfo','120000',blob,'desktop/linked.js']);await assert.rejects(stageDesktopSource({...f,sourceTree:captureSourceTree(f.project)}),/desktop_source_link_rejected/);
});
test('missing required staged UI cannot fall back to dirty or untracked working files',async t=>{
  const f=await fixture(t);git(f.project,['rm','--cached','desktop/main.cjs']);await assert.rejects(stageDesktopSource({...f,sourceTree:captureSourceTree(f.project)}),/desktop_source_incomplete/);
});
test('bundled build driver passes its captured source tree to the backend packager while local builds retain direct copying',async()=>{
  const source=await fs.readFile(path.join(__dirname,'../build.cjs'),'utf8');assert.ok(source.includes("source.captureSourceTree(root)"));assert.ok(source.includes("source.stageDesktopSource({project:root,destination:stage,sourceTree})"));assert.ok(source.includes("'--source-tree',sourceTree"));assert.ok(source.indexOf('source.captureSourceTree(root)')<source.indexOf('await fs.mkdir(stage'));assert.ok(source.includes("resources','desktop-source.json"));assert.ok(source.includes("await fs.copyFile(input,path.join(stage,file))"));
});
