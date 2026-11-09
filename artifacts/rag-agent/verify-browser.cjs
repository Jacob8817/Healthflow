const {chromium}=require('../healthflow-review/browser-tools/node_modules/playwright');
const path=require('node:path');const fs=require('node:fs/promises');const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1248/chrome-win64/chrome.exe')});
 const page=await browser.newPage({viewport:{width:1600,height:1120}});const errors=[];page.on('pageerror',e=>errors.push(e.message));
 try{
 await page.goto('http://localhost:5173');await page.getByLabel('Work email').fill('admin@healthflow.local');await page.getByLabel('Password',{exact:true}).fill('ChangeMe123!');await page.getByRole('button',{name:'Sign in to workspace'}).click();
 await page.getByRole('heading',{name:'Hospital at a glance'}).waitFor();
 await page.getByRole('link',{name:'Operations assistant',exact:true}).click();await page.getByText('Groq connected',{exact:true}).waitFor({timeout:20000});
 await page.getByLabel('Your question').fill('According to our HealthFlow software reference, explain which beds count towards operational capacity, and give our recorded available and staffed operational bed counts. Cite your sources.');
 const response=page.waitForResponse(r=>r.url().endsWith('/operations-intelligence')&&r.request().method()==='POST',{timeout:120000});
 await page.getByRole('button',{name:'Send question',exact:true}).click();const data=await (await response).json();assert.equal(data.status,'ok',JSON.stringify(data));assert.ok(data.citations.some(c=>c.kind==='policy'));
 await page.locator('.chat-turn.assistant').waitFor();await page.locator('.source-list summary').click();
 await page.evaluate(()=>document.querySelector('.workspace').scrollTo(0,0));await page.screenshot({path:path.join(__dirname,'01-rag-assistant.png')});
 await page.reload();await page.locator('.chat-turn.assistant').waitFor();assert.equal(await page.locator('.chat-turn.user').count(),1);
 await page.setViewportSize({width:390,height:844});assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);await page.screenshot({path:path.join(__dirname,'02-mobile-assistant.png')});
 await page.setViewportSize({width:1600,height:1120});await page.getByRole('link',{name:'Policy library',exact:true}).click();await page.getByRole('heading',{name:'Upload a document'}).waitFor();await page.screenshot({path:path.join(__dirname,'03-policy-library.png')});
 assert.deepEqual(errors,[]);await fs.writeFile(path.join(__dirname,'browser-verification.json'),JSON.stringify({status:'passed',conversationRestored:true,semanticCitations:true,mobileWidth:390,errors,answer:data},null,2));console.log('Browser passed: real Groq response, semantic citations, history restored, mobile fit, no JS errors.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exit(1);});
