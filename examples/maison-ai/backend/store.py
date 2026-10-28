"""Server-authoritative money, per-thread carts, expiring quotes and demo orders."""
import hashlib, json, os, secrets, sqlite3, time, uuid
from datetime import datetime, timedelta, timezone
from contextlib import contextmanager
from pathlib import Path
from .config import ROOT

MENU = json.loads((ROOT/'backend/data/menu.json').read_text(encoding='utf-8'))
BY_ID = {dish['id']:dish for dish in MENU}

class BusinessError(ValueError): pass

RESTAURANT_TIMEZONE=timezone(timedelta(hours=8),'Singapore')
TABLES=[{'id':f'T{n:02d}','seats':seats} for n,seats in enumerate([2,2,4,4,6,8,12],1)]

def reservation_window(date,start_time,end_time,party_size):
    import re
    if type(party_size) is not int or not 1<=party_size<=12:raise BusinessError('Choose 1–12 guests')
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',date or ''):raise BusinessError('Choose a reservation date')
    if not all(re.fullmatch(r'\d{2}:\d{2}',value or '') for value in (start_time,end_time)):raise BusinessError('Choose a start and end time')
    try:
        start=datetime.fromisoformat(f'{date}T{start_time}').replace(tzinfo=RESTAURANT_TIMEZONE)
        end=datetime.fromisoformat(f'{date}T{end_time}').replace(tzinfo=RESTAURANT_TIMEZONE)
    except ValueError as exc:raise BusinessError('Invalid reservation date or time') from exc
    if end<=start:raise BusinessError('End time must be after start time on the same day')
    if start<=datetime.now(RESTAURANT_TIMEZONE):raise BusinessError('Choose a future reservation time')
    return {'date':date,'start_time':start_time,'end_time':end_time,'party_size':party_size,'starts_at':start.timestamp(),'ends_at':end.timestamp(),'timezone':'Singapore (UTC+08:00)'}

class Store:
    def __init__(self, path=None):
        self.path=Path(path or ROOT/os.getenv('MAISON_DB','.local/maison.sqlite3'))
        self.path.parent.mkdir(parents=True,exist_ok=True)
        with self.db() as db:
            db.executescript('''
            CREATE TABLE IF NOT EXISTS carts(sid TEXT PRIMARY KEY, revision INTEGER NOT NULL, items TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS quotes(token TEXT PRIMARY KEY, sid TEXT NOT NULL, revision INTEGER NOT NULL, expires REAL NOT NULL, idempotency_key TEXT NOT NULL);
            CREATE TABLE IF NOT EXISTS orders(id TEXT PRIMARY KEY,sid TEXT NOT NULL,idem TEXT NOT NULL,payload TEXT NOT NULL,UNIQUE(sid,idem));
            CREATE TABLE IF NOT EXISTS reservations(id TEXT PRIMARY KEY,sid TEXT NOT NULL,idem TEXT NOT NULL,table_id TEXT NOT NULL,starts REAL NOT NULL,ends REAL NOT NULL,payload TEXT NOT NULL,UNIQUE(sid,idem));
            CREATE INDEX IF NOT EXISTS reservation_window ON reservations(table_id,starts,ends);
            ''')

    @contextmanager
    def db(self):
        with sqlite3.connect(self.path,timeout=15) as db:
            db.row_factory=sqlite3.Row
            db.execute('PRAGMA foreign_keys=ON');db.execute('BEGIN IMMEDIATE')
            yield db

    def _cart(self,db,sid):
        row=db.execute('SELECT * FROM carts WHERE sid=?',(sid,)).fetchone()
        items=json.loads(row['items']) if row else []
        for item in items:
            dish=BY_ID[item['dish_id']]
            item.update(name=dish['name'],unit_price_cents=round(dish['price']*100),image=dish['image'])
            item['line_total_cents']=item['quantity']*item['unit_price_cents']
            item['unit_calories_kcal']=dish['calories_kcal']
            item['line_calories_kcal']=item['quantity']*dish['calories_kcal']
        return dict(items=items,revision=row['revision'] if row else 0,currency='SGD',
                    total_cents=sum(i['line_total_cents'] for i in items),count=sum(i['quantity'] for i in items),
                    total_calories_kcal=sum(i['line_calories_kcal'] for i in items))

    def cart(self,sid):
        with self.db() as db:return self._cart(db,sid)

    def change(self,sid,action,dish_id,quantity=1,options=None,item_id=None):
        if action not in ('add','update','remove'):raise BusinessError('Unknown cart action')
        if action=='remove':
            with self.db() as db:
                cart=self._cart(db,sid)
                matches=[i for i in cart['items'] if (i['id']==item_id if item_id else i['dish_id']==dish_id)]
                if not matches:raise BusinessError('Cart item not found. Refresh your table and try again.')
                ids={i['id'] for i in matches}
                items=[i for i in cart['items'] if i['id'] not in ids]
                db.execute('INSERT INTO carts VALUES(?,?,?) ON CONFLICT(sid) DO UPDATE SET revision=excluded.revision,items=excluded.items',
                           (sid,cart['revision']+1,json.dumps(items)))
                return self._cart(db,sid)
        if type(quantity) is not int or not 0<=quantity<=20:raise BusinessError('Quantity must be an integer from 0 to 20')
        if dish_id not in BY_ID:raise BusinessError('Unknown dish')
        dish=BY_ID[dish_id];options=options or {}
        if action!='remove':
            if not dish['available']:raise BusinessError('This dish is sold out')
            if not isinstance(options,dict):raise BusinessError('Invalid dish options')
            for key,value in options.items():
                if key not in dish['options'] or value not in dish['options'][key]:raise BusinessError('Invalid '+key+' option')
            if 'doneness' in dish['options'] and 'doneness' not in options:raise BusinessError('Choose a steak doneness first')
        line_id=dish_id+'-'+hashlib.sha256(json.dumps(options,sort_keys=True).encode()).hexdigest()[:8]
        with self.db() as db:
            cart=self._cart(db,sid);items=cart['items'];target=next((i for i in items if i['id']==(item_id or line_id)),None)
            if action=='remove':
                items=[i for i in items if (i['id']!=item_id if item_id else i['dish_id']!=dish_id)]
            elif action=='update':
                if not target:raise BusinessError('Cart item not found')
                target['quantity']=quantity
                items=[i for i in items if i['quantity']>0]
            elif quantity>0:
                if target:target['quantity']+=quantity
                else:items.append(dict(id=line_id,dish_id=dish_id,quantity=quantity,options=options))
            if any(i['quantity']>20 for i in items):raise BusinessError('Maximum quantity is 20 per item')
            db.execute('INSERT INTO carts VALUES(?,?,?) ON CONFLICT(sid) DO UPDATE SET revision=excluded.revision,items=excluded.items',
                       (sid,cart['revision']+1,json.dumps(items)))
            return self._cart(db,sid)

    def quote(self,sid):
        with self.db() as db:
            cart=self._cart(db,sid)
            if not cart['items']:raise BusinessError('Your cart is empty')
            for item in cart['items']:
                if not BY_ID[item['dish_id']]['available']:raise BusinessError('A selected dish is no longer available')
            token=secrets.token_urlsafe(24);idem=str(uuid.uuid4());expires=time.time()+600
            db.execute('INSERT INTO quotes VALUES(?,?,?,?,?)',(token,sid,cart['revision'],expires,idem))
            return dict(**cart,confirmation_token=token,idempotency_key=idem,expires_at=expires)

    def place(self,sid,token,idem,explicit_confirm=False):
        if not explicit_confirm:raise BusinessError('Click Confirm Order before submitting')
        if not token or not idem:raise BusinessError('Missing order confirmation')
        with self.db() as db:
            existing=db.execute('SELECT payload FROM orders WHERE sid=? AND idem=?',(sid,idem)).fetchone()
            if existing:return json.loads(existing['payload'])
            quote=db.execute('SELECT * FROM quotes WHERE token=? AND sid=?',(token,sid)).fetchone()
            if not quote or quote['expires']<time.time() or quote['idempotency_key']!=idem:raise BusinessError('Quote expired or invalid; checkout again')
            cart=self._cart(db,sid)
            if quote['revision']!=cart['revision']:raise BusinessError('Cart changed; review a new quote')
            if not cart['items']:raise BusinessError('Your cart is empty')
            order=dict(**cart,order_id='MAI-'+uuid.uuid4().hex[:8].upper(),status='Demo Order',created_at=time.time())
            db.execute('INSERT INTO orders VALUES(?,?,?,?)',(order['order_id'],sid,idem,json.dumps(order)))
            db.execute('UPDATE carts SET items=?,revision=revision+1 WHERE sid=?',('[]',sid))
            return order

    def orders(self,sid):
        with self.db() as db:return [json.loads(r[0]) for r in db.execute('SELECT payload FROM orders WHERE sid=?',(sid,))]

    def availability(self,date,start_time,end_time,party_size):
        window=reservation_window(date,start_time,end_time,party_size)
        with self.db() as db:
            occupied={row[0] for row in db.execute('SELECT table_id FROM reservations WHERE starts<? AND ends>?',(window['ends_at'],window['starts_at']))}
        return {**window,'tables':[table for table in TABLES if table['seats']>=party_size and table['id'] not in occupied]}

    def reserve(self,sid,date,start_time,end_time,party_size,table_id,idem,explicit_confirm=False):
        if not explicit_confirm:raise BusinessError('Choose a table and click Confirm Reservation first')
        if not isinstance(idem,str) or not 8<=len(idem)<=100:raise BusinessError('Missing reservation confirmation key')
        with self.db() as db:
            existing=db.execute('SELECT payload FROM reservations WHERE sid=? AND idem=?',(sid,idem)).fetchone()
            if existing:
                saved=json.loads(existing['payload'])
                if any(saved[key]!=value for key,value in {'date':date,'start_time':start_time,'end_time':end_time,'party_size':party_size,'table_id':table_id}.items()):raise BusinessError('Reservation confirmation does not match; check availability again')
                return saved
            window=reservation_window(date,start_time,end_time,party_size)
            table=next((table for table in TABLES if table['id']==table_id),None)
            if not table or table['seats']<party_size:raise BusinessError('Choose a table with enough seats')
            clash=db.execute('SELECT 1 FROM reservations WHERE table_id=? AND starts<? AND ends>?',(table_id,window['ends_at'],window['starts_at'])).fetchone()
            if clash:raise BusinessError('That table has just been booked. Check availability again.')
            booking={**window,'reservation_id':'RES-'+uuid.uuid4().hex[:8].upper(),'table_id':table_id,'seats':table['seats'],'status':'Demo reservation'}
            db.execute('INSERT INTO reservations VALUES(?,?,?,?,?,?,?)',(booking['reservation_id'],sid,idem,table_id,window['starts_at'],window['ends_at'],json.dumps(booking)))
            return booking

    def reservations(self,sid):
        with self.db() as db:return [json.loads(row[0]) for row in db.execute('SELECT payload FROM reservations WHERE sid=? ORDER BY starts',(sid,))]

