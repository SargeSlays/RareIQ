// Local real-browser regression. Requires installed Edge and Playwright; no real production actions.
const {chromium}=require('playwright');
const assert=require('node:assert/strict');
const origin=process.env.RAREIQ_QA_ORIGIN||'http://127.0.0.1:9040';
const fixture=`<!doctype html><html data-theme="dark" data-operator-skin="ignite"><body class="pp-shell"><div id="tool">
<form id="form"><input id="name" required><input id="check" type="checkbox"><select id="select"><option value="studio">General streaming</option><option value="cards">Card show</option></select><textarea id="notes"></textarea><button id="submit" type="submit">Save</button></form>
<details id="disclosure"><summary>Advanced</summary><p>Options</p></details><input id="dynamicField" type="text"><button id="action" type="button">Action</button><button id="busy" disabled>Busy</button><strong id="result">Ready</strong>
<input id="obsPassword" type="password" value="FAKE_TEST_ONLY_DO_NOT_COPY"><input id="rundownImport" type="file"><iframe src="about:blank"></iframe><canvas></canvas><video></video>
</div><script src="/static/studio_tool_windows.js"></script></body></html>`;
(async()=>{
  const browser=await chromium.launch({headless:true,channel:'msedge'});
  try{
    const context=await browser.newContext(),page=await context.newPage();const errors=[],requests=[];
    context.on('page',p=>{p.on('pageerror',e=>errors.push(e.message));p.on('request',r=>requests.push({url:r.url(),method:r.method(),page:p}));});
    await page.route('**/__tool_window_qa',route=>route.fulfill({contentType:'text/html',body:fixture}));
    await page.goto(origin+'/__tool_window_qa');
    await page.evaluate(()=>{
      window.calls={action:0,submit:0,busy:0};window.messages=[];
      document.getElementById('action').onclick=()=>{calls.action++;document.getElementById('result').textContent='Updated '+calls.action;};
      document.getElementById('busy').onclick=()=>calls.busy++;
      document.getElementById('form').onsubmit=event=>{event.preventDefault();calls.submit++;calls.name=document.getElementById('name').value;};
      window.manager=ProducerStudioToolWindows.create({status:message=>messages.push(message)});
    });
    const opened=page.waitForEvent('popup');await page.evaluate(()=>manager.open('qa','QA tool',document.getElementById('tool')));const popup=await opened;
    await popup.waitForSelector('#name');
    assert.equal(await popup.locator('iframe,canvas,video,input[type=password],input[type=file]').count(),0);
    assert.ok(!await popup.content().then(s=>s.includes('FAKE_TEST_ONLY_DO_NOT_COPY')));
    assert.equal(await popup.locator('#select').inputValue(),'studio');
    await popup.locator('summary').click();assert.equal(await page.locator('#disclosure').getAttribute('open'),'');
    await page.evaluate(()=>{document.getElementById('dynamicField').type='password';document.getElementById('dynamicField').value='SECOND_FAKE_PROTECTED_VALUE';});await popup.waitForFunction(()=>!document.getElementById('dynamicField'));assert.ok(!await popup.content().then(s=>s.includes('SECOND_FAKE_PROTECTED_VALUE')));
    await popup.locator('#action').click();assert.equal(await page.evaluate(()=>calls.action),1);await popup.locator('#result').filter({hasText:'Updated 1'}).waitFor();
    await popup.locator('#submit').click();assert.equal(await page.evaluate(()=>calls.submit),0,'native validation must prevent submission');
    await popup.locator('#name').fill('draft');await popup.locator('#select').selectOption('cards');await popup.locator('#check').click();
    assert.deepEqual(await page.evaluate(()=>[document.getElementById('name').value,document.getElementById('select').value,document.getElementById('check').checked]),['draft','cards',true]);
    await popup.locator('#name').fill('kept while editing');
    await page.evaluate(()=>{document.getElementById('name').value='background update';document.getElementById('result').textContent='Background';});
    await popup.locator('#result').filter({hasText:'Background'}).waitFor();assert.equal(await popup.locator('#name').inputValue(),'kept while editing');
    await popup.locator('#name').press('Enter');assert.deepEqual(await page.evaluate(()=>[calls.submit,calls.name]),[1,'kept while editing']);
    await popup.locator('#submit').focus();await page.evaluate(()=>{document.getElementById('name').value='server value';document.getElementById('check').checked=false;});await popup.waitForFunction(()=>document.getElementById('name').value==='server value');assert.equal(await popup.locator('#check').isChecked(),false);
    await popup.locator('#busy').evaluate(e=>e.click());assert.equal(await page.evaluate(()=>calls.busy),0);
    await page.evaluate(()=>{document.getElementById('action').disabled=true;});await popup.waitForFunction(()=>document.getElementById('action').disabled);await popup.locator('#action').evaluate(e=>e.click());assert.equal(await page.evaluate(()=>calls.action),1);
    await page.evaluate(()=>{const b=document.createElement('button');b.id='dynamic';b.textContent='New row';b.onclick=()=>calls.action++;document.getElementById('tool').append(b);});await popup.locator('#dynamic').click();assert.equal(await page.evaluate(()=>calls.action),2);
    await popup.evaluate(()=>window.oldButton=document.getElementById('dynamic'));await page.evaluate(()=>document.getElementById('dynamic').remove());await popup.waitForFunction(()=>!document.getElementById('dynamic'));await popup.evaluate(()=>oldButton.click());assert.equal(await page.evaluate(()=>calls.action),2);
    await page.evaluate(()=>{document.documentElement.dataset.theme='light';document.documentElement.dataset.operatorSkin='daylight';});await popup.waitForFunction(()=>document.documentElement.dataset.operatorSkin==='daylight');
    const repeated=await page.evaluate(()=>manager.open('qa','QA tool',document.getElementById('tool')));assert.equal(repeated,true);assert.equal(context.pages().length,2);
    assert.ok(!requests.some(r=>r.page===popup&&(/\/api\//.test(r.url)||r.method!=='GET')),'popup must not create an API owner');
    await popup.close();await page.evaluate(()=>{window.savedOpen=window.open;window.open=()=>null;manager.open('blocked','Blocked tool',document.getElementById('tool'));window.open=savedOpen;});assert.match(await page.evaluate(()=>messages.at(-1)),/blocked/i);
    const second=page.waitForEvent('popup');await page.evaluate(()=>manager.open('qa','QA tool',document.getElementById('tool')));const reopened=await second;await reopened.waitForSelector('#name');await page.reload();await reopened.waitForFunction(()=>document.querySelector('.pp-window-content').inert);assert.match(await reopened.locator('.pp-window-notice').textContent(),/closed or reloaded/);
    assert.deepEqual(errors,[]);console.log('PASS: tool-window validation, edits, one activation, state updates, disabled/stale controls, dynamic rows, theme, reuse, blocked/closed windows, parent reload, and media/credential isolation.');
  }finally{await browser.close();}
})().catch(error=>{console.error(error.message);process.exitCode=1;});
