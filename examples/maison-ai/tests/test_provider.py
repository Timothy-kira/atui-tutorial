import asyncio
import pytest


def test_empty_token_exhaustion_is_bounded_and_never_succeeds(monkeypatch):
    from backend import config
    from google.adk.models.lite_llm import LiteLlm
    from google.adk.models.llm_request import LlmRequest
    from google.adk.models.llm_response import LlmResponse
    from google.genai import types

    calls=[]
    async def exhausted(self, request, stream=False):
        calls.append(1)
        yield LlmResponse(error_code='MAX_TOKENS',partial=False)

    monkeypatch.setattr(config,'PROVIDER','dot')
    monkeypatch.setattr(config,'UI_MODE','dynamic')
    monkeypatch.setenv('DOT_API_KEY','test-only-placeholder')
    monkeypatch.setattr(LiteLlm,'generate_content_async',exhausted)
    model=config.make_model()
    request=LlmRequest(contents=[],config=types.GenerateContentConfig())
    emitted=[]
    async def collect():
        async for response in model.generate_content_async(request,stream=True):
            emitted.append(response)
    with pytest.raises(RuntimeError,match='output limit'):
        asyncio.run(collect())
    assert len(calls)==2 and emitted==[]

@pytest.mark.asyncio
async def test_wire_limits_and_json_mode_are_scoped_to_the_request(monkeypatch):
    from backend import config
    from google.adk.models.lite_llm import LiteLLMClient
    from google.adk.models.llm_request import LlmRequest
    from google.genai import types
    from litellm import ModelResponse
    seen=[]
    async def completion(self,*args,**kwargs):
        seen.append(kwargs)
        return ModelResponse(choices=[{'index':0,'message':{'role':'assistant','content':'{}'},'finish_reason':'stop'}],usage={'prompt_tokens':1,'completion_tokens':1,'total_tokens':2})
    monkeypatch.setattr(config,'PROVIDER','dot');monkeypatch.setenv('DOT_API_KEY','test-only-placeholder')
    monkeypatch.setattr(LiteLLMClient,'acompletion',completion)
    model=config.make_model()
    for mime in ('application/json',None):
        request=LlmRequest(contents=[types.Content(role='user',parts=[types.Part(text='Synthetic test')])],config=types.GenerateContentConfig(response_mime_type=mime,max_output_tokens=512))
        async for _ in model.generate_content_async(request,stream=False):pass
    assert all('max_tokens' not in entry and entry['max_completion_tokens']==512 for entry in seen)
    assert seen[0]['response_format']=={'type':'json_object'}
    assert seen[1]['response_format'] is None
    assert config.JSON_OUTPUT.get() is False
