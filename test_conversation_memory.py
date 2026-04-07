#!/usr/bin/env python3
"""
Test de conversación con memoria episódica.

Valida que:
1. La memoria se consulta cuando el usuario dice "recuerda", "requerimiento", etc.
2. El system prompt con personalidad Nia se usa correctamente
3. El modelo responde con contexto de conversaciones previas
"""

import os
import sys

# Asegurar que los imports funcionen
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

def test_conversation_with_memory():
    """Test completo de conversación con consulta de memoria episódica."""
    from src.triage_crew import TriageCrew
    from src.conversation_memory import create_user_memory
    
    print("="*80)
    print("TEST: CONVERSACIÓN CON MEMORIA EPISÓDICA")
    print("="*80)
    
    # Crear crew y memoria para usuario test
    test_user_id = "test_user_123"
    crew = TriageCrew()
    memory = create_user_memory(test_user_id, max_topics=10)
    
    # Paso 1: Simular conversación previa sobre "sistema de mantenimiento para viña"
    print("\n📝 PASO 1: Agregar conversaciones previas a la memoria...")
    
    messages_to_add = [
        ("user", "Quiero crear un sistema de mantenimiento para la viña"),
        ("assistant", "Excelente idea. ¿Qué funcionalidades específicas necesitas? (registro de tareas, alertas, reportes, etc.)"),
        ("user", "Define tú los requisitos, tiene que ser algo simple, un MVP"),
        ("assistant", "Entendido. Aquí están los requisitos mínimos para el MVP:\n1. Autenticación básica\n2. Gestión de tareas (CRUD)\n3. Persistencia local\n4. Interfaz mobile-first"),
        ("user", "Estoy pensando en algo hecho por nosotros, como una página web que se vea bien en móvil"),
        ("assistant", "Perfecto. Un sistema web responsive con enfoque mobile-first es ideal para el equipo de viña. ¿Tienes desarrollador disponible?"),
    ]
    
    for role, content in messages_to_add:
        memory.add_message(content=content, role=role)
        print(f"  ✓ {role}: {content[:60]}...")
    
    # Paso 2: Simular conversación nueva (sin contexto inmediato)
    print("\n💬 PASO 2: Nueva sesión - Usuario pide recordar...")
    
    conversation_history = []  # Historial corto plazo vacío (nueva sesión)
    
    # Test 1: "El requerimiento más reciente"
    print("\n🧪 TEST 1: Usuario pregunta 'El requerimiento más reciente'")
    response = crew.kickoff_conversation(
        user_message="El requerimiento más reciente",
        conversation_history=conversation_history,
        user_id=test_user_id
    )
    
    print(f"\n📤 Usuario: El requerimiento más reciente")
    print(f"📥 Nia: {response}")
    
    # Validar respuesta
    assert len(response) > 50, "Respuesta demasiado corta"
    
    # Debe mencionar el sistema de mantenimiento o contexto relacionado
    # (puede decir "sistema", "mantenimiento", "viña", "MVP", etc.)
    found_context = any(keyword in response.lower() for keyword in [
        "sistema", "mantenimiento", "viña", "vina", "mvp", "mobile", 
        "web", "tareas", "desarrollo", "memoria", "conversación", "hablamos"
    ])
    
    if found_context:
        print("\n✅ TEST 1 PASÓ: Nia recuperó contexto de memoria episódica")
    else:
        print(f"\n⚠️  TEST 1 FALLÓ: Nia no mencionó contexto previo")
        print(f"    Respuesta: {response[:200]}...")
        print(f"    ESPERADO: Debería mencionar 'sistema de mantenimiento' o preguntar con contexto")
    
    # Test 2: "¿No recuerdas lo que conversamos?"
    print("\n🧪 TEST 2: Usuario pregunta '¿No recuerdas lo que conversamos?'")
    
    conversation_history.append({"role": "user", "content": "El requerimiento más reciente"})
    conversation_history.append({"role": "assistant", "content": response})
    
    response2 = crew.kickoff_conversation(
        user_message="¿No recuerdas lo que conversamos?",
        conversation_history=conversation_history,
        user_id=test_user_id
    )
    
    print(f"\n📤 Usuario: ¿No recuerdas lo que conversamos?")
    print(f"📥 Nia: {response2}")
    
    # La respuesta NO debe decir "No tengo memoria de conversaciones pasadas"
    bad_phrases = [
        "no tengo memoria",
        "cada sesión comienza desde cero",
        "no tengo acceso en tiempo real",
        "julio de 2024"
    ]
    
    has_generic_response = any(phrase in response2.lower() for phrase in bad_phrases)
    
    if not has_generic_response:
        print("\n✅ TEST 2 PASÓ: Nia NO respondió con mensaje genérico de 'sin memoria'")
    else:
        print(f"\n❌ TEST 2 FALLÓ: Nia dio respuesta genérica sin consultar memoria")
        print(f"    Respuesta: {response2[:200]}...")
        print(f"    ERROR: Contiene frases genéricas tipo ChatGPT base")
    
    # Test 3: "Haz el triage del sistema de mantenimiento"
    print("\n🧪 TEST 3: Usuario pide 'Haz el triage del sistema de mantenimiento'")
    
    conversation_history.append({"role": "user", "content": "¿No recuerdas lo que conversamos?"})
    conversation_history.append({"role": "assistant", "content": response2})
    
    response3 = crew.kickoff_conversation(
        user_message="Puedes hacer el triage del sistema de mantenimiento que te mencioné?",
        conversation_history=conversation_history,
        user_id=test_user_id
    )
    
    print(f"\n📤 Usuario: Puedes hacer el triage del sistema de mantenimiento que te mencioné?")
    print(f"📥 Nia: {response3}")
    
    # Debe ofrecer ejecutar el triage o pedir confirmación
    offers_action = any(keyword in response3.lower() for keyword in [
        "proceder", "ejecutar", "triage", "documentar", "confluence", 
        "analizar", "quieres que", "confirma", "adelante"
    ])
    
    if offers_action:
        print("\n✅ TEST 3 PASÓ: Nia ofrece acción concreta (triage/documentación)")
    else:
        print(f"\n⚠️  TEST 3 ADVERTENCIA: Respuesta no ofrece acción clara")
        print(f"    ESPERADO: 'Quieres que proceda con el triage?' o similar")
    
    # Resumen final
    print("\n" + "="*80)
    print("📊 RESUMEN DE TESTS")
    print("="*80)
    
    all_passed = found_context and not has_generic_response and offers_action
    
    if all_passed:
        print("✅ TODOS LOS TESTS PASARON")
        print("\nArquitectura validada:")
        print("  ✓ Memoria episódica se consulta cuando usuario menciona 'requerimiento'/'recuerda'")
        print("  ✓ System prompt con personalidad Nia se aplica correctamente")
        print("  ✓ Nia NO responde con mensajes genéricos sin memoria")
        print("  ✓ Nia ofrece acciones concretas basadas en contexto")
    else:
        print("⚠️  ALGUNOS TESTS FALLARON - Revisar implementación")
        if not found_context:
            print("  ❌ Memoria no recupera contexto previo")
        if has_generic_response:
            print("  ❌ Respuestas genéricas sin personalidad Nia")
        if not offers_action:
            print("  ⚠️  Falta propuesta de acción concreta")
    
    print("="*80)
    
    return all_passed


if __name__ == "__main__":
    try:
        success = test_conversation_with_memory()
        sys.exit(0 if success else 1)
    except Exception as exc:
        print(f"\n❌ ERROR EN TEST: {exc}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
