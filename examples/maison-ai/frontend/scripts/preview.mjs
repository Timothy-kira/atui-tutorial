import {chromium} from '@playwright/test';
import fs from 'node:fs';
fs.mkdirSync('../.local/preview',{recursive:true});
const browser=await chromium.launch({headless:true,...(process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE?{executablePath:process.env.PLAYWRIGHT_CHROMIUM_EXECUTABLE}:{})});
const errors=[];
for(const [name,viewport] of [['desktop',{width:1440,height:1000}],['mobile',{width:390,height:844}]]){
 const page=await browser.newPage({viewport});
 page.on('pageerror',e=>errors.push({viewport:name,error:e.message}));
 await page.goto('http://127.0.0.1:3008/',{waitUntil:'networkidle'});
 await page.screenshot({path:'../.local/preview/'+name+'.png',fullPage:true});
 console.log(name,'overflow:',await page.evaluate(()=>document.documentElement.scrollWidth>innerWidth));
 await page.close();
}
fs.writeFileSync('../.local/preview/errors.json',JSON.stringify(errors,null,2));
console.log('Page errors:',errors.length);
await browser.close();
