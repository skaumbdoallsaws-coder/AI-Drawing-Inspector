'use strict';
const { researchURL } = require('./research-policy.cjs');
const MAX_BYTES = 64 * 1024;
function rasterType(bytes) {
  if (bytes.length >= 24 && bytes.subarray(0,8).equals(Buffer.from([137,80,78,71,13,10,26,10]))) {
    const w=bytes.readUInt32BE(16),h=bytes.readUInt32BE(20);
    return w>0&&h>0&&w<=512&&h<=512?'image/png':null;
  }
  if (bytes.length>=10 && /^GIF8[79]a$/.test(bytes.subarray(0,6).toString())) {
    const w=bytes.readUInt16LE(6),h=bytes.readUInt16LE(8);
    return w>0&&h>0&&w<=512&&h<=512?'image/gif':null;
  }
  if(bytes.length>=22&&bytes.readUInt32LE(0)===65536){
    const count=bytes.readUInt16LE(4);
    if(!count||count>16||bytes.length<6+count*16)return null;
    for(let i=0;i<count;i++){
      const entry=6+i*16,size=bytes.readUInt32LE(entry+8),offset=bytes.readUInt32LE(entry+12);
      if(offset<6+count*16||size<8||offset+size>bytes.length)return null;
      const embedded=bytes.subarray(offset,offset+size);
      if(embedded[0]===137&&!rasterType(embedded))return null;
    }
    return 'image/x-icon';
  }
  return null;
}
async function readIcon(response) {
  if(!response.ok||+response.headers.get('content-length')>MAX_BYTES){await response.body?.cancel();throw Error('favicon_unavailable');}
  let length=0;const chunks=[];
  for await(const chunk of response.body){length+=chunk.length;if(length>MAX_BYTES)throw Error('favicon_too_large');chunks.push(Buffer.from(chunk));}
  return Buffer.concat(chunks);
}
function isFaviconDataURL(value) {
  if(typeof value!=='string'||value.length>MAX_BYTES*1.4)return false;
  const match=/^data:(image\/(?:png|gif|x-icon));base64,([a-z0-9+/=]+)$/i.exec(value);
  if(!match)return false;
  const bytes=Buffer.from(match[2],'base64');
  return bytes.length<=MAX_BYTES&&rasterType(bytes)===match[1];
}
async function loadFavicon({ session, urls, pageURL, signal }) {
  let fallback;
  try { fallback=new URL('/favicon.ico',researchURL(pageURL)).href; } catch (_) { return null; }
  const candidates=[...new Set([...(Array.isArray(urls)?urls.filter(u=>typeof u==='string').slice(0,3):[]),fallback])];
  for(const candidate of candidates){
    if(signal?.aborted)return null;
    try{
      let bytes;
      if(candidate.startsWith('data:')){
        if(candidate.length>MAX_BYTES*1.4)continue;
        const match=/^data:image\/(?:png|gif|x-icon|vnd.microsoft.icon);base64,([a-z0-9+/=]+)$/i.exec(candidate);
        if(!match)continue;bytes=Buffer.from(match[1],'base64');
      }else{
        let url=researchURL(candidate),response;
        for(let redirect=0;redirect<4;redirect++){
          response=await session.fetch(url,{redirect:'manual',credentials:'omit',signal});
          if(response.status<300||response.status>=400)break;
          const location=response.headers.get('location');await response.body?.cancel();
          if(!location)throw Error('favicon_redirect_missing');
          url=researchURL(new URL(location,url).href);response=null;
        }
        if(!response)continue;bytes=await readIcon(response);
      }
      if(bytes.length>MAX_BYTES)continue;
      const mime=rasterType(bytes);if(mime)return `data:${mime};base64,${bytes.toString('base64')}`;
    }catch(_){ /* A missing icon must never prevent navigation. */ }
  }
  return null;
}
module.exports={loadFavicon,rasterType,isFaviconDataURL,MAX_BYTES};
