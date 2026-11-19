'use strict';
// A persisted change remains successful if the separate local history is unavailable.
// Only the profile/version is recorded; source routes, names and credentials stay out.
function createProfileActions({store,append,clock=()=>new Date().toISOString()}={}){
  async function apply(action,input){
    const result=await store[action](input);
    const id=action==='save'?result.savedProfileId:input;
    const profile=result.profiles?.find(p=>p.id===id);
    const profileId=typeof id==='string'&&/^[A-Za-z0-9_-]{1,80}$/.test(id)?id:null;
    try{
      await append({at:clock(),action:'output_profile.'+action,actor:'Desktop operator',identityVerified:false,
        profileId,updatedAt:Number.isSafeInteger(profile?.updatedAt)?profile.updatedAt:null,
        replayed:action==='save'&&result.replayed===true});
      return result;
    }catch(_){return {...result,activity_history_warning:true};}
  }
  return Object.freeze({save:value=>apply('save',value),select:id=>apply('select',id),remove:id=>apply('remove',id)});
}
module.exports={createProfileActions};
