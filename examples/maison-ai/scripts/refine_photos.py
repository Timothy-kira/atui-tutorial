"""Use Wikimedia food photographs where a stock photo did not match the dish."""
import concurrent.futures,html,json,re,urllib.parse,urllib.request
from pathlib import Path
ROOT=Path(__file__).resolve().parents[1];OUT=ROOT/'frontend/public/images'
MATCHES={'caesar':'Caesar_salad','soup':'Cream_of_mushroom_soup','burrata':'Burrata','duck':'Duck_confit','risotto':'Risotto','carbonara':'Carbonara','seafood':'Spaghetti_alle_vongole','sorbet':'Sorbet','lemonade':'Lemonade'}
def get(url):
    request=urllib.request.Request(url,headers={'User-Agent':'MaisonAIWorkshop/1.0 (educational demo)'})
    return urllib.request.urlopen(request,timeout=15).read()
def fetch(pair):
    dish,title=pair
    for attempt in range(2):
        try:
            page=json.loads(get('https://en.wikipedia.org/api/rest_v1/page/summary/'+title))
            url=page['originalimage']['source'];filename=urllib.parse.unquote(url.rsplit('/',1)[-1])
            query=urllib.parse.urlencode(dict(action='query',format='json',prop='imageinfo',titles='File:'+filename,iiprop='extmetadata'))
            meta=json.loads(get('https://commons.wikimedia.org/w/api.php?'+query))
            image=next(iter(meta['query']['pages'].values()))['imageinfo'][0]['extmetadata']
            license=image.get('LicenseShortName',{}).get('value','')
            if not license:raise ValueError('No verified license metadata')
            data=get(url);(OUT/(dish+'.jpg')).write_bytes(data)
            record=dict(dish_id=dish,url=url,source='https://commons.wikimedia.org/wiki/File:'+urllib.parse.quote(filename),
                license=license,license_url=image.get('LicenseUrl',{}).get('value',''),artist=re.sub('<[^>]+>','',image.get('Artist',{}).get('value','')),
                status='downloaded',note='Illustrative food photography; plating may differ.')
            print(dish,'matched; license:',license,flush=True);return record
        except Exception as e:
            if attempt==1:print(dish,'retained existing illustrative photo:',type(e).__name__,flush=True)
    return None
if __name__=='__main__':
    sources=OUT/'sources.json';records=json.loads(sources.read_text())
    with concurrent.futures.ThreadPoolExecutor(4) as pool:
        for result in pool.map(fetch,MATCHES.items()):
            if result:records=[r for r in records if r['dish_id']!=result['dish_id']]+[result]
    sources.write_text(json.dumps(records,indent=2),encoding='utf-8')
    lines=['<!doctype html><meta charset="utf-8"><title>Maison AI photo credits</title><style>body{font:16px/1.6 system-ui;max-width:900px;margin:50px auto;padding:20px}li{margin-bottom:18px}</style><h1>Photo credits</h1><p>Illustrative food photography. Actual plating may differ.</p><ul>']
    for r in records:
        artist=html.escape(r.get('artist','Unsplash community'));license=html.escape(r.get('license',''))
        source=html.escape(r.get('source','https://unsplash.com'),quote=True)
        url=html.escape(r.get('license_url',r.get('license','https://unsplash.com/license')),quote=True)
        lines.append(f'<li><b>{html.escape(r["dish_id"])}</b> — {artist} · <a href="{source}">Source</a> · <a href="{url}">{license}</a></li>')
    (OUT/'credits.html').write_text('\n'.join(lines+['</ul>']),encoding='utf-8')
