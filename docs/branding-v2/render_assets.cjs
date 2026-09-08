const fs = require('fs');
const path = require('path');
const sharp = require('sharp');
const root=process.env.RAREIQ_BRAND_OUTPUT||path.resolve(__dirname,'../../output/branding/rareiq-v2');
(async()=>{
 let count=0;
 for(const folder of ['logos','mascot','icons','templates']) {
   for(const name of fs.readdirSync(path.join(root,folder)).filter(n=>n.endsWith('.svg'))) {
     const src=path.join(root,folder,name), dest=src.replace(/\.svg$/,'.png');
     await sharp(src).png().toFile(dest);count++;
     if(folder==='icons'){
       const sizes=name.includes('favicon')?[16,24,32,48,64]:[128,180,192,256,512,1024];
       for(const s of sizes)await sharp(src).resize(s,s).png().toFile(src.replace('.svg',`-${s}.png`));
     }
   }
 }
 console.log(`Rendered ${count} sources and icon sizes.`);
})();
