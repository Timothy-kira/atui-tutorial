"""A labelled, scripted BaseLlm for offline workshops; ADK still executes tools."""
import json,uuid,re
from google.adk.models.base_llm import BaseLlm
from google.adk.models.llm_response import LlmResponse
from google.genai import types

class WorkshopModel(BaseLlm):
    model: str='maison/mock-scripted'
    async def generate_content_async(self,llm_request,stream=False):
        contents=llm_request.contents
        start=max((i for i,c in enumerate(contents) if any(getattr(p,'text',None) for p in c.parts or []) and c.role=='user'),default=0)
        tail=contents[start:]
        text=' '.join(p.text for c in tail[:1] for p in c.parts or [] if getattr(p,'text',None))
        responses=[p.function_response for c in tail for p in c.parts or [] if getattr(p,'function_response',None)]
        name='';args={};reply='Here you go. This is the scripted Mock Mode demonstration.'
        def call(n,a): return n,a
        try: action=json.loads(text).get('a2uiAction')
        except (ValueError,AttributeError): action=None
        if action:
            if not responses:
                ctx=action.get('context',{});kind=action.get('name')
                if kind in ('add_to_cart','update_item','remove_item'):
                    name,args=call('update_cart',dict(action={'add_to_cart':'add','update_item':'update','remove_item':'remove'}[kind],dish_id=ctx.get('dish_id',''),quantity=ctx.get('quantity',1),options=ctx.get('options',{}),item_id=ctx.get('item_id','')))
                elif kind=='checkout':name='quote_order'
                elif kind=='confirm_order':name,args=call('place_order',ctx)
                elif kind=='calculate_calories':name,args=call('calculate_total_calories',{'party_size':ctx.get('party_size',1)})
                elif kind=='recommend_dishes':name,args=call('recommend_dishes',{key:ctx[key] for key in ('party_size','dietary_preferences','budget','max_calories','excluded_allergens') if key in ctx})
                elif kind=='open_reservation':name,args=call('show_reservation',{key:ctx[key] for key in ('date','start_time','end_time','party_size') if key in ctx})
                elif kind=='check_reservation':name,args=call('check_reservation',{key:ctx[key] for key in ('date','start_time','end_time','party_size') if key in ctx})
                elif kind=='confirm_reservation':name,args=call('reserve_table',{key:ctx[key] for key in ('date','start_time','end_time','party_size','table_id','idempotency_key') if key in ctx})
            else: reply='Your cart is updated.'
        elif not responses:
            lower=text.lower()
            party=re.search(r'(?:for\s+|party of\s+)(\d+)',lower)
            people=int(party.group(1)) if party else 4 if 'four' in lower else 2
            if any(word in lower for word in ('reserv','book a table','预定','預訂','预订')):name,args=call('show_reservation',{'party_size':people})
            elif any(word in lower for word in ('checkout','check out','结账','結帳')):name='quote_order'
            elif any(word in lower for word in ('calori','kcal','热量','熱量')) and not any(word in lower for word in ('recommend','under','below','推荐')):name,args=call('calculate_total_calories',{'party_size':people})
            elif any(word in lower for word in ('recommend','vegetarian','vegan','allerg','under','推荐')):
                limit=re.search(r'(\d+)\s*(?:kcal|calories)',lower)
                budget=re.search(r'(?:s\$|\$)\s*(\d+(?:\.\d+)?)',lower)
                diets=['vegan'] if 'vegan' in lower else ['vegetarian'] if 'vegetarian' in lower else []
                excluded=[value for value in ('milk','egg','gluten','nuts','fish','shellfish','sesame') if re.search(r'(?:no|without|exclude|allergic to)\s+'+value,lower)]
                name,args=call('recommend_dishes',{'party_size':people,'dietary_preferences':diets,'max_calories':int(limit.group(1)) if limit else 0,'budget':float(budget.group(1)) if budget else 0,'excluded_allergens':excluded})
            elif 'steak' in lower:name,args=call('ask_user',dict(question='How would you like your steak?',options=['rare','medium-rare','medium','well-done']))
            else:name,args=call('get_menu',dict(category='dessert' if any(w in text.lower() for w in ['sweet','dessert']) else '',dietary_preferences=['vegetarian'] if 'vegetarian' in text.lower() else []))
        elif responses[-1].name=='ask_user':
            result=responses[-1].response
            if 'cancel' not in json.dumps(result).lower():name,args=call('get_dish_details',{'dish_id':'ribeye'})
            else:reply='No problem. We can choose something else.'
        elif responses[-1].name in ('get_menu','get_dish_details'):
            result=responses[-1].response
            dishes=result.get('dishes',[result])
            answer=next((r.response for r in responses if r.name=='ask_user'),{})
            raw=answer.get('result',answer)
            if isinstance(raw,str):
                try:raw=json.loads(raw)
                except ValueError:raw={'selection':raw}
            name,args=call('mock_show_menu',{'dish_ids':[d['id'] for d in dishes[:6]],'doneness':raw.get('selection','') if isinstance(raw,dict) else ''})
        if name:
            part=types.Part(function_call=types.FunctionCall(id='mock-'+uuid.uuid4().hex[:12],name=name,args=args))
        else:part=types.Part(text=reply)
        yield LlmResponse(content=types.Content(role='model',parts=[part]),partial=False)

