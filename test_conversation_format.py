#!/usr/bin/env python3
"""
Test rápido: validar que NO aparece el formato interno del contexto en la respuesta.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_no_context_leak():
    """Validar que el contexto interno NO aparece en la respuesta final."""
    from src.triage_crew import TriageCrew
    from src.conversation_memory import create_user_memory
    
    print("="*80)
    print("TEST: NO FILTRAR CONTEXTO INTERNO EN RESPUESTA")
    print("="*80)
    
    # Crear crew y memoria
    test_user_id = "test_format_user"
    crew = TriageCrew()
    memory = create_user_memory(test_user_id, max_topics=10)
    
    # Agregar conversación previa
    print("\n📝 Agregando conversación previa...")
    memory.add_message("Quiero crear un sistema de mantenimiento para la viña", role="user")
    memory.add_message("Excelente idea. ¿Qué funcionalidades necesitas?", role="assistant")
    memory.add_message("Define tú los requisitos, MVP simple", role="user")
    memory.add_message("Entendido. Requisitos: autenticación, CRUD tareas, mobile-first", role="assistant")
    
    # Preguntar algo que active la memoria
    print("\n💬 Usuario: '¿todavía podemos conversar?'")
    response = crew.kickoff_conversation(
        user_message="todavia podemos conversar?",
        conversation_history=[],
        user_id=test_user_id
    )
    
    print("\n📥 Respuesta de Nia:")
    print("-" * 80)
    print(response)
    print("-" * 80)
    
    # Validaciones
    print("\n🔍 Validando formato...")
    
    bad_patterns = [
        "**MEMORIA EPISÓDICA:",
        "[CONTEXTO PREVIO",
        "[FIN CONTEXTO PREVIO]",
        "**Tema:**",
        "**Contexto:**",
        "**Acción tomada:**",
        "📚",
    ]
    
    found_issues = []
    for pattern in bad_patterns:
        if pattern in response:
            found_issues.append(pattern)
    
    if found_issues:
        print(f"\n❌ TEST FALLÓ: Se encontraron patrones de contexto interno en la respuesta:")
        for issue in found_issues:
            print(f"   - '{issue}'")
        print("\n⚠️  El modelo está repitiendo el contexto en lugar de usarlo.")
        return False
    else:
        print("\n✅ TEST PASÓ: NO hay filtración de contexto interno")
        print("   ✓ Respuesta limpia sin bloques [CONTEXTO PREVIO]")
        print("   ✓ Sin formato **MEMORIA EPISÓDICA:**")
        print("   ✓ Sin viñetas de metadata interna")
        return True


if __name__ == "__main__":
    try:
        success = test_no_context_leak()
        sys.exit(0 if success else 1)
    except Exception as exc:
        print(f"\n❌ ERROR EN TEST: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
