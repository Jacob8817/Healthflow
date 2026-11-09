const {chromium}=require('./healthflow-review/browser-tools/node_modules/playwright');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:process.env.LOCALAPPDATA+'/ms-playwright/chromium-1248/chrome-win64/chrome.exe'});
 const page=await browser.newPage({viewport:{width:1024,height:1100}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 // Exercise the literal fragment in an isolated browser document.
 const html=await fs.readFile('F:/projhosp/artifacts/healthflow-staff-portal-concept.html','utf8');
 await page.setContent('<!doctype html><html><head><meta name="viewport" content="width=device-width, initial-scale=1"><style>:root{color-scheme:light dark}body{margin:0}</style></head><body>'+html+'</body></html>');
 await page.getByRole('button',{name:'Intensive care 1 available / 12 spaces'}).click();
 assert.equal(await page.locator('#hf-ward-title').innerText(),'Intensive care');
 await page.getByRole('button',{name:'ICU bed 11, Available · staffed',exact:true}).click();
 assert.match(await page.locator('#hf-bed-detail').innerText(),/ICU-11.*Available/);
 await page.getByRole('button',{name:'Inspect blocked beds'}).click();
 assert.match(await page.locator('#hf-bed-detail').innerText(),/ED-12.*Blocked/);
 for(const name of ['Emergency flow','Demand planning','Hospital overview'])await page.getByRole('button',{name,exact:true}).click();
 await page.screenshot({path:'F:/projhosp/artifacts/healthflow-staff-concept-desktop.png',fullPage:true});
 for(const width of [736,390,320]){
  await page.setViewportSize({width,height:1100});
  const dimensions=await page.evaluate(()=>({width:innerWidth,content:document.documentElement.scrollWidth}));
  assert.equal(dimensions.content,dimensions.width,JSON.stringify(dimensions));
  for(const name of ['Emergency flow','Demand planning','Hospital overview'])await page.getByRole('button',{name,exact:true}).click();
 }
 await page.screenshot({path:'F:/projhosp/artifacts/healthflow-staff-concept-mobile.png',fullPage:true});
 await page.emulateMedia({colorScheme:'dark'});await page.setViewportSize({width:1024,height:1100});
 await page.screenshot({path:'F:/projhosp/artifacts/healthflow-staff-concept-dark.png',fullPage:true});
 assert.deepEqual(errors,[]);console.log('PASS: ward selection, bed details, blocked-bed action, three views, 1024/736/390/320px, dark render, no JavaScript errors');
 await browser.close();
})().catch(e=>{console.error(e);process.exitCode=1;});
