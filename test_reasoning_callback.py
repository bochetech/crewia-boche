#!/usr/bin/env python3
"""
Test script para verificar que el callback _sanitize_reasoning_callback
detecta correctamente diferentes formatos de razonamiento.

MODO: Test directo sin Telegram - solo LLM + callback
"""
import os
# Evitar que se inicie Telegram
os.environ["TELEGRAM_BOT_TOKEN"] = ""  

from src.triage_crew import TriageCrew

def test_callback_layers():
    """Test de las 4 capas del callback con ejemplos simulados."""
    print("="*80)
    print("TEST: 4 CAPAS DEL CALLBACK _sanitize_reasoning_callback")
    print("="*80)
    
    # Solo inicializar el crew SIN bot de Telegram
    print("\n⚙️  Inicializando TriageCrew (solo LLM local)...\n")
    crew = TriageCrew()
    
    if crew.local_llm is None:
        print("⚠️  LM Studio no disponible. Asegúrate de:")
        print("   1. Tener LM Studio corriendo en http://localhost:1234")
        print("   2. Un modelo cargado (ej: Qwen3.5-9b)")
        return
    
    # Pregunta que típicamente genera razonamiento
    user_message = "¿Qué es Descorcha y cuál es su estrategia de transformación digital?"
    
    print(f"📤 PREGUNTA: {user_message}\n")
    print("🔄 Enviando al LLM (esto puede tardar 10-30 segundos)...\n")
    
    try:
        response = crew.kickoff_conversation(user_message)
        
        print(f"\n{'='*80}")
        print(f"📥 RESPUESTA FINAL:")
        print(f"{'='*80}")
        print(response)
        print(f"{'='*80}\n")
        
        # Verificar que NO contenga marcadores de razonamiento
        has_think_tags = "<think>" in response.lower() or "</think>" in response.lower()
        has_reasoning_tags = "<reasoning>" in response.lower() or "</reasoning>" in response.lower()
        has_html_comments = "<!-- thinking -->" in response.lower()
        
        print("\n🔍 ANÁLISIS DE LA RESPUESTA:")
        print(f"   {'❌' if has_think_tags else '✅'} Contiene <think> tags: {has_think_tags}")
        print(f"   {'❌' if has_reasoning_tags else '✅'} Contiene <reasoning> tags: {has_reasoning_tags}")
        print(f"   {'❌' if has_html_comments else '✅'} Contiene <!-- thinking --> comments: {has_html_comments}")
        
        if not (has_think_tags or has_reasoning_tags or has_html_comments):
            print("\n✅ ÉXITO: El callback limpió correctamente el razonamiento")
        else:
            print("\n⚠️  ADVERTENCIA: Se detectaron marcadores de razonamiento en la respuesta")
        
        return response
        
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        print("\nVerifica:")
        print("  - LM Studio está corriendo")
        print("  - Hay un modelo cargado")
        print("  - El modelo responde a prompts simples")


if __name__ == "__main__":
    test_callback_layers()
