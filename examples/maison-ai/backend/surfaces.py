"""Composed A2UI checkout, nutrition, recommendation and reservation surfaces."""
from .config import CATALOG_ID,PROTOCOL_VERSION

def surface(sid,components,data=None):
    return {'a2ui_operations':[
        {'version':PROTOCOL_VERSION,'createSurface':{'surfaceId':sid,'catalogId':CATALOG_ID}},
        {'version':PROTOCOL_VERSION,'updateComponents':{'surfaceId':sid,'components':components}},
        {'version':PROTOCOL_VERSION,'updateDataModel':{'surfaceId':sid,'path':'/','value':data or {}}},
    ]}

def checkout(quote):
    c=[dict(id='root',component='Card',title='Review your order',subtitle='A demo order. No payment required.',child='body'),
       dict(id='body',component='Column',children=['lines','energy','total','confirm']),
       dict(id='lines',component='Column',children=['line-'+str(n) for n in range(len(quote['items']))]),
       dict(id='total',component='CartTotal',totalCents=quote['total_cents']),
       dict(id='energy',component='NutritionTotal',totalKcal=quote['total_calories_kcal'],partySize=1,showSplit=False),
       dict(id='confirm',component='Button',label='Confirm Order',action={'name':'confirm_order','context':{'confirmation_token':quote['confirmation_token'],'idempotency_key':quote['idempotency_key']}})]
    for n,item in enumerate(quote['items']):
        c.append(dict(id='line-'+str(n),component='Text',text=f"{item['quantity']} × {item['name']} — S$ {item['line_total_cents']/100:.2f} · {item['line_calories_kcal']} kcal"))
    return surface('order-review',c,quote)

def success(order):
    return surface('order-success',[dict(id='root',component='Card',title='Your order is in.',subtitle='Demo Order · no payment collected',child='status'),
        dict(id='status',component='OrderStatus',orderId=order['order_id'],status='Demo Order',totalCents=order['total_cents'])],order)

def cart_view(cart):
    """A live cart surface built from trusted line items and small components."""
    nodes=[dict(id='root',component='Column',children=['heading','items','total']),
        dict(id='heading',component='Text',text=f"Your table · {cart['count']} items"),
        dict(id='items',component='Row',children=[]),
        dict(id='total',component='CartTotal',totalCents=cart['total_cents'])]
    for item in cart['items']:
        key=item['id'];body=key+'-body'
        nodes[2]['children'].append(key)
        options=' · '.join(value.replace('-',' ') for value in item.get('options',{}).values())
        nodes.extend([dict(id=key,component='Card',title=item['name'],child=body),
            dict(id=body,component='Column',children=[key+'-photo',key+'-price',key+'-detail',key+'-controls']),
            dict(id=key+'-photo',component='DishImage',dishId=item['dish_id']),
            dict(id=key+'-price',component='PriceBadge',dishId=item['dish_id']),
            dict(id=key+'-detail',component='Text',text=options or 'Made for your table.'),
            dict(id=key+'-controls',component='CartItemControls',itemId=key,dishId=item['dish_id'],quantity=item['quantity'],options=item.get('options',{}))])
    if cart['items']:
        nodes[0]['children'].append('checkout')
        nodes.append(dict(id='checkout',component='Button',label='Checkout',action={'name':'checkout'}))
    else:
        nodes.append(dict(id='empty',component='Text',text='Your table is empty. Browse Menu to choose a dish.'))
        nodes[0]['children'].insert(1,'empty')
    return surface('cart-view',nodes,cart)

def mock_menu(dishes,sid='mock-menu',doneness=None):
    nodes=[dict(id='root',component='Column',children=['heading','grid']),dict(id='heading',component='Text',text='A few things you might love.'),dict(id='grid',component='Row',children=[])]
    for d in dishes:
        key=d['id'];children=[key+'-photo',key+'-price',key+'-tags',key+'-description']
        nodes.extend([dict(id=key+'-photo',component='DishImage',dishId=key,src=d['image'],alt=d['name']),
          dict(id=key+'-price',component='PriceBadge',dishId=key),
          dict(id=key+'-tags',component='DietaryBadge',vegetarian=d['vegetarian'],vegan=d['vegan']),
          dict(id=key+'-description',component='Text',text=d['description'])])
        for option,choices in d['options'].items():
            id=key+'-'+option;children.append(id)
            nodes.append(dict(id=id,component='DishOptionSelector',dishId=key,option=option,choices=choices,value=doneness if option=='doneness' and doneness else choices[0]))
        children += [key+'-quantity',key+'-add']
        nodes.extend([dict(id=key+'-quantity',component='QuantitySelector',dishId=key,value=1),
          dict(id=key+'-add',component='Button',label='Add to cart',action={'name':'add_to_cart','context':{'dish_id':key}}),
          dict(id=key+'-body',component='Column',children=children),dict(id=key,component='Card',title=d['name'],child=key+'-body')])
        nodes[2]['children'].append(key)
    return surface(sid,nodes)

def calorie_summary(cart,party_size=1):
    nodes=[dict(id='root',component='Card',title='Calories at your table',subtitle='Recipe estimates based on the selected portions.',child='body'),
        dict(id='body',component='Column',children=['controls','lines','energy','price']),
        dict(id='controls',component='CalorieControls',partySize=party_size),
        dict(id='lines',component='Column',children=[]),
        dict(id='energy',component='NutritionTotal',totalKcal=cart['total_calories_kcal'],partySize=party_size,showSplit=True),
        dict(id='price',component='CartTotal',totalCents=cart['total_cents'])]
    for n,item in enumerate(cart['items']):
        key=f'calorie-line-{n}';nodes[3]['children'].append(key)
        nodes.append(dict(id=key,component='Text',text=f"{item['quantity']} × {item['name']} · {item['unit_calories_kcal']} kcal / portion · {item['line_calories_kcal']} kcal total"))
    if not cart['items']:
        nodes[3]['children'].append('empty')
        nodes.append(dict(id='empty',component='Text',text='Your cart is empty. Add dishes to calculate your meal.'))
    return surface('calorie-summary',nodes,cart)

def recommendations(result,show_results=False):
    filters={key:result[key] for key in ('party_size','dietary_preferences','budget','max_calories','excluded_allergens','allergen_options')}
    nodes=[dict(id='root',component='Column',children=['filters','summary','grid']),
        dict(id='filters',component='RecommendationFilters',partySize=filters['party_size'],dietaryPreferences=filters['dietary_preferences'],budget=filters['budget'],maxCalories=filters['max_calories'],excludedAllergens=filters['excluded_allergens'],allergenOptions=filters['allergen_options']),
        dict(id='summary',component='Text',text=f"{len(result['candidates'])} matching dishes for {result['party_size']} diners. Each card is a choice; adding every card is not a meal plan."),
        dict(id='grid',component='Row',children=[])]
    if not show_results:
        nodes[0]['children']=['filters']
        return surface('recommendations',nodes[:2],{**filters,'candidates':[]})
    nodes[0]['children']=['summary','grid']
    for dish in result['candidates']:
        key='rec-'+dish['id'];children=[key+'-photo',key+'-price',key+'-tags',key+'-servings']
        nodes[3]['children'].append(key)
        nodes.extend([dict(id=key,component='Card',title=dish['name'],child=key+'-body'),
            dict(id=key+'-photo',component='DishImage',dishId=dish['id']),dict(id=key+'-price',component='PriceBadge',dishId=dish['id']),
            dict(id=key+'-tags',component='DietaryBadge',vegetarian=dish['vegetarian'],vegan=dish['vegan']),
            dict(id=key+'-servings',component='ServingInfo',dishId=dish['id'],recommendedQuantity=dish['recommended_quantity'],partySize=result['party_size'])])
        for option,choices in dish['options'].items():
            id=key+'-'+option;children.append(id)
            nodes.append(dict(id=id,component='DishOptionSelector',dishId=dish['id'],option=option,choices=choices,value='' if option=='doneness' else choices[0]))
        children.extend([key+'-quantity',key+'-add'])
        nodes.extend([dict(id=key+'-quantity',component='QuantitySelector',dishId=dish['id'],value=dish['recommended_quantity']),
            dict(id=key+'-add',component='Button',label='Add to table',action={'name':'add_to_cart','context':{'dish_id':dish['id'],'quantity':dish['recommended_quantity']}}),
            dict(id=key+'-body',component='Column',children=children)])
    if not result['candidates']:
        nodes[0]['children'].append('empty')
        nodes.append(dict(id='empty',component='Text',text='No dishes meet all filters. Adjust the calorie limit, budget or dietary preferences.'))
    return surface('recommendations',nodes,result)

def reservation_form(date='',start_time='18:00',end_time='20:00',party_size=2):
    from datetime import datetime,timedelta
    from .store import RESTAURANT_TIMEZONE
    today=datetime.now(RESTAURANT_TIMEZONE).date()
    return surface('reservation-form',[
        dict(id='root',component='Card',title='Reserve your table',subtitle='Choose a date, time window and number of guests.',child='form'),
        dict(id='form',component='ReservationForm',date=date or (today+timedelta(days=1)).isoformat(),minDate=today.isoformat(),startTime=start_time or '18:00',endTime=end_time or '20:00',partySize=party_size)])

def reservation_availability(result):
    import uuid
    form=reservation_form(result['date'],result['start_time'],result['end_time'],result['party_size'])
    nodes=form['a2ui_operations'][1]['updateComponents']['components']
    nodes[0]['child']='body'
    nodes.extend([dict(id='body',component='Column',children=['form','availability','tables']),
        dict(id='availability',component='Text',text=f"{len(result['tables'])} tables available · {result['date']} · {result['start_time']}–{result['end_time']} · {result['party_size']} guests. Availability is checked again when you confirm."),
        dict(id='tables',component='Row',children=[])])
    for table in result['tables']:
        key='table-'+table['id']
        next(node for node in nodes if node['id']=='tables')['children'].append(key)
        context={key:result[key] for key in ('date','start_time','end_time','party_size')}
        context.update(table_id=table['id'],idempotency_key=str(uuid.uuid4()))
        nodes.extend([dict(id=key,component='Card',title=f"Table {table['id']}",subtitle=f"{table['seats']} seats",child=key+'-confirm'),
            dict(id=key+'-confirm',component='Button',label='Confirm Reservation',action={'name':'confirm_reservation','context':context})])
    if not result['tables']:
        nodes.append(dict(id='empty',component='Text',text='No table fits this time and party size. Try another time window.'))
        next(node for node in nodes if node['id']=='body')['children'].append('empty')
    return surface('reservation-availability',nodes,result)

def reservation_success(booking):
    return surface('reservation-success',[dict(id='root',component='Card',title='Your table is reserved',subtitle='Demo reservation · saved locally',child='status'),
        dict(id='status',component='ReservationStatus',reservationId=booking['reservation_id'],tableId=booking['table_id'],date=booking['date'],startTime=booking['start_time'],endTime=booking['end_time'],partySize=booking['party_size'],seats=booking['seats'])],booking)

