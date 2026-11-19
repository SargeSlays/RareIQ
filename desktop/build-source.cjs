'use strict';
// Bundled builds read every application input from one captured Git tree.
const fs=require('node:fs/promises'),path=require('node:path'),{spawnSync}=require('node:child_process'),{createHash}=require('node:crypto');
const TREE=/^(?:[a-f0-9]{40}|[a-f0-9]{64})$/;
const ASSETS=['producer-please.tokens.css','icon-192.png','icon-512.png'];
function git(project,args){
  const result=spawnSync('git',args,{cwd:project,windowsHide:true,maxBuffer:64*1024*1024});
  if(result.status!==0||result.error)throw Error('desktop_source_unavailable');
  return result.stdout;
}
function captureSourceTree(project){
  const tree=git(project,['write-tree']).toString('ascii').trim();
  return validateSourceTree(project,tree);
}
function parseBuildArguments(args){
  let bundled=false,sourceTree=null;
  for(let index=0;index<args.length;index++){
    if(args[index]==='--bundled'&&!bundled){bundled=true;continue;}
    if(args[index]==='--source-tree'&&sourceTree===null&&typeof args[index+1]==='string'&&TREE.test(args[index+1])){sourceTree=args[++index];continue;}
    throw Error('desktop_build_arguments_invalid');
  }
  if(sourceTree!==null&&!bundled)throw Error('desktop_build_arguments_invalid');
  return {bundled,sourceTree};
}
function captureBaseCommit(project){
  const commit=git(project,['rev-parse','--verify','HEAD^{commit}']).toString('ascii').trim();
  if(!TREE.test(commit))throw Error('desktop_source_commit_invalid');
  return commit;
}
function validateSourceTree(project,tree){
  if(typeof tree!=='string'||!TREE.test(tree)||git(project,['cat-file','-t',tree]).toString('ascii').trim()!=='tree')throw Error('desktop_source_tree_invalid');
  return tree;
}
async function stageDesktopSource({project,destination,sourceTree}){
  const tree=validateSourceTree(project,sourceTree),inventory=new Map();
  for(const record of git(project,['ls-tree','-r','-z','--full-tree',tree]).toString('utf8').split('\0')){
    if(!record)continue;const match=/^([0-7]{6}) (blob|tree|commit) ([a-f0-9]+)\t(.+)$/.exec(record);
    if(!match)throw Error('desktop_source_inventory_invalid');inventory.set(match[4],{mode:match[1],type:match[2]});
  }
  const selected=[...inventory.keys()].filter(name=>/^desktop\/[^/]+$/.test(name)&&!['desktop/build.cjs','desktop/build-source.cjs'].includes(name)&&(/\.(?:cjs|js|css|html)$/.test(name)||name==='desktop/package.json')).sort();
  const required=['desktop/main.cjs','desktop/package.json'];
  if(required.some(name=>!selected.includes(name)))throw Error('desktop_source_incomplete');
  for(const asset of ASSETS)selected.push('rareiq/web/static/brand/producer-please-v2/'+asset);
  const files=[];
  for(const name of selected){
    const entry=inventory.get(name);if(!entry||entry.type!=='blob'||!['100644','100755'].includes(entry.mode))throw Error('desktop_source_link_rejected');
    const relative=name.startsWith('desktop/')?name.slice('desktop/'.length):'assets/'+path.posix.basename(name);
    if(/[\\\x00-\x1f\x7f:]/.test(relative)||relative.split('/').some(part=>!part||part==='.'||part==='..'))throw Error('desktop_source_path_invalid');
    const data=git(project,['show',tree+':'+name]),output=path.join(destination,...relative.split('/'));
    await fs.mkdir(path.dirname(output),{recursive:true});await fs.writeFile(output,data,{flag:'wx'});
    files.push({path:name,sha256:createHash('sha256').update(data).digest('hex')});
  }
  return {sourceTree:tree,files};
}
module.exports={captureSourceTree,captureBaseCommit,parseBuildArguments,validateSourceTree,stageDesktopSource};
