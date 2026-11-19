const test=require('node:test'),assert=require('node:assert/strict'),fs=require('node:fs'),path=require('node:path'),vm=require('node:vm');
const source=fs.readFileSync(path.resolve(__dirname,'../../rareiq/web/static/studiox.js'),'utf8');
const code=source.slice(source.indexOf('async function openPreviewSceneEditor('),source.indexOf('async function takeProductionScene('));
const id='a'.repeat(64),image='image:11111111-1111-4111-8111-111111111111';
function fixture(){
 const f={calls:[],opened:[],events:[],focus:0,scroll:0,state:{generation:4,preview_revision:7,preview_slot:2,program_slot:1,preview_layout:'custom',preview_composition_id:id,preview_sources:[image],program_sources:['camera:1'],program_layout:'grid',preview_layers:{[image]:{x:.2,y:.1,width:.7,height:.8}},program_layers:{},transition:'fade',duration_ms:500}};
 const form={hidden:false,scrollIntoView:()=>f.scroll++},nodes={productionSceneEditor:form,productionSceneName:{focus:()=>f.focus++}},context=vm.createContext({window:{},productionScenes:[],api:async(url,options)=>{f.calls.push({url,options});return f.state;},openProductionSceneEditor:value=>f.opened.push(value),document:{querySelector:()=>({_studioDocks:{showTool:name=>{f.dock=name;return true;}}})},$:name=>nodes[name],renderProductionSwitcher:value=>{f.rendered=value;},logProductionEvent:(...args)=>f.events.push(args),notify:(...args)=>{f.notice=args;}});
 vm.runInContext(code,context);return Object.assign(f,{context,form});
}
test('Create scene from reviewed Preview opens a scene draft without a save or Take',async()=>{
 const f=fixture(),result=await f.context.window.ProducerLayerScenes.savePreview({compositionId:id});assert.equal(result.opened,true);assert.equal(result.programChanged,false);assert.equal(f.calls.length,1);assert.equal(f.calls[0].url,'/api/production/switcher');assert.equal(f.calls[0].options,undefined);assert.equal(f.opened[0].layout,'custom');assert.equal(f.opened[0].program_sources[0],image);assert.equal(f.opened[0].layers[image].x,.2);assert.equal(f.opened[0].preview_sources[0],'camera:1');assert.equal(f.opened[0].preview_layout,'grid');assert.equal(f.dock,'production-scenes');assert.equal(f.focus,1);
});
test('stale Preview geometry and invalid identities cannot open a scene for a different picture',async()=>{
 for(const change of [{preview_composition_id:'b'.repeat(64)},{preview_layout:'grid'}]){const f=fixture();Object.assign(f.state,change);await assert.rejects(f.context.window.ProducerLayerScenes.savePreview({compositionId:id}),/Preview changed/);assert.equal(f.opened.length,0);}
 const f=fixture();await assert.rejects(f.context.window.ProducerLayerScenes.savePreview({compositionId:'invalid'}),/Apply/);assert.equal(f.calls.length,0);
});
test('custom scene Preview uses fresh revisions and never promotes Program or starts scene audio actions',async()=>{
 const f=fixture(),scene={id:'saved',name:'Saved layout',layout:'custom',program_sources:[image],layers:{[image]:{x:.3}},spotify_action:'play',soundboard_action:'stop'};await f.context.stageProductionScenePreview(scene);assert.equal(f.calls.length,2);assert.equal(f.calls[1].url,'/api/production/switcher/preview');const payload=JSON.parse(f.calls[1].options.body);assert.equal(payload.expected_generation,4);assert.equal(payload.expected_preview_revision,7);assert.equal(payload.layers[image].x,.3);assert.ok(f.calls.every(item=>!item.url.endsWith('/take')));assert.match(f.notice[1],/Program is unchanged/);
});
