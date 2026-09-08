(function(root){
  "use strict";
  const RESTRICTED=new Set(["SCRIPT","STYLE","LINK","META","BASE","IFRAME","OBJECT","EMBED","CANVAS","VIDEO","AUDIO","IMG","IMAGE","FOREIGNOBJECT","SOURCE"]);
  function restricted(tag,type="",identity=""){
    return RESTRICTED.has(String(tag).toUpperCase())||["password","file"].includes(type.toLowerCase())||/password|secret|token|stream.?key|api.?key|authorization/i.test(identity);
  }
  function copyAttribute(tag,name){
    return !name.startsWith("on")&&!["src","srcset","srcdoc","autofocus","action","formaction"].includes(name)&&(name!=="value"||["OPTION","BUTTON"].includes(tag));
  }
  function create({status=()=>{},returned=()=>{}}={}){
    const ownerDocument=root.document,windows=new Map(),session=Date.now().toString(36);
    function open(id,title,panel){
      const existing=windows.get(id);
      if(existing&&!existing.popup.closed){existing.popup.focus();return true;}
      let popup;try{popup=root.open("",`producer-tool-${session}-${id}`,"popup,width=740,height=760,resizable=yes,scrollbars=yes");}catch{}
      if(!popup){status("The browser blocked the tool window. Allow popups for this studio and try again.");return false;}
      const doc=popup.document,html=doc.documentElement;
      doc.head.replaceChildren();doc.body.replaceChildren();doc.title=`${title} · Producer, Please`;
      const node=(tag,text)=>{const e=doc.createElement(tag);if(text)e.textContent=text;return e;};
      const csp=node("meta");csp.httpEquiv="Content-Security-Policy";
      csp.content="default-src 'none'; style-src 'self' 'unsafe-inline'; font-src 'self' data:; img-src 'self' data:; form-action 'none'; base-uri 'self'";doc.head.append(csp);
      const base=node("base");base.href=root.location.href;doc.head.append(base);
      for(const sheet of ownerDocument.querySelectorAll('link[rel="stylesheet"]')){
        if(new URL(sheet.href,root.location.href).origin!==root.location.origin)continue;
        const link=node("link");link.rel="stylesheet";link.href=sheet.href;doc.head.append(link);
      }
      const owner='html[data-theme] body.pp-shell.studiox-ui4.studiox-premium.studiox-command-deck.pp-tool-window[data-operator-layout="v2"][data-studiox-visual-system="unified"]';
      const style=node("style");style.textContent=`
        ${owner} { box-sizing:border-box!important; width:100%!important; max-width:none!important; display:block!important; margin:0!important; padding:14px!important; overflow:auto!important; height:auto!important; min-height:100vh!important; background:var(--pp-bg)!important; color:var(--pp-text)!important; }
        ${owner} .pp-window-toolbar { display:flex; align-items:center; flex-wrap:wrap; gap:10px; margin-bottom:12px; }
        ${owner} .pp-window-toolbar img { width:208px; height:59px; object-fit:contain; margin-right:auto; }
        ${owner} .pp-window-toolbar button { padding:9px 12px; color:var(--pp-text); background:var(--pp-surface-raised); border:1px solid var(--pp-border); border-radius:6px; cursor:pointer; }
        ${owner} .pp-window-notice { color:var(--pp-text-muted); font-size:13px; margin:8px 0 14px; }
        ${owner} .pp-window-content { display:block!important; width:100%!important; max-width:none!important; height:auto!important; padding:0!important; overflow:visible!important; }
        ${owner} .studio-dock-tool { width:100%!important; max-width:none!important; height:auto!important; max-height:none!important; resize:none!important; overflow:visible!important; }
        ${owner} .pp-window-placeholder { display:block; padding:12px; border:1px dashed var(--pp-border); color:var(--pp-text-muted); font-size:13px; }
        .pp-window-content[inert] { opacity:.5; }
      `;doc.head.append(style);
      const toolbar=node("header"),logo=node("img"),back=node("button","Return to main studio"),close=node("button","Close window");toolbar.className="pp-window-toolbar";
      logo.alt="Producer, Please";back.type=close.type="button";
      back.addEventListener("click",()=>{root.focus();returned(id);});close.addEventListener("click",()=>popup.close());toolbar.append(logo,back,close);
      const heading=node("h1",title),notice=node("p","Connected to the main studio. Previews, file imports and protected fields stay there."),host=node("section"),wrapper=node("div");
      notice.className="pp-window-notice";notice.setAttribute("role","status");
      host.className="workspace studiox-app-workspace--broadcast active pp-window-content";host.dataset.workspace="broadcast";
      wrapper.className="studio-dock-tool";host.append(wrapper);doc.body.append(toolbar,heading,notice,host);
      const copies=new WeakMap(),originals=new WeakMap(),edits=new Map();let stopped=false,queued=false,timer;
      function theme(){
        html.dataset.theme=ownerDocument.documentElement.dataset.theme||"dark";html.dataset.operatorSkin=ownerDocument.documentElement.dataset.operatorSkin||"ignite";
        doc.body.className=ownerDocument.body.className+" pp-tool-window";
        for(const key of ["operatorLayout","studioxVisualSystem"])doc.body.dataset[key]=ownerDocument.body.dataset[key]||"";
        logo.src=new URL(`/static/brand/producer-please-v2/PP_Approved_3D_Horizontal_on-${html.dataset.theme==="light"?"light":"dark"}_2400.png`,root.location.href).href;
      }
      function isRestricted(source){return source.nodeType===1&&restricted(source.tagName,source.type||"",`${source.id||""} ${source.name||""}`);}
      function mirror(source){
        if(![1,3].includes(source.nodeType))return null;
        let copy=copies.get(source);const blocked=isRestricted(source);
        if(copy&&copy._ppRestricted!==blocked){originals.delete(copy);edits.delete(copy);copy=null;}
        if(!copy){
          copy=source.nodeType===3?doc.createTextNode(""):isRestricted(source)?node("span"):doc.createElementNS(source.namespaceURI,source.tagName.toLowerCase());
          copy._ppRestricted=blocked;copies.set(source,copy);if(!blocked)originals.set(copy,source);
        }
        if(source.nodeType===3){if(copy.data!==source.data)copy.data=source.data;return copy;}
        if(isRestricted(source)){
          copy.className="pp-window-placeholder";copy.textContent=["SCRIPT","STYLE","LINK","META","BASE","SOURCE"].includes(source.tagName)?"":"Preview or protected control — use the main studio.";
          copy.hidden=!copy.textContent;return copy;
        }
        const kept=new Set();
        for(const attribute of source.attributes){
          const name=attribute.name.toLowerCase();
          if(!copyAttribute(source.tagName,name))continue;
          if(name==="href"&&!/^(https?:|\/|#)/i.test(attribute.value))continue;
          kept.add(name);if(copy.getAttribute(name)!==attribute.value)copy.setAttribute(name,attribute.value);
        }
        for(const attribute of [...copy.attributes])if(!kept.has(attribute.name))copy.removeAttribute(attribute.name);
        const desired=[...source.childNodes].map(mirror).filter(Boolean);
        let cursor=copy.firstChild;
        for(const child of desired){if(cursor===child)cursor=cursor.nextSibling;else copy.insertBefore(child,cursor);}
        while(cursor){const next=cursor.nextSibling;copy.removeChild(cursor);cursor=next;}
        if(["INPUT","SELECT","TEXTAREA"].includes(source.tagName)){
          if(!edits.has(copy)&&copy.value!==source.value)copy.value=source.value;
          if(source.tagName==="INPUT")copy.checked=source.checked;
          copy.disabled=source.disabled;
        }
        return copy;
      }
      function refresh(){
        queued=false;
        if(stopped)return;
        if(popup.closed){stop();return;}
        if(root.document!==ownerDocument||!panel.isConnected){stop("The main studio changed. Return there and reopen this tool.");return;}
        theme();const copy=mirror(panel);if(wrapper.firstChild!==copy)wrapper.replaceChildren(copy);
      }
      function schedule(){if(!queued&&!stopped){queued=true;root.queueMicrotask(refresh);}}
      function actionable(source){
        if(stopped||root.document!==ownerDocument||!source?.isConnected||!panel.contains(source)||isRestricted(source)||source.matches?.(":disabled"))return false;
        for(let current=source;current&&current!==panel;current=current.parentElement){
          if(current.hidden||current.inert||current.getAttribute("aria-disabled")==="true"||root.getComputedStyle(current).display==="none")return false;
        }
        return true;
      }
      function flush(){for(const [copy,value] of edits){const source=originals.get(copy);if(actionable(source))source.value=value;}edits.clear();}
      function reject(){notice.textContent="That control changed or is unavailable. Check the main studio before trying again.";schedule();}
      function syncField(copy,type){
        const source=originals.get(copy);if(!actionable(source)){reject();return;}
        edits.set(copy,copy.value);source.value=copy.value;source.dispatchEvent(new root.Event(type,{bubbles:true}));
      }
      host.addEventListener("input",event=>{if(event.target.matches("input,select,textarea"))syncField(event.target,"input");});
      host.addEventListener("change",event=>{if(event.target.matches("input,select,textarea")&&!["checkbox","radio"].includes(event.target.type))syncField(event.target,"change");});
      host.addEventListener("click",event=>{
        const copy=event.target.closest("button,a,summary,input[type=checkbox],input[type=radio],input[type=submit],input[type=reset]");
        if(!copy||!host.contains(copy))return;
        event.preventDefault();event.stopPropagation();const source=originals.get(copy);
        if(!actionable(source)){reject();return;}
        const form=copy.form;
        if(form&&(copy.type==="submit")&&!form.reportValidity())return;
        flush();notice.textContent="Action sent to the main studio. Complete any confirmation there.";source.click();schedule();
      });
      host.addEventListener("submit",event=>{
        event.preventDefault();const source=originals.get(event.target);
        if(actionable(source)&&event.target.reportValidity()){flush();source.requestSubmit();}else reject();
      });
      // Enter/Space operate the mirrored controls; main-window production hotkeys are never forwarded.
      host.addEventListener("keydown",event=>event.stopPropagation());
      host.addEventListener("focusout",()=>{flush();schedule();});
      const messages=ownerDocument.getElementById("notificationStack");
      const messageObserver=new root.MutationObserver(()=>{const latest=messages?.lastElementChild?.querySelector(".notification-copy strong");if(latest)notice.textContent=`Main studio: ${latest.textContent}. Return there for details.`;});
      if(messages)messageObserver.observe(messages,{childList:true,subtree:true,characterData:true});
      const observer=new root.MutationObserver(schedule);observer.observe(panel,{subtree:true,attributes:true,childList:true,characterData:true});
      const themeObserver=new root.MutationObserver(schedule);themeObserver.observe(ownerDocument.documentElement,{attributes:true,attributeFilter:["data-theme","data-operator-skin"]});
      function stop(message){
        if(stopped)return;stopped=true;observer.disconnect();themeObserver.disconnect();messageObserver.disconnect();root.clearInterval(timer);windows.delete(id);
        if(message&&!popup.closed){notice.textContent=message;host.inert=true;}
      }
      popup.addEventListener("pagehide",()=>stop());
      windows.set(id,{popup,stop});timer=root.setInterval(refresh,200);refresh();popup.focus();
      status(`${title} opened in its own window. The main studio remains its controller.`);return true;
    }
    root.addEventListener("pagehide",()=>{for(const {stop} of windows.values())stop("The main studio closed or reloaded. Return there and reopen this tool.");});
    return Object.freeze({open});
  }
  const api=Object.freeze({create,restricted,copyAttribute});
  if(typeof module!=="undefined"&&module.exports)module.exports=api;else root.ProducerStudioToolWindows=api;
})(typeof window!=="undefined"?window:globalThis);
