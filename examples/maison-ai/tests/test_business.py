from collections import Counter
from concurrent.futures import ThreadPoolExecutor
import pytest
from backend.store import MENU,BusinessError
from backend.tools import get_menu,recommend_dishes

def test_fixture_and_dietary_constraints():
    assert Counter(d['category'] for d in MENU)==dict(appetizer=4,main=7,pasta_pizza=5,dessert=4,drink=4)
    result=get_menu(dietary_preferences=['vegetarian'])
    assert result['source']=='backend/data/menu.json'
    assert result['dishes'] and all(d['vegetarian'] and d['available'] for d in result['dishes'])
    from backend.recommendations import candidates
    matches=candidates(3,['vegan'])['candidates']
    assert matches and all(d['vegan'] for d in matches)
    form=recommend_dishes(3,['vegan'])
    assert form['ui_request']=='recommendation_filters' and form['recommendation']['candidates']==[]

def test_menu_rejects_mistyped_category_and_preference():
    assert 'error' in get_menu(category='vegetarian')
    assert 'error' in get_menu(dietary_preferences=['vegeterian'])
    dishes=get_menu(category='main',dietary_preferences=['vegetarian'])['dishes']
    assert dishes and all(d['category']=='main' and d['vegetarian'] for d in dishes)

def test_server_money_and_session_isolation(store):
    store.change('alice','add','tiramisu',2)
    assert store.cart('alice')['total_cents']==2400
    assert store.cart('bob')['items']==[]
    store.change('alice','update','tiramisu',1)
    assert store.cart('alice')['total_cents']==1200
    store.change('alice','remove','tiramisu')
    assert store.cart('alice')['count']==0

def test_steak_requires_supported_doneness(store):
    with pytest.raises(BusinessError,match='doneness'):store.change('alice','add','ribeye')
    with pytest.raises(BusinessError):store.change('alice','add','ribeye',options={'doneness':'raw'})
    store.change('alice','add','ribeye',options={'doneness':'medium-rare','side':'salad'})
    assert store.cart('alice')['total_cents']==4200

@pytest.mark.parametrize('dish,quantity,options',[('chocolate',1,{}),('tiramisu',-1,{}),('tiramisu',1,{'price':'0'}),('missing',1,{})])
def test_rejects_invalid_cart_inputs(store,dish,quantity,options):
    with pytest.raises(BusinessError):store.change('alice','add',dish,quantity,options)

def test_confirmation_and_idempotency(store):
    store.change('alice','add','tiramisu',2);q=store.quote('alice')
    args=('alice',q['confirmation_token'],q['idempotency_key'])
    with pytest.raises(BusinessError,match='Confirm'):store.place(*args)
    with ThreadPoolExecutor(2) as pool:
        orders=list(pool.map(lambda _:store.place(*args,True),range(2)))
    assert orders[0]['order_id']==orders[1]['order_id']
    assert len(store.orders('alice'))==1 and orders[0]['total_cents']==2400
    assert store.cart('alice')['count']==0

def test_quote_rejects_changed_cart_and_cross_session(store):
    store.change('alice','add','tiramisu');q=store.quote('alice')
    with pytest.raises(BusinessError):store.place('bob',q['confirmation_token'],q['idempotency_key'],True)
    store.change('alice','add','cheesecake')
    with pytest.raises(BusinessError,match='Cart changed'):store.place('alice',q['confirmation_token'],q['idempotency_key'],True)

