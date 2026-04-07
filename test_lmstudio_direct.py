import logging
logging.basicConfig(level=logging.INFO, format='%(levelname)s:%(name)s:%(message)s')

from src.lmstudio_litellm import build_lmstudio_llm

print("Building LLM...")
llm = build_lmstudio_llm(enable_reasoning=False)
print(f"LLM: {llm}\n")

prompt = "Usuario: Hello Nia\n\nAsistente (responde de forma concisa y directa):"
print(f"Prompt: {prompt}\n")

print("Calling LLM...")
result = llm(prompt)

print(f"\nResult type: {type(result)}")
print(f"Result length: {len(result)}")
print(f"Result: '{result}'")
