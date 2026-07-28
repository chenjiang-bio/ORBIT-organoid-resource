import logging
from crewai import LLM
import litellm
from ..utils.json_schema import clean_schema
from functools import wraps

# # Keep original litellm.completion
# _original_litellm_completion = litellm.completion

# def _patched_litellm_completion(*args, **kwargs):
#     """
#     Patched litellm.completion that flattens schemas for Gemini.
#     """
#     # Check for Gemini + tools
#     model = kwargs.get('model', args[0] if args else '')
    
#     # Detect Gemini models
#     is_gemini = 'gemini' in model.lower() if isinstance(model, str) else False
    
#     if is_gemini and 'tools' in kwargs:
#         tools = kwargs['tools']
#         if tools and isinstance(tools, list):
#             print(f"[KMLLM Patch] Detected Gemini model with {len(tools)} tools, flattening schemas...")
#             flattened_tools = []
#             for tool in tools:
#                 if isinstance(tool, dict) and 'function' in tool:
#                     # Deep-copy tool defs to avoid mutating originals
#                     import copy
#                     flattened_tool = copy.deepcopy(tool)
#                     func = flattened_tool['function']
                    
#                     # Flatten parameters schema
#                     if 'parameters' in func and isinstance(func['parameters'], dict):
#                         print(f"[KMLLM Patch] Flattening schema for tool: {func.get('name', 'unknown')}")
#                         func['parameters'] = clean_schema(func['parameters'])
                    
#                     flattened_tools.append(flattened_tool)
#                     print(f"[KMLLM Patch] before flattening: {tool}")
#                     print("--"*100)
#                     print(f"[KMLLM Patch] after flattening: {flattened_tool}")
#                 else:
#                     flattened_tools.append(tool)
            
#             kwargs['tools'] = flattened_tools
#             print(f"[KMLLM Patch] Successfully flattened {len(flattened_tools)} tool schemas")
    
#     # Call original litellm.completion
#     return _original_litellm_completion(*args, **kwargs)

# # Replace litellm.completion with patched version
# litellm.completion = _patched_litellm_completion
# print("[KMLLM] litellm.completion has been patched for Gemini schema flattening")


class KMLLM(LLM):
    def __init__(self, model, real_provider=None, context_window_size=262144, timeout = None, temperature = None, top_p = None, n = None, stop = None, max_completion_tokens = None, max_tokens = None, presence_penalty = None, frequency_penalty = None, logit_bias = None, response_format = None, seed = None, logprobs = None, top_logprobs = None, base_url = None, api_base = None, api_version = None, api_key = None, callbacks = None, reasoning_effort = None, stream = False, **kwargs):
        super().__init__(model, timeout, temperature, top_p, n, stop, max_completion_tokens, max_tokens, presence_penalty, frequency_penalty, logit_bias, response_format, seed, logprobs, top_logprobs, base_url, api_base, api_version, api_key, callbacks, reasoning_effort, stream, **kwargs)
        self.real_provider = real_provider
        self.real_model = model.split("/")[-1]
        self.context_window_size = context_window_size
        print(f"Initialized KMLLM with model: {model} and real_provider: {real_provider}, function calling support: {self.supports_function_calling()}, context_window_size:{context_window_size}")
    
    def _validate_call_params(self) -> None:
        """
        Validate parameters before making a call. Currently this only checks if
        a response_format is provided and whether the model supports it.
        The custom_llm_provider is dynamically determined from the model:
          - E.g., "openrouter/deepseek/deepseek-chat" yields "openrouter"
          - "gemini/gemini-1.5-pro" yields "gemini"
          - If no slash is present, "openai" is assumed.
        """
        if self.real_provider:
            provider = self.real_provider
            model = self.model.split("/")[-1]
        else:
            provider = self._get_custom_llm_provider()
            model = self.model
        if self.response_format is not None and not self.supports_response_schema(
            model=model,
            custom_llm_provider=provider,
        ):
            raise ValueError(
                f"The model {model} does not support response_format for provider '{provider}'. "
                "Please remove response_format or use a supported model."
            )

    def supports_function_calling(self) -> bool:
        try:
            if self.real_provider:
                provider = self.real_provider
                model = self.model.split("/")[-1]
            else:
                provider = self._get_custom_llm_provider()
                model = self.model
            print(f"Checking function calling support for model: {model} with provider: {provider}")
            return litellm.utils.supports_function_calling(
                model, custom_llm_provider=provider
            )
        except Exception as e:
            logging.error(f"Failed to check function calling support: {e!s}")
            return False