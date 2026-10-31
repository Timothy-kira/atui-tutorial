"""Agent-authored component graphs, validated against the actual React catalog.

This tool never selects a page template. It validates what the model composed,
then transports that graph through A2UI v0.9.
"""
import json,re,uuid,logging,asyncio
import httpx
from litellm.exceptions import APIError
from pathlib import Path
from google.adk.tools import BaseTool
from google.genai import types
from jsonschema import Draft202012Validator
from .config import CATALOG_ID,PROTOCOL_VERSION
from .store import BY_ID
from ag_ui_adk.a2ui_google_sdk import heal_json_arg

CATALOG=json.loads((Path(__file__).parent/'data/ui-catalog.json').read_text(encoding='utf-8'))
SCHEMAS={key:value for key,value in CATALOG['components'].items() if key!='Skeleton'}

class GraphError(ValueError):
    def __init__(self,message,repair):
        super().__init__(message)
        self.repair=repair

def trusted_data(context):
    """Business values come from tools/store, never a model-authored data copy."""
    from .tools import store
    data={};dishes={}
    for record in context.state.get('_ui_records',[]):
        if not record.get('error'):data.pop('error',None)
        for key in ('quote','recommendation','availability','order','reservation','date','start_time','end_time','party_size','error'):
            if key in record:data[key]=record[key]
        for dish in record.get('dishes',[]):dishes[dish['id']]=dish
        if record.get('id') in BY_ID:dishes[record['id']]=record
        for dish in record.get('recommendation',{}).get('candidates',[]):dishes[dish['id']]=dish
    data['cart']=store.cart(context.state['maison_thread'])
    records=context.state.get('_ui_records',[])
    data['latest_result']=records[-1] if records else {}
    data['dishes']=list(dishes.values());data['dish_by_id']=dishes
    allergens=data.get('recommendation',{}).get('allergen_options',[])
    data['choices']={'allergens':[{'label':value.title(),'value':value} for value in allergens],
        'diets':[{'label':'Vegetarian','value':'vegetarian'},{'label':'Vegan','value':'vegan'}]}
    quote=data.get('quote')
    if quote and quote.get('revision')!=data['cart']['revision']:data.pop('quote')
    return data

def _inline_refs(value,root):
    if isinstance(value,dict):
        if '$ref' in value:
            target=root
            for key in value['$ref'].removeprefix('#/').split('/'):
                key=key.replace('~1','/').replace('~0','~')
                target=target[int(key)] if isinstance(target,list) else target[key]
            return _inline_refs(target,root)
        return {key:_inline_refs(item,root) for key,item in value.items()}
    if isinstance(value,list):return [_inline_refs(item,root) for item in value]
    return value
TOOL_COMPONENT_SCHEMAS=[_inline_refs(schema,schema) for schema in SCHEMAS.values()]

def parse_argument(value,expect):
    fenced=re.fullmatch(r'```(?:json)?\s*([\s\S]*?)\s*```',value.strip(),flags=re.IGNORECASE)
    return heal_json_arg(fenced.group(1) if fenced else value,expect=expect)

def _resolve(value,data):
    if isinstance(value,dict):
        if set(value)=={'path'}:
            current=data
            for key in value['path'].lstrip('/').split('/'):
                key=key.replace('~1','/').replace('~0','~')
                current=current[int(key)] if isinstance(current,list) else current[key]
            return current
        if 'call' in value:raise ValueError('Client function calls are not enabled in this catalog; use literal values or data paths')
        return {key:_resolve(item,data) for key,item in value.items()}
    if isinstance(value,list):return [_resolve(item,data) for item in value]
    return value

def validate_graph(components,data,context):
    if not isinstance(components,list) or not 1<=len(components)<=80:raise ValueError('Provide 1–80 components')
    normalized=[]
    for original in components:
        node=dict(original)
        component=node.get('component')
        if isinstance(component,dict) and len(component)==1:
            name,props=next(iter(component.items()))
            if isinstance(props,dict):node={**props,**node,'component':name}
        props=node.pop('props',None)
        if props is not None:
            if not isinstance(props,dict):raise ValueError('Component props must be an object')
            if set(props)&set(node):raise ValueError('Duplicate flat and nested component properties')
            node={**node,**props}
        if node.get('component') in {'Row','Column','Form'} and 'children' not in node and isinstance(node.get('child'),str):node['children']=[node.pop('child')]
        normalized.append(node)
    components=normalized
    if len(json.dumps([components,data]))>100_000:raise ValueError('Interface payload is too large')
    ids=[node.get('id') for node in components]
    if len(set(ids))!=len(ids) or 'root' not in ids:raise ValueError('Component IDs must be unique and include root')
    edges={};resolved=[]
    from .tools import store
    cart=store.cart(context.state['maison_thread'])
    records=context.state.get('_ui_records',[])
    totals={cart['total_cents']};calories={cart['total_calories_kcal']}
    for record in records:
        for key in ('quote','cart','order'):
            facts=record.get(key,{})
            if 'total_cents' in facts:totals.add(facts['total_cents'])
            if 'total_calories_kcal' in facts:calories.add(facts['total_calories_kcal'])
    for node in components:
        name=node.get('component');schema=SCHEMAS.get(name)
        if schema is None:raise ValueError(f'Unknown component {name}. Use the provided catalog')
        value=_resolve(node,data)
        errors=list(Draft202012Validator(schema).iter_errors(value))
        if errors:raise ValueError(f"{node.get('id')}: {errors[0].message}")
        resolved.append(value)
        dish_id=value.get('dishId')
        if dish_id is not None and dish_id not in BY_ID:raise GraphError(f"{node['id']}.dishId is not an actual ID",{'node':node['id'],'property':'dishId','actual':str(dish_id)[:120],'allowed_dishes':[{'id':key,'name':dish['name']} for key,dish in BY_ID.items()]})
        if name=='CartTotal' and value['totalCents'] not in totals:raise ValueError('CartTotal must match an actual cart, quote or order result')
        if name=='NutritionTotal' and value['totalKcal'] not in calories:raise ValueError('NutritionTotal must match the actual cart or quote calorie total')
        if name=='CartItemControls' and not any(item['id']==value['itemId'] and item['dish_id']==dish_id and item['quantity']==value['quantity'] and item['options']==value['options'] for item in cart['items']):raise ValueError('Cart item controls must match a current server cart line')
        if name=='Button':
            from .actions import UIActionInput
            aliases={'dishId':'dish_id','itemId':'item_id','partySize':'party_size','confirmationToken':'confirmation_token','idempotencyKey':'idempotency_key','startTime':'start_time','endTime':'end_time','tableId':'table_id'}
            fields=value['action'].get('context') or {}
            normalized={aliases.get(key,key):item for key,item in fields.items()}
            if len(normalized)!=len(fields):raise ValueError('Duplicate action context fields; use snake_case field names')
            value['action']['context']=normalized
            action=UIActionInput.model_validate(value['action'])
            if action.name in {'add_to_cart','update_item','remove_item'} and action.context.dish_id not in BY_ID:raise GraphError(f"{node['id']}.action.context.dish_id must be an actual ID",{'node':node['id'],'property':'action.context.dish_id','actual':action.context.dish_id,'allowed_dishes':[{'id':key,'name':dish['name']} for key,dish in BY_ID.items()]})
            if action.name=='confirm_order':
                quote=next((record['quote'] for record in reversed(records) if record.get('quote')),None)
                if not quote:raise ValueError('Confirmation needs an actual quote_order result first')
                if action.context.confirmation_token!=quote['confirmation_token'] or action.context.idempotency_key!=quote['idempotency_key']:raise GraphError(f"{node['id']}.action.context must use server quote bindings",{'node':node['id'],'context':{key:{'path':'/quote/'+key} for key in ('confirmation_token','idempotency_key')}})
        if name=='DataTable' and any(len(row)!=len(value['columns']) for row in value['rows']):raise ValueError('Each table row must match the number of columns')
        edges[value['id']]=[*value.get('children',[]),*value.get('footerChildren',[]),*([value['child']] if value.get('child') else [])]
    visited=set();active=set()
    def walk(key):
        if key not in edges:raise ValueError(f'Missing referenced component {key}')
        if key in active:raise ValueError('The component graph contains a cycle')
        if key in visited:return
        active.add(key)
        for child in edges[key]:walk(child)
        active.remove(key);visited.add(key)
    walk('root')
    if visited!=set(ids):raise ValueError('Every component must be reachable from root')
    by_id={node['id']:node for node in resolved}
    for node in resolved:
        if node['component']!='Form':continue
        pending=list(edges[node['id']]);seen=set()
        while pending:
            key=pending.pop()
            if key in seen:continue
            seen.add(key);child=by_id[key]
            if child['component']=='Form':raise ValueError('Forms cannot be nested')
            if child['component']=='Button' and child['action']['name']==node['action']:
                raise GraphError('Form already renders its submit button; remove the duplicate child Button',{'form':node['id'],'remove_component':key})
            pending.extend(edges[key])
    return resolved

class RenderInterfaceTool(BaseTool):
    def __init__(self):
        super().__init__(name='render_a2ui',description='Create a real interactive interface inline in the conversation. YOU compose the component graph; there are no preselected page templates. Read business facts first, then choose and arrange catalog components. Also callable for corrections, explanations, comparisons or recoverable tool errors. An ordinary text promise does not display any UI.')

    def _get_declaration(self):
        return types.FunctionDeclaration(name=self.name,description=self.description,parameters_json_schema={
            'type':'object','properties':{
                'components_json':{'type':'string','description':'JSON-encoded NONEMPTY array of component objects. Each object needs id, component and its catalog props. Root id is root. Example: [{"id":"root","component":"Column","children":["note"]},{"id":"note","component":"Text","text":"Choose your preferences."}]. Compose the requested graph yourself; do not submit an empty array.'},
                'data_json':{'type':'string','description':'Optional JSON-encoded object for data bindings. Literal component props usually need no data object.'},
                'surface_id':{'type':'string','description':'Omit for a new surface. Use an actual returned surface_id to update a previously rendered surface.'},
            },'required':['components_json']})

    async def run_async(self,*,args,tool_context):
        try:
            components=parse_argument(args['components_json'],'list') if 'components_json' in args else args.get('components')
            data=parse_argument(args['data_json'],'dict') if args.get('data_json') else args.get('data') or {}
            if not isinstance(data,dict):raise ValueError('data_json must encode an object')
            nodes=validate_graph(components,data,tool_context)
            sid=args.get('surface_id') or 'generated-'+uuid.uuid4().hex[:12]
            known=dict(tool_context.state.get('_a2ui_surfaces',{}))
            if not re.fullmatch(r'generated-[a-z0-9-]{6,80}',sid) or (args.get('surface_id') and sid not in known):raise ValueError('Use an actual returned surface_id or omit it to create a new interface')
            create=[] if sid in known else [{'version':PROTOCOL_VERSION,'createSurface':{'surfaceId':sid,'catalogId':CATALOG_ID}}]
            operations=[*create,{'version':PROTOCOL_VERSION,'updateComponents':{'surfaceId':sid,'components':nodes}},
                {'version':PROTOCOL_VERSION,'updateDataModel':{'surfaceId':sid,'path':'/','value':data}}]
            known[sid]=[node['id'] for node in nodes]
            tool_context.state['_a2ui_surfaces']=dict(list(known.items())[-30:])
            tool_context.state['_a2ui_rendered_invocation']=tool_context.invocation_id
            return {'surface_id':sid,'a2ui_operations':operations,'ui_context':{'displayed':True,'agent_composed':True,'component_count':len(nodes)}}
        except (ValueError,KeyError,TypeError,IndexError) as exc:
            result={'error':'Interface validation failed','issues':[str(exc)[:500]],'retryable':True,'ui_context':{'displayed':False}}
            if isinstance(exc,GraphError):result['repair_data']=exc.repair
            return result

def catalog_instructions():
    """Keep the planning catalog compact; validation uses the exported full schema."""
    rows=[]
    for name,schema in SCHEMAS.items():
        props={key:value for key,value in schema['properties'].items() if key not in {'id','component'}}
        def shape(prop):
            if '$ref' in prop:return prop['$ref']
            if 'enum' in prop:return '|'.join(map(str,prop['enum']))
            if 'anyOf' in prop:return ' | '.join(shape(item) for item in prop['anyOf'] if not item.get('properties',{}).get('call'))
            if prop.get('type')=='array':return 'array of '+shape(prop.get('items',{}))
            if prop.get('type')=='object':return '{'+', '.join(key+':'+shape(value) for key,value in prop.get('properties',{}).items())+'}' if prop.get('properties') else 'object'
            kind=prop.get('type','value')
            return '|'.join(kind) if isinstance(kind,list) else kind
        rows.append(name+'('+', '.join(key+('' if key in schema['required'] else '?')+': '+shape(value) for key,value in props.items())+')')
    return '\n'.join(rows)

class GenerateInterfaceTool(BaseTool):
    """A model composes JSON, independently of provider tool-argument grammars."""
    def __init__(self,model):
        super().__init__(name='generate_a2ui',description='Generate a real interactive A2UI interface for this request from the actual tool records. A model chooses and composes the component graph; no page template is selected. Also use for comparisons, input corrections and actual business errors. Read business facts first when needed.')
        self._model=model

    def _get_declaration(self):
        return types.FunctionDeclaration(name=self.name,description=self.description,parameters_json_schema={'type':'object','properties':{'request':{'type':'string','description':'Describe what interface the guest needs and which actual business result to use. Include relevant preferences and desired controls.'},'surface_id':{'type':'string','description':'Optional existing surface ID to update. Omit for a new interface.'}},'required':['request']})

    async def run_async(self,*,args,tool_context):
        from google.adk.models.llm_request import LlmRequest
        from .actions import UIActionInput,ActionContext
        guide='''Create an interactive A2UI component graph for the guest request using the authoritative data provided. Return ONLY a JSON object {"components":[...]}. Do not repeat business data in your output.
Nodes are flat objects with id, component and props directly on the node. The root id is root. Row/Column/Form.children and Card.footerChildren are arrays of component ID strings; Card.child is one ID. Every node must be reachable from root. No HTML, CSS or client function calls.
For any business value use a server data binding {"path":"/JSON/pointer"}; the host resolves it before validating/rendering. This also works in static props and action contexts. For example CartTotal.totalCents={"path":"/cart/total_cents"}. Do not copy totals, item IDs or opaque confirmation strings.
For confirmation Button.action.context use confirmation_token={"path":"/quote/confirmation_token"} and idempotency_key={"path":"/quote/idempotency_key"}. Only show Confirm Order if quote exists. This does not place an order until the guest clicks.
For dish nodes, use known IDs or bindings such as dishId={"path":"/dishes/0/id"}, and for add_to_cart context use dish_id={"path":"/dishes/0/id"}. Keep component IDs simple strings you choose. Never invent a dish ID. Put QuantitySelector and add Button IDs in Card.footerChildren. Use a Row for two-column dish cards; at most three compact cards. Details/allergens/calories can be explained in chat; include DishFacts only for a detail request.
For recommendation settings awaiting submission, choose generic Form and Field nodes, not a whole-page template. Form.action=recommend_dishes. Field names use snake_case party_size, budget, max_calories, dietary_preferences, excluded_allergens. Bind initial values to /recommendation/<field>. Use multi fields for array values; options can bind to /choices/diets and /choices/allergens. Do not display candidates before the guest submits.
For actual errors, show a Notice and useful correction controls. An unknown dish in an error is NOT a valid DishImage ID. DataTable may compare actual records. Choose the layout/components yourself; no fixed page template. Keep the graph under 30 nodes and text brief.
Syntax example: {"components":[{"id":"root","component":"Column","children":["info"]},{"id":"info","component":"Notice","severity":"info","message":"Choose your preferences."}]}.
Catalog signatures (optional props marked ?; every business prop may use a server binding):
'''+catalog_instructions()+'\nPermitted action names: '+', '.join(UIActionInput.model_fields['name'].annotation.__args__)+'\nAction context schema: '+json.dumps(ActionContext.model_json_schema(),separators=(',',':'))+'''
Do not invent action names such as view_menu, retry, clear_cart or continue_shopping. If no permitted action fits, show a Notice with a next step in text. A request to keep the cart unchanged does not need remove/update controls. Use Field.type (not kind). Form automatically renders one submit button using submitLabel and collects all descendant Field values; do not include another Button for the same action or nest Forms. Only the latest_result is the result being presented; historical data is available for comparison, not a reason to repeat old forms.
'''
        data=trusted_data(tool_context)
        def describe(value,path=''):
            if isinstance(value,dict):return {key:({'server_binding':path+'/'+key} if key in {'confirmation_token','idempotency_key'} else describe(item,path+'/'+key)) for key,item in value.items()}
            if isinstance(value,list):return [describe(item,path+'/'+str(index)) for index,item in enumerate(value)]
            return value
        prompt=json.dumps({'interface_request':args.get('request',''),'latest_guest_request':tool_context.state.get('maison_guest_request'),'authoritative_data':describe(data)},ensure_ascii=False)
        issues=[]
        for attempt in range(2):
            request=LlmRequest(contents=[types.Content(role='user',parts=[types.Part(text=prompt+('\nCorrect these validation issues from your previous draft: '+json.dumps(issues) if issues else ''))])],config=types.GenerateContentConfig(system_instruction=guide,temperature=0.2,max_output_tokens=4096,response_mime_type='application/json'))
            chunks=[]
            try:
                async with asyncio.timeout(30):
                    async for response in self._model.generate_content_async(request,stream=False):
                        if response.content:chunks.extend(part.text for part in response.content.parts or [] if part.text and not part.thought)
            except (RuntimeError,TimeoutError) as exc:
                if isinstance(exc,RuntimeError) and 'output limit' not in str(exc):raise
                issues=['Generation exceeded its output/time budget. Compose a much smaller graph, at most 20 nodes; use fewer cards and no duplicated detail text.']
                continue
            except (httpx.HTTPError,APIError) as exc:
                logging.getLogger('uvicorn.error').warning('maison_ui_provider_failure type=%s',type(exc).__name__)
                return {'error':'Interface provider is temporarily unavailable','issues':[type(exc).__name__],'retryable':True,'ui_context':{'displayed':False}}
            try:
                document=parse_argument(''.join(chunks),'dict')
                rendered=await RenderInterfaceTool().run_async(args={'components':document.get('components'),'data':{'local':document.get('data') or {},**data},**({'surface_id':args['surface_id']} if args.get('surface_id') else {})},tool_context=tool_context)
                if not rendered.get('error'):return {**rendered,'generation_attempts':attempt+1}
                issues=rendered['issues']+([rendered['repair_data']] if rendered.get('repair_data') else [])
                logging.getLogger('uvicorn.error').warning('maison_ui_schema attempt=%d issues=%s shapes=%s',attempt+1,issues,[{'id':node.get('id'),'component':node.get('component') if isinstance(node.get('component'),str) else 'nested','keys':list(node)} for node in document.get('components',[]) if isinstance(node,dict)][:8])
                prompt+='\nPrevious component draft: '+json.dumps(document,ensure_ascii=False)
            except (ValueError,TypeError,KeyError) as exc:issues=[str(exc)[:400]]
        return {'error':'Interface generation did not pass validation','issues':issues,'retryable':True,'ui_context':{'displayed':False}}
