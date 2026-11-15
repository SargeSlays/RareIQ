/* Revision stays attached to the open draft; background reads cannot rebase it. */
(function(root){
  class ProductionSceneEdits {
    static requestId(cryptoSource=crypto){
      if(typeof cryptoSource.randomUUID==='function')return cryptoSource.randomUUID();
      return Array.from(cryptoSource.getRandomValues(new Uint8Array(16)),value=>value.toString(16).padStart(2,'0')).join('');
    }
    constructor(makeId=()=>ProductionSceneEdits.requestId()){this.makeId=makeId;this.revision=null;this.draftRevision=null;this.pending=null;}
    loaded(revision){if(!Number.isSafeInteger(revision)||revision<0)throw new Error('Reload the studio to update scene editing.');if(this.revision===null||revision>=this.revision)this.revision=revision;}
    begin(){if(this.revision===null)throw new Error('Scenes are still loading. Try again shortly.');this.draftRevision=this.revision;this.pending=null;}
    prepare(data){
      if(this.draftRevision===null)throw new Error('Open the scene editor again.');
      const fingerprint=JSON.stringify(data);
      if(!this.pending||this.pending.fingerprint!==fingerprint)this.pending={fingerprint,request_id:this.makeId()};
      return {...data,expected_revision:this.draftRevision,request_id:this.pending.request_id};
    }
    saved(){this.draftRevision=null;this.pending=null;}
  }
  if(typeof module==='object'&&module.exports)module.exports={ProductionSceneEdits};
  else root.ProductionSceneEdits=ProductionSceneEdits;
})(typeof window==='object'?window:globalThis);
