"""Download local Unsplash food photography; failed assets use a labelled fallback."""
import concurrent.futures,json,urllib.request
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
# These are existing Unsplash photo asset identifiers, never model-generated URLs.
PHOTOS={
 'caesar':'1512621776951-a57141f2eefd','soup':'1547592180-85f173990554',
 'bruschetta':'1572695157366-5e585ab2b69f','burrata':'1608897013039-887f21d8c804',
 'ribeye':'1546833999-b9f581a1996d','filet':'1558030006-450675393462',
 'salmon':'1467003909585-2f8a72700288','chicken':'1532550907401-a500c9a57435',
 'duck':'1544025162-d76694265947','risotto':'1473093295043-cdd812d0e601',
 'cauliflower':'1511690743698-d9d85f2fbf38','carbonara':'1621996346565-e3dbc646d9a9',
 'pesto':'1473093295043-cdd812d0e601','margherita':'1579751626657-72bc17010498',
 'seafood':'1551183053-bf91a1d81141','pepperoni':'1628840042765-356cda07504e',
 'tiramisu':'1571877227200-a0d98ea607e9','cheesecake':'1533134242443-d4fd215305ad',
 'chocolate':'1578985545062-69928b1d9587','sorbet':'1563805042-7684c019e1cb',
 'lemonade':'1513558161293-cdaf765edfd7','coffee':'1509042239860-f550ce710b93',
 'water':'1523362628745-0c100150b504','icedtea':'1556679343-c7306c1976bc',
}
def fetch(pair):
    dish,photo=pair;url=f'https://images.unsplash.com/photo-{photo}?auto=format&fit=crop&w=900&q=85'
    dest=ROOT/'frontend/public/images'/f'{dish}.jpg'
    record=dict(dish_id=dish,url=url,source=f'https://unsplash.com/photos/{photo}',license='https://unsplash.com/license',note='Illustrative food photography; plating may differ.')
    for _ in range(2):
        try:
            data=urllib.request.urlopen(urllib.request.Request(url,headers={'User-Agent':'MaisonAIWorkshop/1.0'}),timeout=20).read()
            if len(data)<3000:raise ValueError('Image too small')
            dest.write_bytes(data);record['status']='downloaded';return record
        except Exception as e:record['status']='placeholder';record['error']=type(e).__name__
    return record

if __name__=='__main__':
    root=ROOT/'.local/tasks/assets';root.mkdir(parents=True,exist_ok=True)
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
        records=[]
        for record in pool.map(fetch,PHOTOS.items()):
            records.append(record);print(record['dish_id'],record['status'],flush=True)
            (root/'status.json').write_text(json.dumps(dict(status='running',completed=len(records),total=24)),encoding='utf-8')
    (ROOT/'frontend/public/images/sources.json').write_text(json.dumps(records,indent=2),encoding='utf-8')
    (root/'status.json').write_text(json.dumps(dict(status='complete',completed=24,downloaded=sum(r['status']=='downloaded' for r in records),total=24)),encoding='utf-8')
