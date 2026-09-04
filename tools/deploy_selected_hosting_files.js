// Rebuild current Hosting manifest, remove private dot paths, replace only listed files, release.
const fs=require('fs'),zlib=require('zlib'),crypto=require('crypto'),path=require('path');
const api=require('firebase-tools/lib/hosting/api');
const {Client}=require('firebase-tools/lib/apiv2');
const site='decorate-me';
const files=Object.fromEntries(process.argv.slice(2).map(arg=>{const [url,...rest]=arg.split('=');return [url,rest.join('=')];}));
if(!Object.keys(files).length) throw Error('no files');
(async()=>{
  const client=new Client({urlPrefix:'https://firebasehosting.googleapis.com/v1beta1',auth:true});
  const releasePage=await client.get(`/sites/${site}/releases`,{queryParams:{pageSize:1}});
  const releases=releasePage.body.releases||[];
  const source=releases[0]?.version?.name;
  if(!source) throw Error('current version unavailable');
  const version=await api.createVersion(site,{config:releases[0].version.config,labels:{'deployment-tool':'codex-selected-files'}});
  const map={}; const bodies={};
  let pageToken;
  do {
    const queryParams={pageSize:1000}; if(pageToken) queryParams.pageToken=pageToken;
    const page=await client.get(`/${source}/files`,{queryParams});
    for(const f of page.body.files||[]){
      if(f.path.startsWith('/.git/')||f.path.startsWith('/.claude/')) continue;
      map[f.path]=f.hash;
    }
    pageToken=page.body.nextPageToken;
  } while(pageToken);
  for(const [url,file] of Object.entries(files)){
    const raw=fs.readFileSync(path.resolve(file));
    const gzip=zlib.gzipSync(raw,{level:9});
    const hash=crypto.createHash('sha256').update(gzip).digest('hex');
    map[url]=hash;bodies[hash]=gzip;
  }
  let uploadClient;
  for(let i=0;i<Object.keys(map).length;i+=1000){
    const batch=Object.fromEntries(Object.entries(map).slice(i,i+1000));
    const populated=await client.post(`/${version}:populateFiles`,{files:batch});
    uploadClient ||= new Client({urlPrefix:populated.body.uploadUrl,auth:true});
    for(const hash of populated.body.uploadRequiredHashes||[]){
      if(!bodies[hash]) throw Error('unexpected required hash '+hash);
      const res=await uploadClient.request({method:'POST',path:`/${hash}`,body:bodies[hash],resolveOnHTTPError:true});
      if(res.status!==200) throw Error('upload failed '+hash+' '+res.status);
    }
  }
  await api.updateVersion(site,version.split('/').pop(),{status:'FINALIZED'});
  const release=await api.createRelease(site,'live',version,{type:'DEPLOY',message:'Selected admin macro and OTP fixes; internal dotfiles removed from cloned release'});
  console.log(JSON.stringify({source,version,release:release.name,files:Object.keys(files),removed:['/.git/**','/.claude/**']}));
})().catch(e=>{console.error(e);process.exit(1)});
