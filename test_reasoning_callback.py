#!/usr/bin/env python3
"""
Test script para verificar que el callback _sanitize_reasoning_callback
detecta correctamente diferentes formatos de razonamiento.
"""

from src.triage_crew import TriageCrew

def test_conversation():
    """Test que simula una conversación que normalmente generaría razonamiento."""
    print("="*80)
    print("TEST: Pregunta que genera razonamiento visible")
    print("="*80)
    
    crew = TriageCrew()
    
    # Pregunta que típicamente genera razonamiento
    user_message = "¿Qué es Descorcha y cómo funciona su modelo de negocio?"
    
    print(f"\n📤 PREGUNTA: {user_message}\n")
    
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
    print(f"   ❌ Contiene <think> tags: {has_think_tags}")
    print(f"   ❌ Contiene <reasoning> tags: {has_reasoning_tags}")
    print(f"   ❌ Contiene <!-- thinking --> comments: {has_html_comments}")
    
    if not (has_think_tags or has_reasoning_tags or has_html_comments):
        print("\n✅ ÉXITO: El callback limpió correctamente el razonamiento")
    else:
        print("\n⚠️  ADVERTENCIA: Se detectaron marcadores de razonamiento en la respuesta")
    
    return response


if __name__ == "__main__":
    test_conversation()
