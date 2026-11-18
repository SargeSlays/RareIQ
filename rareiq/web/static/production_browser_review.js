/* Explicit, pre-show visual review of the very frame that will become Program. */
(function(host){
  'use strict';
  function mount({view,document=host.document,fetch:request=host.fetch.bind(host)}={}){
    if(!view||!document)return null;
    const panel=document.createElement('section');panel.className='browser-output-review';panel.hidden=true;panel.setAttribute('aria-label','Browser source review');
    panel.innerHTML='<h1>Review this output</h1><p>Preparation view changes this output layout. Close it before broadcasting. Pages are silent. Approve only a visible, working page; replace blank or blocked pages.</p><label>Browser source<select aria-label="Browser source to review"></select></label><div><button type="button" data-browser-approve>I can see this page</button><button type="button" data-browser-reload>Reload page</button><button type="button" data-browser-finish>Close review</button></div><p role="status" aria-live="polite"></p>';
    document.body.append(panel);const one=s=>panel.querySelector(s),select=one('select'),approve=one('[data-browser-approve]'),reload=one('[data-browser-reload]'),note=one('[role=status]');let open=false,busy=false,closed=false,signature='',selected=null,token=null,lastReport='',warning='';
    function tell(message=warning,finished=false){const needsReview=view._allTiles().some(tile=>tile.source.kind==='browser'&&tile.browser?.snapshot().phase!=='visual_reviewed'),status={type:'producer-browser-review',open,needsReview,note:message,finished},key=JSON.stringify(status);if(key!==lastReport&&host.parent!==host){lastReport=key;host.parent.postMessage(status,host.location.origin);}}
    function tiles(){return [...(view.current?.tiles||[]),...view.preloads.values()].filter(tile=>tile.source.kind==='browser');}
    function render(){
      if(closed)return;const available=tiles(),key=available.map(tile=>tile.id).join(',');
      if(signature!==key){signature=key;select.replaceChildren();for(const tile of available){const option=document.createElement('option');option.value=tile.id;option.textContent=tile.browserName||'Browser '+(available.indexOf(tile)+1);select.append(option);}if(available.some(tile=>tile.id===selected))select.value=selected;}
      selected=select.value||null;const tile=available.find(tile=>tile.id===selected),state=tile?.browser?.snapshot();token=state?.reviewToken||null;
      for(const item of available)item.node.dataset.browserReviewSelected=String(open&&item===tile);
      approve.disabled=!open||state?.phase!=='loaded_unverified';reload.disabled=!tile?.browser;
      note.textContent=!available.length?'Choose a browser source in Preview or Program. Reviews are available only before broadcasting.':tile?.browserFailed?'This page is unavailable, or this browser cannot preserve it through Take. Use current Chrome or Edge.':state?.phase==='visual_reviewed'?'Reviewed for this output. Close review to enable Take.':state?.phase==='loaded_unverified'?'Check the picture below. A loaded page may still be blank or blocked.': 'Loading page. Take stays blocked until it is reviewed in every connected output.';tell();
    }
    function finish(){if(!open)return;open=false;warning='';panel.hidden=true;view.browserReviewOpen=false;delete view.container.dataset.browserReviewing;for(const tile of tiles())delete tile.node.dataset.browserReviewSelected;view.refresh();tell();}
    async function begin(){
      if(closed||busy||open)return;busy=true;warning='';
      try{
        for(let attempt=0;!view.state&&!closed&&attempt<30;attempt++)await new Promise(resolve=>host.setTimeout(resolve,100));
        if(closed)return;if(!view.state)throw Error('Wait for the output to connect, then retry review.');
        if(!tiles().length){tell('',true);return;}
        const responses=await Promise.all(['/api/production/session','/api/production/obs'].map(url=>request(url,{credentials:'same-origin',cache:'no-store'})));
        if(responses.some(r=>!r.ok))throw Error('Cannot confirm the studio is idle. Review is available before the show.');
        const [a,b]=await Promise.all(responses.map(r=>r.json())),session=a.session,obs=b.obs;
        if(a.native_encoding?.active===true||!session||!obs||session.active!==false||session.recording?.active!==false||obs.streaming!==false||obs.recording!==false)throw Error('End the show, stream and recording before changing this output to review mode.');
        if(closed)return;
        if(!tiles().length){tell('',true);return;}open=true;panel.hidden=false;view.browserReviewOpen=true;view.container.dataset.browserReviewing='true';view.refresh();render();select.focus();tell();
      }catch(error){warning=error.message||'Review is unavailable.';tell();}finally{busy=false;}
    }
    select.addEventListener('change',()=>{selected=select.value;render();});approve.addEventListener('click',()=>{const tile=tiles().find(tile=>tile.id===selected);tile?.browser?.review(token);view.refresh();render();});reload.addEventListener('click',()=>{tiles().find(tile=>tile.id===selected)?.browser?.reload();view.refresh();render();});one('[data-browser-finish]').addEventListener('click',finish);
    panel.addEventListener('keydown',event=>{if(event.key==='Escape')finish();});const timer=host.setInterval(render,200);render();
    return {open:begin,close(){finish();closed=true;host.clearInterval(timer);panel.remove();}};
  }
  if(typeof module==='object'&&module.exports)module.exports={mount};else host.ProducerBrowserReview={mount};
})(typeof window==='undefined'?globalThis:window);
