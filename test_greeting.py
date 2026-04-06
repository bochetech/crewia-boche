#!/usr/bin/env python3
"""Test específico para saludos que generan razonamiento duplicado."""
import os
os.environ["TELEGRAM_BOT_TOKEN"] = ""

from src.triage_crew import TriageCrew

def test_greeting():
    print("="*80)
    print("TEST: Saludo simple (típicamente genera razonamiento + duplicados)")
    print("="*80)
    
    crew = TriageCrew()
    
    if crew.local_llm is None:
        print("⚠️  LM Studio no disponible")
        return
    
    # Saludo simple que genera razonamiento visible
    user_message = "Hello Nia"
    
    print(f"\n📤 MENSAJE: '{user_message}'\n")
    print("🔄 Procesando...\n")
    
    response = crew.kickoff_conversation(user_message)
    
    print(f"\n{'='*80}")
    print(f"📥 RESPUESTA LIMPIA:")
    print(f"{'='*80}")
    print(response)
    print(f"{'='*80}\n")
    
    # Verificaciones
    has_let_me = "let me" in response.lower()
    has_i_need = "i need" in response.lower()
    has_multiple_greetings = response.lower().count("¡hola") + response.lower().count("hola!") > 1
    
    print("🔍 VERIFICACIONES:")
    print(f"   {'❌' if has_let_me else '✅'} Contiene 'Let me': {has_let_me}")
    print(f"   {'❌' if has_i_need else '✅'} Contiene 'I need': {has_i_need}")
    print(f"   {'❌' if has_multiple_greetings else '✅'} Saludos duplicados: {has_multiple_greetings}")
    
    if not (has_let_me or has_i_need or has_multiple_greetings):
        print("\n✅ ÉXITO: Callback eliminó reasoning y duplicados")
    else:
        print("\n⚠️  Todavía hay trazas de razonamiento")

if __name__ == "__main__":
    test_greeting()
