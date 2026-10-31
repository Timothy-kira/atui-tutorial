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
        if not responses:
            lower=text.lower()
            party=re.search(r'(?:for\s+|party of\s+)(\d+)',lower)
            people=int(party.group(1)) if party else 4 if 'four' in lower else 2
            from .store import MENU
            detail=any(word in lower for word in ('ingredient',"what's in",'what’s in','allergen','calories','食材','成分'))
            dish=next((d for d in MENU if d['name'].lower() in lower or d['id'].replace('-',' ') in lower or ('lemonade' in lower and 'lemonade' in d['name'].lower()) or ('chicken' in lower and 'chicken' in d['name'].lower())),None)
            if detail and dish:name,args=call('get_dish_details',{'dish_id':dish['id']})
            elif any(word in lower for word in ('reserv','book a table','预定','預訂','预订')):name,args=call('show_reservation',{'party_size':people})
            elif any(word in lower for word in ('checkout','check out','结账','結帳')):name='quote_order'
            elif any(word in lower for word in ('calori','kcal','热量','熱量')) and not any(word in lower for word in ('recommend','under','below','推荐')):name,args=call('calculate_total_calories',{'party_size':people})
            elif any(word in lower for word in ('recommend','under','below','推荐')):
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
        elif responses[-1].response.get('error'):
            reply=str(responses[-1].response['error'])
        elif responses[-1].response.get('ui_request') or (responses[-1].name=='get_dish_details' and not any(r.name=='ask_user' for r in responses)):
            name='mock_show_workflow'
        elif responses[-1].name in ('get_menu','get_dish_details'):
            result=responses[-1].response
            dishes=result.get('dishes',[result])
            answer=next((r.response for r in responses if r.name=='ask_user'),{})
            raw=answer.get('result',answer)
            if isinstance(raw,str):
                try:raw=json.loads(raw)
                except ValueError:raw={'selection':raw}
            name,args=call('mock_show_menu',{'dish_ids':[d['id'] for d in dishes[:6]],'doneness':raw.get('selection','') if isinstance(raw,dict) else ''})
        elif responses[-1].response.get('assistant_message'):
            reply=responses[-1].response['assistant_message']
        if name:
            part=types.Part(function_call=types.FunctionCall(id='mock-'+uuid.uuid4().hex[:12],name=name,args=args))
        else:part=types.Part(text=reply)
        yield LlmResponse(content=types.Content(role='model',parts=[part]),partial=False)

