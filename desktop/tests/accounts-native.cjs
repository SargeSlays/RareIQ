/* Actual EXE/preload/IPC/UI against the preverified synthetic viewer fixture only. */
'use strict';
const assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path');
const {_electron}=require('playwright');
const origin='http://127.0.0.1:8770';
const evidenceArg=process.argv[2],executable=process.argv[3];
if(!evidenceArg||!path.isAbsolute(evidenceArg)||!executable||!path.isAbsolute(executable))throw Error('Supply absolute evidence directory and executable');
const evidence=path.resolve(evidenceArg),diagnose=process.argv.includes('--diagnose');
const api=async route=>{const response=await fetch(origin+route);assert.equal(response.ok,true);return response.json();};

async function main(){
  const marker=await api('/__qa__/viewer-chat-marker'),guest=await api('/__qa__/guest-fixture');
  assert.equal(marker.synthetic_viewer_chat_fixture,true);assert.equal(marker.provider_network,false);
  assert.equal(marker.hardware,false);assert.equal(marker.real_credentials,false);assert.equal(guest.isolated_guest_fixture,true);
  assert.ok(path.isAbsolute(executable)&&fs.statSync(executable).isFile());
  assert.equal(path.parse(evidence).root.toLowerCase(),'f:\\');fs.mkdirSync(evidence,{recursive:false});
  const before=await api('/api/production/switcher'),profile=path.join(evidence,'profile');
  let app;const result={complete:false,syntheticOnly:true,realCredentials:false,providerGrant:false,
    externalOpen:false,physicalCapture:false,programMutation:false,fixtureServerOwned:false};
  try{
    app=await _electron.launch({executablePath:executable,env:{...process.env,
      PRODUCER_DESKTOP_QA_ORIGIN:origin,PRODUCER_DESKTOP_QA_PROFILE:profile,ELECTRON_ENABLE_LOGGING:'0'}});
    app.context().setDefaultTimeout(20000);
    result.guard=await app.evaluate(({app,BrowserWindow,shell})=>{
      globalThis.nativeAccountExternalAttempts=0;
      shell.openExternal=async()=>{globalThis.nativeAccountExternalAttempts++;throw Error('External opening forbidden in this synthetic test');};
      const install=contents=>{
        contents.session.setPermissionCheckHandler(()=>false);
        contents.session.setPermissionRequestHandler((_contents,_permission,reply)=>reply(false));
        contents.session.setDisplayMediaRequestHandler((_request,reply)=>reply(null));
        contents.session.webRequest.onBeforeRequest((details,reply)=>{
          const url=new URL(details.url),local=url.origin==='http://127.0.0.1:8770'||url.origin==='ws://127.0.0.1:8770';
          const resource=['file:','data:','blob:','devtools:'].includes(url.protocol);
          reply({cancel:!resource&&(!local||!['GET','HEAD'].includes(details.method))});
        });
      };
      app.on('web-contents-created',(_event,contents)=>install(contents));
      for(const window of BrowserWindow.getAllWindows())install(window.webContents);
      return {existingWindows:BrowserWindow.getAllWindows().length,externalOpenBlocked:true,physicalPermissionsDenied:true,rendererMutationsBlocked:true};
    });
    const studio=await app.firstWindow();await studio.waitForURL(origin+'/control?workspace=studio&desktop=1');
    await studio.locator('#instantSplash').waitFor({state:'hidden'});await studio.locator('[data-studio-docks="ready"]').waitFor();
    assert.equal(await studio.evaluate(()=>typeof producerDesktop.authorizeAccount),'function');
    assert.equal(await studio.evaluate(()=>typeof window.require),'undefined');
    assert.equal(await studio.evaluate(()=>typeof window.process),'undefined');
    const invalid=await studio.evaluate(async()=>{
      const values=[null,{},'invalid',{platform:'twitch',flowId:'a'.repeat(32)},
        {platform:'youtube',flowId:'not-a-flow'},{platform:'youtube',flowId:'a'.repeat(32),authorization_url:'https://untrusted.example'}];
      return Promise.all(values.map(value=>producerDesktop.authorizeAccount(value)));
    });
    assert.ok(invalid.every(value=>value.ok===false&&value.reason==='invalid_authorization_request'));
    const stale=await studio.evaluate(()=>producerDesktop.authorizeAccount({platform:'youtube',flowId:'a'.repeat(32)}));
    assert.deepEqual(stale,{ok:false,reason:'authorization_flow_unavailable'});
    Object.assign(result,{rendererBridgePresent:true,invalidPayloadsDenied:invalid.length,staleFlowDenied:true});
    await studio.getByRole('button',{name:'Viewer chat',exact:true}).click();
    const viewer=studio.locator('.production-viewer-chat');await viewer.waitFor({state:'visible'});
    const connections=viewer.locator('.viewer-chat-connections > summary');
    if(diagnose){
      await connections.scrollIntoViewIfNeeded();
      result.layout=await connections.evaluate(summary=>{
        const box=node=>{if(!node)return null;const rect=node.getBoundingClientRect(),style=getComputedStyle(node);
          return {tag:node.tagName,class:node.className,rect:{x:rect.x,y:rect.y,width:rect.width,height:rect.height},position:style.position,overflow:style.overflow,zIndex:style.zIndex};};
        const rect=summary.getBoundingClientRect(),point={x:rect.x+rect.width/2,y:rect.y+rect.height/2};
        return {viewport:{width:innerWidth,height:innerHeight,devicePixelRatio},summary:box(summary),point,
          interceptor:box(document.elementFromPoint(point.x,point.y)),
          ancestors:Array.from((function*(node){while(node){yield node;node=node.parentElement;}})(summary)).map(box),
          dockRegions:Array.from(document.querySelectorAll('.studio-dock-region,.workspace-readiness,.greenroom-heading')).map(box)};
      });
      await studio.screenshot({path:path.join(evidence,'native-pointer-layout.png')});
      result.externalAttempts=await app.evaluate(()=>globalThis.nativeAccountExternalAttempts);
      result.programGenerationUnchanged=(await api('/api/production/switcher')).generation===before.generation;
      result.diagnosticComplete=true;return;
    }
    const placement=await studio.evaluate(()=>{
      const right=document.querySelector('.studio-dock-right').getBoundingClientRect(),bottom=document.querySelector('.studio-dock-bottom').getBoundingClientRect();
      return {width:innerWidth,rightBottom:right.bottom,bottomTop:bottom.top};
    });
    if(placement.width>1100)assert.ok(placement.bottomTop>=placement.rightBottom-1,'full-width backstage starts below the right-side tools');
    result.nonOverlappingDocks=true;
    await connections.click();
    const manage=viewer.locator('[data-viewer-accounts]');await manage.click();
    const dialog=studio.locator('.platform-accounts-dialog[open]');await dialog.waitFor();
    await dialog.locator('[data-account-platform="twitch"] [data-accounts-begin]').waitFor({state:'visible'});
    assert.equal(await dialog.locator('[data-account-platform]').count(),3);
    assert.equal(await dialog.locator('input,textarea').count(),0);
    assert.equal(await dialog.evaluate(node=>node.scrollWidth<=node.clientWidth+1),true);
    await studio.screenshot({path:path.join(evidence,'native-manage-accounts.png')});
    await dialog.locator('[data-accounts-close]').click();await dialog.waitFor({state:'hidden'});
    assert.equal(await manage.evaluate(node=>node===node.ownerDocument.activeElement),true);
    result.externalAttempts=await app.evaluate(()=>globalThis.nativeAccountExternalAttempts);assert.equal(result.externalAttempts,0);
    assert.equal((await api('/api/production/switcher')).generation,before.generation);
    Object.assign(result,{complete:true,actualExecutable:executable,rendererBridgePresent:true,invalidPayloadsDenied:invalid.length,
      staleFlowDenied:true,viewerChatVisible:true,manageAccountsVisible:true,closeRestoresFocus:true,programGenerationUnchanged:true});
  }catch(error){result.error=String(error.message).slice(0,2000);throw error;}
  finally{
    fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));
    if(app){const child=app.process();await app.close().catch(()=>{});result.ownedNativeAppClosed=child.exitCode!==null;
      fs.writeFileSync(path.join(evidence,'results.json'),JSON.stringify(result,null,2));}
  }
  console.log(JSON.stringify(result));
}
main().catch(error=>{console.error(String(error.message).slice(0,2000));process.exitCode=1;});
