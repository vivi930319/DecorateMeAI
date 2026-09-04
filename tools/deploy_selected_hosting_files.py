import gzip,hashlib,json,subprocess,sys,requests
site='decorate-me'; base='https://firebasehosting.googleapis.com/v1beta1'
token=subprocess.check_output(['gcloud.cmd','auth','print-access-token'],text=True).strip()
h={'Authorization':f'Bearer {token}','x-goog-user-project':'decorate-me'}
def call(method,url,**kw):
 r=requests.request(method,base+url,headers=h,timeout=90,**kw); r.raise_for_status(); return r.json() if r.content else {}
releases=call('GET',f'/sites/{site}/releases?pageSize=1')['releases']; current=releases[0]['version']; source=current['name']
version=call('POST',f'/projects/-/sites/{site}/versions',json={'config':current['config'],'labels':{'deployment-tool':'codex-selected-files'}})['name']
files={}; page=''
while True:
 data=call('GET',f'/{source}/files?pageSize=1000'+(f'&pageToken={page}' if page else ''))
 for f in data.get('files',[]):
  if not (f['path'].startswith('/.git/') or f['path'].startswith('/.claude/')): files[f['path']]=f['hash']
 page=data.get('nextPageToken','')
 if not page: break
bodies={}
for arg in sys.argv[1:]:
 url,path=arg.split('=',1); body=gzip.compress(open(path,'rb').read(),compresslevel=9,mtime=0); digest=hashlib.sha256(body).hexdigest(); files[url]=digest;bodies[digest]=body
upload=''
entries=list(files.items())
for i in range(0,len(entries),1000):
 data=call('POST',f'/{version}:populateFiles',json={'files':dict(entries[i:i+1000])});upload=data['uploadUrl']
 for digest in data.get('uploadRequiredHashes',[]):
  if digest not in bodies: raise RuntimeError('unexpected missing old hash '+digest)
  r=requests.post(upload+'/'+digest,headers=h,data=bodies[digest],timeout=90);r.raise_for_status()
call('PATCH',f'/{version}?updateMask=status',json={'status':'FINALIZED'})
release=call('POST',f'/projects/-/sites/{site}/channels/live/releases?versionName={version}',json={'type':'DEPLOY','message':'Selected OTP, guest feedback, admin macro fixes; remove internal dotfiles'})
print(json.dumps({'version':version,'release':release.get('name'),'files':list(sys.argv[1:])}))
