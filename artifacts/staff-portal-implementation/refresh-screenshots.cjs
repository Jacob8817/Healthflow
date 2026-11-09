const {chromium}=require('../healthflow-review/browser-tools/node_modules/playwright');
const path=require('node:path');
const fs=require('node:fs/promises');
const assert=require('node:assert/strict');
(async()=>{
 const browser=await chromium.launch({headless:true,executablePath:path.join(process.env.LOCALAPPDATA,'ms-playwright/chromium-1248/chrome-win64/chrome.exe')});
 const page=await browser.newPage({viewport:{width:1600,height:1120}});
 const errors=[];page.on('pageerror',e=>errors.push(e.message));
 const out=path.join(__dirname,'updated-screenshots');await fs.mkdir(out,{recursive:true});
 async function capture(name,{whole=true,mobile=false}={}){
  await page.setViewportSize({width:mobile?390:1600,height:1120});
  if(whole){
   await page.evaluate(()=>{document.querySelector('.workspace')?.scrollTo(0,0);document.querySelector('aside')?.scrollTo(0,0);});
   const height=await page.evaluate(()=>Math.max(1120,Math.ceil(document.querySelector('.workspace')?.scrollHeight||document.documentElement.scrollHeight)));
   await page.setViewportSize({width:mobile?390:1600,height:height+4});
  }
  if(!mobile&&await page.locator('.shell>aside').count()){
   const bounds=await page.locator('.shell>aside').boundingBox();assert.equal(bounds.y,0);
   const brand=await page.locator('.brand').boundingBox();assert.ok(brand.y>=0);
   const logout=await page.getByRole('button',{name:'Sign out',exact:true}).boundingBox();assert.ok(logout.y+logout.height<=page.viewportSize().height);
  }
  assert.equal(await page.locator('.demo-banner').count(),0);
  await page.screenshot({path:path.join(out,name),fullPage:false,animations:'disabled'});
 }
 try{
 await page.goto('http://localhost:5173');await page.getByRole('heading',{name:'Welcome back'}).waitFor();await capture('01-staff-login.png');
 await page.getByLabel('Work email').fill('admin@healthflow.local');await page.getByLabel('Password',{exact:true}).fill('ChangeMe123!');await page.getByRole('button',{name:'Sign in to workspace'}).click();
 await page.getByRole('heading',{name:'Hospital at a glance'}).waitFor();await capture('02-hospital-overview.png');
 for(const [label,heading,file] of [['Beds & wards','Beds & wards','03-bed-inventory.png'],['Emergency flow','Emergency flow','04-emergency-flow.png'],['Staffing & equipment','Staffing & equipment','05-staffing-resources.png']]){
  await page.getByRole('link',{name:label,exact:true}).click();await page.getByRole('heading',{name:heading,exact:true}).waitFor();await capture(file);
 }
 await page.getByRole('link',{name:'Demand forecast',exact:true}).click();await page.getByRole('heading',{name:'Demand forecast',exact:true}).waitFor();
 await page.locator('input[type=file]').setInputFiles('F:/projhosp/sample_data/hospital_prediction_test.csv');
 await page.waitForFunction(()=>document.querySelector('[aria-label="Emergency admissions 13"]')?.value==='4345');
 await capture('06-forecast-input.png');
 await page.getByRole('button',{name:'Generate hospital prediction'}).click();await page.locator('.forecast-result strong').waitFor();
 await page.setViewportSize({width:1600,height:1120});await page.locator('.forecast-output').scrollIntoViewIfNeeded();
 const scroll=await page.locator('.workspace').evaluate(el=>el.scrollTop);assert.ok(scroll>0);
 await capture('07-forecast-result.png',{whole:false});
 await page.getByRole('link',{name:'Use forecast in capacity planning'}).click();await page.getByRole('button',{name:'Run capacity scenario'}).click();await page.getByRole('heading',{name:'Scenario result'}).waitFor();await capture('08-connected-capacity-plan.png');
 await page.getByRole('link',{name:'Action queue',exact:true}).click();await page.getByRole('heading',{name:'Action queue',exact:true}).waitFor();await capture('09-action-queue.png');
 await page.setViewportSize({width:390,height:844});await page.getByRole('button',{name:'Open navigation'}).click();await page.getByRole('link',{name:'Emergency flow',exact:true}).click();await page.getByRole('heading',{name:'Emergency flow',exact:true}).waitFor();await capture('10-mobile-emergency.png',{mobile:true});
 assert.equal(await page.evaluate(()=>document.documentElement.scrollWidth),390);
 assert.deepEqual(errors,[]);
 await fs.writeFile(path.join(out,'verification.json'),JSON.stringify({bannerRemoved:true,desktopSidebarChecks:'All desktop screenshots show brand and sign out; sidebar stays at viewport top while forecast content scrolls.',mobileWidth:390,errors},null,2));
 console.log('PASS: 10 screenshots refreshed; banner absent; desktop sidebar bounds, scrolled prediction, mobile navigation, and console checks passed.');
 }finally{await browser.close();}
})().catch(e=>{console.error(e);process.exitCode=1;});
