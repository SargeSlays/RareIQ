'use strict';
const fs=require('node:fs/promises'),path=require('node:path'),{spawnSync}=require('node:child_process');
async function build(){
  const source=require('./build-source.cjs'),args=source.parseBuildArguments(process.argv.slice(2)),bundled=args.bundled,stamp=new Date().toISOString().replace(/[^0-9]/g,''),root=path.resolve(__dirname,'..'),cache='F:/Caches/ProducerPlease',out=path.join('F:/Apps/ProducerPlease/builds','0.1.0-'+stamp),stage=path.join(cache,'app-stage-'+stamp);
  const sourceTree=bundled?(args.sourceTree?source.validateSourceTree(root,args.sourceTree):source.captureSourceTree(root)):null,baseCommit=bundled?source.captureBaseCommit(root):null;
  await fs.mkdir(stage,{recursive:true});let desktopSource;
  if(bundled)desktopSource={baseCommit,...await source.stageDesktopSource({project:root,destination:stage,sourceTree})};
  else{
    for(const file of await fs.readdir(__dirname)){if(['build.cjs','build-source.cjs'].includes(file)||!(/\.(?:cjs|js|css|html)$/.test(file)||file==='package.json'))continue;const input=path.join(__dirname,file);if((await fs.stat(input)).isFile())await fs.copyFile(input,path.join(stage,file));}
    await fs.mkdir(path.join(stage,'assets'),{recursive:true});for(const file of ['producer-please.tokens.css','icon-192.png','icon-512.png'])await fs.copyFile(path.join(root,'rareiq/web/static/brand/producer-please-v2',file),path.join(stage,'assets',file));
  }
  const assets=path.join(stage,'assets');
  const manifest=JSON.parse(await fs.readFile(path.join(stage,'package.json'),'utf8'));delete manifest.devDependencies;delete manifest.scripts;await fs.writeFile(path.join(stage,'package.json'),JSON.stringify(manifest,null,2));
  const icon=path.join(assets,'app.ico');
  const converted=spawnSync(path.join(root,'.venv','Scripts','python.exe'),['-B','-c',"from PIL import Image;import sys;Image.open(sys.argv[1]).save(sys.argv[2],format='ICO',sizes=[(16,16),(24,24),(32,32),(48,48),(64,64),(128,128),(256,256)])",path.join(assets,'icon-512.png'),icon],{windowsHide:true});if(converted.status!==0)throw Error('Desktop icon conversion failed');
  const packager=require('@electron/packager');const destinations=await packager.packager({dir:stage,name:'ProducerPlease',appCopyright:'Producer, Please',appBundleId:'com.producerplease.studio',executableName:'ProducerPlease',platform:'win32',arch:'x64',icon,electronVersion:'45.3.4',out,overwrite:false,asar:true,prune:true,download:{cacheRoot:path.join(cache,'electron')},win32metadata:{CompanyName:'Producer, Please',FileDescription:'Producer, Please desktop production studio',ProductName:'Producer, Please',InternalName:'ProducerPlease',OriginalFilename:'ProducerPlease.exe'}});
  const executable=path.join(destinations[0],'ProducerPlease.exe');const ffmpeg=spawnSync('where.exe',['ffmpeg'],{encoding:'utf8',windowsHide:true}).stdout.trim().split(/\r?\n/)[0];
  if(bundled){
    await fs.writeFile(path.join(destinations[0],'resources','desktop-source.json'),JSON.stringify(desktopSource,null,2)+'\n',{flag:'wx'});
    const result=spawnSync(path.join(root,'.venv/Scripts/python.exe'),['-B',path.join(root,'tools/package_desktop_runtime.py'),path.join(destinations[0],'resources'),'--source-tree',sourceTree],{cwd:root,encoding:'utf8',windowsHide:true,maxBuffer:1024*1024});
    if(result.status!==0){console.error(result.stderr);throw Error('Bundled runtime build failed. The current installed build was preserved.');}
    const receipt={executable,...JSON.parse(result.stdout.trim().split(/\r?\n/).at(-1))};await fs.writeFile('F:/Apps/ProducerPlease/latest-bundled-build.json',JSON.stringify(receipt,null,2));console.log(JSON.stringify(receipt));return;
  }
  const pythonPackages=path.join(destinations[0],'resources','python-packages');await fs.cp('F:/Caches/ProducerPlease/python-packages',pythonPackages,{recursive:true,errorOnExist:true});
  const encoderWorker=path.join(destinations[0],'resources','encoder_worker.py');await fs.copyFile(path.join(__dirname,'encoder_worker.py'),encoderWorker);
  const sharedEncoderWorker=path.join(destinations[0],'resources','shared_encoder_worker.py');await fs.copyFile(path.join(__dirname,'shared_encoder_worker.py'),sharedEncoderWorker);
  await fs.writeFile(path.join(destinations[0],'resources','runtime.json'),JSON.stringify({projectRoot:root,python:path.join(root,'.venv','Scripts','python.exe'),encoderWorker,sharedEncoderWorker,pythonPackages,ffmpeg,buildKind:'local-development-runtime'},null,2));
  await fs.writeFile('F:/Apps/ProducerPlease/latest-build.json',JSON.stringify({executable,buildKind:'local-development-runtime',runtimeBundled:false},null,2));
  console.log(JSON.stringify({executable,buildKind:'local-development-runtime',runtimeBundled:false}));
}
build().catch(error=>{console.error(error.message);process.exitCode=1;});
