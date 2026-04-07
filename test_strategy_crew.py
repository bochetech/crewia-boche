"""
Test completo del Multi-Agent Strategy Crew.

Valida el flujo end-to-end:
1. Detección de iniciativa estratégica en conversación
2. Activación del crew (Coordinator, Triage Strategist, BA, Researcher)
3. Clasificación en Foco (F1-F4)
4. Deduplicación semántica (ChromaDB threshold 0.85)
5. Escritura al HTML SSOT con <mark> para modificaciones
6. Respuesta conversacional de Nia manteniendo contexto

Test scenarios:
- Modificación de iniciativa existente (F4-101 Vilaport)
- Nueva iniciativa (F2: sistema de recomendaciones IA)
- Iniciativa rechazada (no estratégica)
"""
from __future__ import annotations
import os
import sys
import json
import time

# Forzar variables de entorno para test
os.environ["TRIAGE_STUB_MODE"] = "0"  # Deshabilitar stub mode
os.environ["LMSTUDIO_BASE_URL"] = "http://localhost:1234"

from src.triage_crew import TriageCrew
from src.strategy_tools.html_strategy_tool import HTMLStrategyTool


def test_scenario_1_modify_existing():
    """
    TEST 1: Modificación de iniciativa existente F4-101 (Comparador Vilaport).
    
    Input: "Matías dice que ajustemos precios en comparador Vilaport"
    Expected:
    - Foco: F4
    - Action: MODIFICACIÓN (similarity > 0.85)
    - Initiative ID: F4-101
    - HTML updated with <mark>
    """
    print("\n" + "="*80)
    print("TEST 1: Modificación de iniciativa existente (F4-101 Vilaport)")
    print("="*80 + "\n")
    
    crew = TriageCrew()
    
    user_message = "Matías dice que ajustemos precios en comparador Vilaport para ser más competitivos"
    
    print(f"📩 Input: {user_message}\n")
    
    # Ejecutar detección de iniciativa + multi-agent crew
    result = crew.kickoff_strategy_crew(user_message)
    
    print(f"\n📊 Resultado del Strategy Crew:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validaciones
    assert result.get("status") == "approved", "❌ Iniciativa debería estar aprobada"
    assert result.get("foco") == "F4", "❌ Debería clasificarse como F4 (Optimización Oferta)"
    assert result.get("action") == "MODIFICACIÓN", "❌ Debería ser MODIFICACIÓN (no nueva)"
    assert result.get("initiative_id") == "F4-101", "❌ Debería actualizar F4-101 existente"
    assert result.get("html_updated") is True, "❌ HTML debería estar actualizado"
    
    print("\n✅ TEST 1 PASÓ: Iniciativa modificada correctamente (F4-101)")
    print(f"   - Foco: {result.get('foco')}")
    print(f"   - Acción: {result.get('action')}")
    print(f"   - ID: {result.get('initiative_id')}")
    print(f"   - HTML actualizado: {result.get('html_updated')}")
    
    return True


def test_scenario_2_create_new():
    """
    TEST 2: Nueva iniciativa (sistema de recomendaciones IA).
    
    Input: "Quiero implementar un sistema de recomendaciones con IA para aumentar cross-sell"
    Expected:
    - Foco: F2 (Experiencia Cliente)
    - Action: NUEVA_INICIATIVA (similarity < 0.85)
    - Initiative ID: F2-XXX (nuevo)
    - HTML updated
    """
    print("\n" + "="*80)
    print("TEST 2: Nueva iniciativa (Recomendaciones IA)")
    print("="*80 + "\n")
    
    crew = TriageCrew()
    
    user_message = "Quiero implementar un sistema de recomendaciones con IA que sugiera vinos según historial de compras para aumentar cross-sell"
    
    print(f"📩 Input: {user_message}\n")
    
    result = crew.kickoff_strategy_crew(user_message)
    
    print(f"\n📊 Resultado del Strategy Crew:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validaciones
    assert result.get("status") == "approved", "❌ Iniciativa debería estar aprobada"
    assert result.get("foco") == "F2", "❌ Debería clasificarse como F2 (Experiencia Cliente)"
    assert result.get("action") == "NUEVA_INICIATIVA", "❌ Debería ser NUEVA_INICIATIVA"
    assert result.get("initiative_id", "").startswith("F2-"), "❌ ID debería empezar con F2-"
    assert result.get("html_updated") is True, "❌ HTML debería estar actualizado"
    
    print("\n✅ TEST 2 PASÓ: Nueva iniciativa creada correctamente")
    print(f"   - Foco: {result.get('foco')}")
    print(f"   - Acción: {result.get('action')}")
    print(f"   - ID: {result.get('initiative_id')}")
    
    return True


def test_scenario_3_reject_non_strategic():
    """
    TEST 3: Rechazo de iniciativa no estratégica.
    
    Input: "Quiero cambiar el color del logo a rojo"
    Expected:
    - Status: rejected
    - Reason: No alineada con Focos estratégicos
    """
    print("\n" + "="*80)
    print("TEST 3: Rechazo de iniciativa no estratégica")
    print("="*80 + "\n")
    
    crew = TriageCrew()
    
    user_message = "Quiero cambiar el color del logo de Descorcha a rojo porque me gusta más"
    
    print(f"📩 Input: {user_message}\n")
    
    result = crew.kickoff_strategy_crew(user_message)
    
    print(f"\n📊 Resultado del Strategy Crew:")
    print(json.dumps(result, indent=2, ensure_ascii=False))
    
    # Validaciones
    assert result.get("status") == "rejected", "❌ Iniciativa debería estar rechazada"
    assert "estratégic" in result.get("reason", "").lower(), "❌ Razón debería mencionar 'estratégica'"
    
    print("\n✅ TEST 3 PASÓ: Iniciativa no estratégica rechazada correctamente")
    print(f"   - Status: {result.get('status')}")
    print(f"   - Razón: {result.get('reason')}")
    
    return True


def test_scenario_4_conversation_integration():
    """
    TEST 4: Integración con conversación (Nia menciona resultado del crew).
    
    Input conversacional: "Propongo integrar MultiVende para mejorar OTD"
    Expected:
    - Detección automática de iniciativa
    - Activación del crew
    - Respuesta de Nia mencionando el resultado
    """
    print("\n" + "="*80)
    print("TEST 4: Integración conversacional con Strategy Crew")
    print("="*80 + "\n")
    
    crew = TriageCrew()
    
    user_message = "Propongo integrar MultiVende para automatizar sincronización de inventario y mejorar nuestro OTD"
    
    print(f"📩 Input conversacional: {user_message}\n")
    
    # Llamar a kickoff_conversation (debería detectar iniciativa y activar crew)
    response = crew.kickoff_conversation(user_message, user_id="test_user_strategy")
    
    print(f"\n💬 Respuesta de Nia:")
    print(response)
    
    # Validaciones
    assert response is not None, "❌ Nia debería responder"
    assert len(response) > 50, "❌ Respuesta debería tener contenido sustancial"
    
    # La respuesta debería mencionar el procesamiento (si el crew se activó)
    keywords_esperados = ["multivende", "inventario", "otd", "f1", "logística"]
    assert any(kw in response.lower() for kw in keywords_esperados), "❌ Respuesta debería mencionar términos estratégicos"
    
    print("\n✅ TEST 4 PASÓ: Nia respondió conversacionalmente con contexto estratégico")
    
    return True


def test_html_tool_basic():
    """
    TEST 5 (Preliminar): Validar HTMLStrategyTool funciona correctamente.
    """
    print("\n" + "="*80)
    print("TEST 5: Validación básica de HTMLStrategyTool")
    print("="*80 + "\n")
    
    tool = HTMLStrategyTool()
    
    # 1. Leer iniciativa existente
    print("📖 Test: Leer F4-101…")
    result = tool._run("read", initiative_id="F4-101")
    data = json.loads(result)
    
    assert data.get("status") == "ok", "❌ Lectura debería ser exitosa"
    assert data.get("initiative_id") == "F4-101", "❌ ID incorrecto"
    assert "Vilaport" in data.get("title", ""), "❌ Título debería contener 'Vilaport'"
    
    print(f"   ✓ Título: {data.get('title')}")
    print(f"   ✓ Objetivo: {data.get('objective')[:80]}...")
    
    # 2. Buscar similares
    print("\n🔍 Test: Buscar iniciativas similares a 'precios Vilaport'…")
    result = tool._run("search", query="precios Vilaport competencia", threshold=0.85)
    data = json.loads(result)
    
    print(f"   ✓ Encontradas: {len(data.get('matches', []))} iniciativas similares")
    if data.get('matches'):
        print(f"   ✓ Top match: {data['matches'][0].get('initiative_id')} (similarity: {data['matches'][0].get('similarity')})")
    
    # 3. Listar todas
    print("\n📋 Test: Listar todas las iniciativas…")
    result = tool._run("list_all")
    data = json.loads(result)
    
    assert data.get("status") == "ok", "❌ Listado debería ser exitoso"
    assert data.get("total", 0) > 0, "❌ Debería haber iniciativas en el HTML"
    
    print(f"   ✓ Total iniciativas: {data.get('total')}")
    
    print("\n✅ TEST 5 PASÓ: HTMLStrategyTool operativo")
    
    return True


if __name__ == "__main__":
    print("\n" + "🤖" * 40)
    print("SUITE DE TESTS: Multi-Agent Strategy Crew")
    print("🤖" * 40 + "\n")
    
    tests = [
        ("HTMLStrategyTool básico", test_html_tool_basic),
        # Comentados temporalmente hasta que se configure SerperDevTool API key
        # ("Modificar iniciativa existente", test_scenario_1_modify_existing),
        # ("Crear nueva iniciativa", test_scenario_2_create_new),
        # ("Rechazar no estratégica", test_scenario_3_reject_non_strategic),
        # ("Integración conversacional", test_scenario_4_conversation_integration),
    ]
    
    passed = 0
    failed = 0
    
    for test_name, test_func in tests:
        try:
            if test_func():
                passed += 1
            else:
                failed += 1
                print(f"\n❌ {test_name} FALLÓ (retornó False)\n")
        except AssertionError as e:
            failed += 1
            print(f"\n❌ {test_name} FALLÓ: {e}\n")
        except Exception as exc:
            failed += 1
            print(f"\n❌ {test_name} ERROR: {exc}\n")
            import traceback
            traceback.print_exc()
        
        time.sleep(1)  # Espera entre tests
    
    print("\n" + "="*80)
    print(f"RESUMEN: {passed} tests pasados, {failed} fallidos")
    print("="*80 + "\n")
    
    if failed == 0:
        print("✅ ¡TODOS LOS TESTS PASARON!")
        print("\n📝 Próximos pasos:")
        print("   1. Configurar SERPER_API_KEY en .env para SerperDevTool")
        print("   2. Descomentar tests completos del multi-agent crew")
        print("   3. Ejecutar: python test_strategy_crew.py")
        print("   4. Validar en Telegram: 'Propongo integrar MultiVende'")
    else:
        print(f"⚠️ {failed} test(s) fallaron — revisar logs arriba")
        sys.exit(1)
