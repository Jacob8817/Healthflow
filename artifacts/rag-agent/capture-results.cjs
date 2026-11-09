const {chromium}=require('../healthflow-review/browser-tools/node_modules/playwright');const path=require('node:path');const fs=require('node:fs/promises');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1248/chrome-win64/chrome.exe')});
 const page=await browser.newPage({viewport:{width:1600,height:1120},reducedMotion:'reduce'});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto('http://localhost:5173');await page.getByLabel('Work email').fill('admin@healthflow.local');await page.getByLabel('Password',{exact:true}).fill('ChangeMe123!');await page.getByRole('button',{name:'Sign in to workspace'}).click();await page.getByRole('heading',{name:'Hospital at a glance'}).waitFor();
 const uid=await page.evaluate(async()=>{const r=await fetch('http://localhost:8000/api/v1/auth/me',{headers:{Authorization:'Bearer '+localStorage.getItem('healthflow_token')}});return (await r.json()).id;});
 const policy=JSON.parse(await fs.readFile(path.join(__dirname,'browser-verification.json'),'utf8')).answer;
 await page.evaluate(({uid,cid})=>localStorage.setItem(`healthflow_chat_${uid}_DEMO-HOSP-01`,cid),{uid,cid:policy.conversation_id});
 await page.getByRole('link',{name:'Operations assistant',exact:true}).click();await page.locator('.chat-turn.assistant').waitFor();
 await page.setViewportSize({width:1600,height:1500});await page.screenshot({path:path.join(__dirname,'01-rag-assistant.png')});
 await page.setViewportSize({width:390,height:844});await page.waitForFunction(()=>document.querySelector('.shell>aside').getBoundingClientRect().right<=1);console.log(await page.evaluate(()=>['.workspace','main','.page-head','.record-strip','.assistant-layout','.assistant-chat','.chat-turn','.chat-text'].map(sel=>{const e=document.querySelector(sel),r=e.getBoundingClientRect();return {sel,x:r.x,width:r.width,scroll:e.scrollWidth};})));assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);console.log(await page.evaluate(()=>['.workspace','.workspace main','.page-head','.assistant-layout','.assistant-chat','.chat-text'].map(s=>{const e=document.querySelector(s),r=e.getBoundingClientRect();return {selector:s,x:r.x,width:r.width,scroll:e.scrollWidth,client:e.clientWidth}})));await page.screenshot({path:path.join(__dirname,'02-mobile-assistant.png')});
 await page.setViewportSize({width:1600,height:1120});
 const forecast=JSON.parse(await fs.readFile(path.join(__dirname,'forecast-agent.json'),'utf8'));
 await page.evaluate(({uid,cid})=>localStorage.setItem(`healthflow_chat_${uid}_DEMO-HOSP-01`,cid),{uid,cid:forecast.conversation_id});await page.reload();await page.getByText('4,411 predicted admissions',{exact:true}).waitFor();await page.screenshot({path:path.join(__dirname,'04-forecast-tool.png')});
 const capacity=JSON.parse(await fs.readFile(path.join(__dirname,'capacity-agent.json'),'utf8'));
 await page.evaluate(({uid,cid})=>localStorage.setItem(`healthflow_chat_${uid}_DEMO-HOSP-01`,cid),{uid,cid:capacity.conversation_id});await page.reload();await page.getByText('25 additional beds · 2644 additional staff-hours',{exact:true}).waitFor();await page.setViewportSize({width:1600,height:1600});await page.screenshot({path:path.join(__dirname,'05-capacity-tool.png')});
 assert.deepEqual(errors,[]);console.log('Verified tool cards and mobile navigation; refreshed 4 screenshots.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
