"""Render validated A2UI values as they arrive, with official final recovery."""
import json
import uuid
from contextvars import ContextVar
from ag_ui.core import CustomEvent, EventType, ToolCallStartEvent, ToolCallArgsEvent, ToolCallEndEvent
from ag_ui_adk.a2ui_tool import A2UISubAgentTool
from ag_ui_adk.a2ui_google_sdk import normalize_catalog_dict
from ag_ui_a2ui_toolkit import validate_a2ui_components
from .config import CATALOG_ID, PROTOCOL_VERSION

argument_observer = ContextVar('maison_a2ui_arguments', default=None)


class JsonValues:
    """Incremental JSON reader: only closed values cross the SSE boundary.

    Chunks may split strings, escapes, numbers and exponents. Child values are
    emitted before their container, so complete components/data fields can paint
    before the enclosing model tool call ends.
    """
    def __init__(self):
        self.buffer, self.offset, self.stack, self.done = '', 0, [], False
        self.decoder = json.JSONDecoder()

    def feed(self, delta):
        self.buffer += delta
        if len(self.buffer) > 1_000_000:
            raise ValueError('A2UI stream exceeds the argument limit')
        output = []
        while not self.done:
            while self.offset < len(self.buffer) and self.buffer[self.offset].isspace():
                self.offset += 1
            if self.offset == len(self.buffer):
                break
            frame = self.stack[-1] if self.stack else None
            char = self.buffer[self.offset]
            if frame and frame['state'] == 'separator':
                if char == frame['end']:
                    self.offset += 1
                    self.stack.pop()
                    self._accept(frame['path'], frame['value'], output)
                    continue
                if char != ',':
                    raise ValueError('Invalid JSON separator')
                self.offset += 1
                frame['state'] = 'key' if frame['end'] == '}' else 'value'
                continue
            if frame and frame['state'] == 'colon':
                if char != ':':
                    raise ValueError('Invalid JSON property')
                self.offset += 1
                frame['state'] = 'value'
                continue
            if frame and char == frame['end'] and frame['state'] in ('key', 'value'):
                self.offset += 1
                self.stack.pop()
                self._accept(frame['path'], frame['value'], output)
                continue
            if frame and frame['state'] == 'key':
                if char != '"':
                    raise ValueError('Invalid JSON key')
                try:
                    key, end = self.decoder.raw_decode(self.buffer, self.offset)
                except json.JSONDecodeError:
                    break
                frame['key'], frame['state'], self.offset = key, 'colon', end
                continue
            path = frame['path'] + (frame['key'] if frame['end'] == '}' else len(frame['value']),) if frame else ()
            if char in '{[':
                self.stack.append(dict(path=path, value={} if char == '{' else [],
                    end='}' if char == '{' else ']', state='key' if char == '{' else 'value'))
                self.offset += 1
                continue
            try:
                value, end = self.decoder.raw_decode(self.buffer, self.offset)
            except json.JSONDecodeError:
                break
            if char != '"' and (end == len(self.buffer) or self.buffer[end] not in ',}] \r\n\t'):
                break  # A number can still gain more digits or an exponent.
            self.offset = end
            self._accept(path, value, output)
        return output

    def _accept(self, path, value, output):
        output.append((path, value))
        if not self.stack:
            self.done = True
        else:
            parent = self.stack[-1]
            if parent['end'] == '}':
                parent['value'][parent['key']] = value
            else:
                parent['value'].append(value)
            parent['state'] = 'separator'


def operation(kind, value):
    return {'version': PROTOCOL_VERSION, kind: value}


class SurfaceProgress:
    def __init__(self, tool, sid, stream_id, catalog, tool_call_id):
        self.tool, self.sid, self.stream_id, self.catalog = tool, sid, stream_id, catalog
        self.parser = JsonValues()
        self.nodes = {'root': dict(id='root', component='Skeleton', variant='cards')}
        self.sent = {}
        self.invalid = False
        self.tool_call_id = tool_call_id

    async def emit(self, phase, ops=()):
        if self.tool.event_queue is not None:
            await self.tool.event_queue.put(CustomEvent(type=EventType.CUSTOM, name='A2UI_STREAM',
                value={'phase': phase, 'streamId': self.stream_id, 'toolCallId': self.tool_call_id, 'surfaceId': self.sid, 'operations': list(ops)}))

    async def start(self):
        await self.emit('begin', [operation('createSurface', {'surfaceId': self.sid, 'catalogId': CATALOG_ID}),
            operation('updateComponents', {'surfaceId': self.sid, 'components': list(self.nodes.values())})])

    async def feed(self, delta):
        if self.invalid:
            return
        try:
            values = self.parser.feed(delta)
        except ValueError:
            self.invalid = True
            return  # The official final validator/recovery handles bad output.
        ops = []
        for path, value in values:
            if len(path) == 2 and path[0] == 'components' and isinstance(path[1], int):
                changed = self.component(value)
                if changed:
                    ops.append(operation('updateComponents', {'surfaceId': self.sid, 'components': changed}))
            elif len(path) > 1 and path[0] == 'data':
                if path[1] == 'selections':
                    continue  # Client-owned interactive values.
                pointer = '/' + '/'.join(str(key).replace('~', '~0').replace('/', '~1') for key in path[1:])
                marker = json.dumps(value, sort_keys=True)
                if self.sent.get(pointer) != marker:
                    self.sent[pointer] = marker
                    ops.append(operation('updateDataModel', {'surfaceId': self.sid, 'path': pointer, 'value': value}))
        if ops:
            await self.emit('progress', ops)

    def component(self, value):
        if not isinstance(value, dict) or not isinstance(value.get('id'), str) or not isinstance(value.get('component'), str):
            return []
        proposed = {**self.nodes, value['id']: value}
        refs = list(value.get('children', [])) if isinstance(value.get('children'), list) else []
        if isinstance(value.get('child'), str):
            refs.append(value['child'])
        placeholders = []
        for ref in refs:
            if not isinstance(ref, str):
                return []
            if ref not in proposed:
                node = dict(id=ref, component='Skeleton', variant='card' if value['component'] == 'Row' else 'body' if value['component'] == 'Card' else 'line')
                proposed[ref] = node
                placeholders.append(node)
        check = validate_a2ui_components(components=list(proposed.values()), catalog=self.catalog, validate_bindings=False)
        if not check['valid']:
            return []
        self.nodes = proposed
        return placeholders + [value]


class StreamingA2UITool(A2UISubAgentTool):
    """Retain SDK preparation, full-result validation and bounded retries."""
    def for_run(self, event_queue):
        clone = type(self)(self._cfg)
        clone.event_queue = event_queue
        return clone

    async def run_async(self, *, args, tool_context):
        self._stream_sid = args.get('target_surface_id') if args.get('intent') == 'update' else None
        self._stream_sid = self._stream_sid or 'generated-' + uuid.uuid4().hex[:12]
        self._stream_id = uuid.uuid4().hex
        _, schema = self._state_view(tool_context)
        self._stream_catalog = normalize_catalog_dict(self._catalog or schema, default_catalog_id=self._default_catalog_id)
        kind=tool_context.state.get('_ui_kind','dishes')
        subsets={
            'recommendation_filters':{'Column','Text','RecommendationFilters'},
            'reservation_form':{'Column','Text','ReservationForm'},
            'calorie_summary':{'Column','Text','NutritionTotal','CalorieControls'},
            'cart':{'Column','Row','Card','Text','PriceBadge','CartItemControls','CartTotal','Button'},
            'checkout':{'Column','Card','Text','CartTotal','NutritionTotal','Button'},
            'order_success':{'Column','Text','OrderStatus'},
            'reservation_success':{'Column','Text','ReservationStatus'},
            'reservation_availability':{'Column','Row','Card','Text','Button'},
            'dishes':{'Column','Row','Card','Text','DishImage','PriceBadge','DietaryBadge','QuantitySelector','DishOptionSelector','ServingInfo','Button'},
        }
        if self._stream_catalog and kind in subsets:
            # Send only relevant registered definitions to the composition model.
            # It still chooses the layout, bindings, fields and actions.
            self._stream_catalog={**self._stream_catalog,'components':{key:value for key,value in self._stream_catalog.get('components',{}).items() if key in subsets[kind]}}
            self._catalog=self._stream_catalog
        if self._stream_catalog:
            self._stream_catalog = {**self._stream_catalog, 'components': {
                **self._stream_catalog.get('components', {}), 'Skeleton': {'required': ['variant']}}}
        # Build the progress writer before the sub-agent runs. A failure that
        # happens before its first streaming attempt used to leave the browser
        # with a surface that was announced nowhere and closed nowhere.
        self._progress=SurfaceProgress(self,self._stream_sid,self._stream_id,self._stream_catalog,'')
        self._open_tool_call=None
        committed = False
        try:
            result = await super().run_async(args=args, tool_context=tool_context)
            payload = json.loads(result) if isinstance(result, str) else result
            operations = payload.get('a2ui_operations') if isinstance(payload, dict) else (payload if isinstance(payload, list) else None)
            if isinstance(operations, list):
                if self._progress:
                    await self._progress.emit('commit', operations)
                committed = True
            return result
        finally:
            # A run that dies mid-composition leaves the streaming tool call
            # open, and AG-UI then refuses the RUN_FINISHED that follows it.
            if self._open_tool_call:
                await self.event_queue.put(ToolCallEndEvent(type=EventType.TOOL_CALL_END,tool_call_id=self._open_tool_call))
                self._open_tool_call=None
            if not committed and self._progress:
                await self._progress.emit('rollback')

    async def _stream_one_attempt(self, prompt, attempt, tool_call_id, conversation):
        self._progress.tool_call_id=tool_call_id
        self._open_tool_call=tool_call_id
        await self._progress.start()
        await self.event_queue.put(ToolCallStartEvent(type=EventType.TOOL_CALL_START,
            tool_call_id=tool_call_id, tool_call_name='render_a2ui'))
        prompt += ('\nSTREAMING: Set surfaceId to ' + self._stream_sid +
            '. Emit surfaceId first, then components, then data. Emit root and containers before their '
            'contents, referencing stable child IDs. For generated prose use Text/Card strings bound '
            'to data paths, then fill those paths in data. Never include user selections in data. '
            'Do not generate Skeleton components; the host provides missing-field placeholders.')
        request = self._build_llm_request(prompt, conversation)
        token = argument_observer.set(self._progress.feed)
        final_args = None
        try:
            async for response in self._model.generate_content_async(request, stream=True):
                fc = self._extract_render_fc(response)
                if fc is not None and getattr(fc, 'args', None):
                    final_args = self._coerce_freeform_args(dict(fc.args))
                    final_args['surfaceId'] = self._stream_sid
            if final_args is not None:
                await self.event_queue.put(ToolCallArgsEvent(type=EventType.TOOL_CALL_ARGS,
                    tool_call_id=tool_call_id, delta=json.dumps(final_args)))
            return final_args
        finally:
            argument_observer.reset(token)
            await self.event_queue.put(ToolCallEndEvent(type=EventType.TOOL_CALL_END,tool_call_id=tool_call_id))
            # Cleared only after the frame is queued, so an interrupted queueing
            # still leaves the call for the outer handler to close.
            if self._open_tool_call==tool_call_id:self._open_tool_call=None


def streaming_a2ui_tool(tool):
    return StreamingA2UITool(tool._cfg)
