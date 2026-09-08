const {test}=require('node:test');
const assert=require('node:assert/strict');
const {restricted,copyAttribute}=require('../../rareiq/web/static/studio_tool_windows.js');
test('tool windows exclude media owners, executable elements and protected fields before cloning',()=>{
  for(const tag of ['SCRIPT','IFRAME','IMG','image','foreignObject','VIDEO','AUDIO','CANVAS','OBJECT','EMBED'])assert.equal(restricted(tag),true,tag);
  for(const type of ['password','file'])assert.equal(restricted('INPUT',type),true);
  for(const identity of ['obsPassword','streamKey','api_key','accessToken','clientSecret'])assert.equal(restricted('INPUT','text',identity),true,identity);
  for(const tag of ['BUTTON','FORM','SELECT','TEXTAREA','DIV'])assert.equal(restricted(tag),false,tag);
  assert.equal(restricted('INPUT','text','productionSessionName'),false);
});

test('option machine values survive different display labels; editable values and active content are not attributes',()=>{
  assert.equal(copyAttribute('OPTION','value'),true);assert.equal(copyAttribute('BUTTON','value'),true);
  assert.equal(copyAttribute('INPUT','value'),false);assert.equal(copyAttribute('TEXTAREA','value'),false);
  for(const name of ['onclick','onload','src','srcdoc','action','formaction'])assert.equal(copyAttribute('DIV',name),false);
});
