# Migración a Flujo Único de Triage

**Fecha:** 6 de abril de 2026  
**Motivo:** Eliminar triage "rápido" mock y unificar todo en Multi-Agent Strategy Crew para mantener calidad del HTML SSOT

---

## 🎯 **Problema Original**

### **Arquitectura anterior (2 flujos paralelos):**

```
Input → ¿Qué ejecutar?
         ├─ kickoff() → Triage "rápido" → ConfluenceMock ❌
         └─ kickoff_conversation() → Detecta keywords → Strategy Crew ✅
```

**Problemas:**
1. **ConfluenceMock no persiste nada** - solo retorna JSON simulado
2. **Triage "rápido" no actualiza HTML** - el SSOT quedaba desincronizado
3. **Dos flujos diferentes** - confusión sobre cuándo usar cada uno
4. **HTML podía "embasurarse"** - no había control de calidad ni deduplicación

---

## ✅ **Solución Implementada**

### **Nueva arquitectura (flujo único):**

```
TODO Input (email/chat/voz)
    ↓
kickoff() SIEMPRE ejecuta Multi-Agent Strategy Crew
    ↓
┌─────────────────────────────────────────────────┐
│ 🤖 Multi-Agent Strategy Crew (4 agentes)       │
├─────────────────────────────────────────────────┤
│ 1. Triage Strategist                            │
│    └─ Clasifica: F1, F2, F3, F4 o JUNK         │
│                                                 │
│ 2. Business Analyst (en paralelo con 3)        │
│    ├─ search_similar(threshold=0.85)           │
│    ├─ Si existe → MODIFICA iniciativa          │
│    └─ Si nueva → CREA iniciativa               │
│                                                 │
│ 3. Researcher (en paralelo con 2)              │
│    └─ Valida viabilidad técnica (APIs, docs)   │
│                                                 │
│ 4. Coordinator                                  │
│    ├─ Revisa completitud                       │
│    ├─ Aprueba/rechaza                          │
│    └─ Solo escribe si aprobado                 │
└─────────────────────────────────────────────────┘
    ↓
HTMLStrategyTool → data/estrategia_descorcha.html
    ↓
TriageDecisionOutput (para notificaciones)
```

---

## 📝 **Cambios Realizados**

### **1. Eliminado `kickoff()` antiguo (triage "rápido")**

**Antes:**
```python
def kickoff(self, email_entrante: str):
    # Tier 1: Local LM Studio
    # Tier 2: Gemini fallback
    # Tier 3: Stub pipeline (ConfluenceMock)
```

**Ahora:**
```python
def kickoff(self, email_entrante: str):
    """Run UNIFIED triage using Multi-Agent Strategy Crew."""
    logger.info("🚀 Iniciando triage con Multi-Agent Strategy Crew…")
    
    strategy_result = self.kickoff_strategy_crew(email_entrante)
    
    # Convertir a TriageDecisionOutput
    if strategy_result.get("status") == "approved":
        return TriageDecisionOutput(
            classification="STRATEGIC",
            actions_taken=[ActionRecord(tool="HTMLStrategyTool", ...)]
        )
```

### **2. Eliminadas herramientas mock del `__init__`**

**Antes:**
```python
self.confluence_tool = ConfluenceUpsertTool()  # ❌ Mock
self.email_tool = EmailDraftingTool()          # ❌ Mock
self.notification_tool = LeaderNotificationTool()  # ❌ Mock
```

**Ahora:**
```python
# Solo tools de input (lectura)
self.email_inbox_tool = EmailInboxTool()
self.chat_inbox_tool = ChatMessageInboxTool()
```

**NOTA:** HTMLStrategyTool se instancia dentro del Business Analyst agent

### **3. Eliminado método `_build_crewai_crew`**

Ya no se necesita crew para triage "rápido" - solo Multi-Agent Strategy Crew

### **4. Eliminado método `_parse_crewai_output`**

Ya no parseamos output del triage tradicional - solo del Strategy Crew

---

## 🔒 **Control de Calidad Garantizado**

### **Antes (triage rápido):**
- ❌ Sin deduplicación
- ❌ Sin validación técnica
- ❌ Escribe directo sin revisión
- ❌ No persiste (solo mock)

### **Ahora (Multi-Agent Crew):**
- ✅ **Deduplicación**: Business Analyst busca similarity > 0.85
- ✅ **Validación técnica**: Researcher valida APIs/docs con SerperDevTool
- ✅ **Aprobación**: Coordinator revisa antes de escribir
- ✅ **Persistencia**: HTMLStrategyTool escribe a `estrategia_descorcha.html`
- ✅ **Clasificación**: Triage Strategist asigna Foco correcto (F1-F4)

---

## 📊 **Comparación de Flujos**

| Aspecto | Triage "Rápido" (old) | Multi-Agent Crew (new) |
|---------|----------------------|------------------------|
| **Velocidad** | ~5s | ~30-60s |
| **Calidad** | ❌ Básica | ✅ Alta |
| **Deduplicación** | ❌ No | ✅ Sí (ChromaDB) |
| **Validación técnica** | ❌ No | ✅ Sí (Researcher) |
| **Aprobación** | ❌ No | ✅ Sí (Coordinator) |
| **Persistencia** | ❌ Mock | ✅ HTML real |
| **SSOT** | ❌ No actualiza | ✅ Actualiza HTML |
| **Control de calidad** | ❌ No | ✅ 4 agentes validan |

**Conclusión:** Sacrificamos velocidad (5s → 30s) a cambio de **calidad garantizada** del HTML SSOT

---

## 🚀 **Testing del Nuevo Flujo**

### **Test 1: Iniciativa nueva**

```python
crew = TriageCrew()
result = crew.kickoff("""
De: cto@descorcha.cl
Asunto: Propuesta integración MultiVende

Necesitamos integrar MultiVende para mejorar el OTD.
Propongo hacer un adaptador que conecte Shopify con MultiVende API.
""")

# Resultado esperado:
# - classification: "STRATEGIC"
# - actions_taken: [{"tool": "HTMLStrategyTool", "status": "ok"}]
# - HTML actualizado con nueva iniciativa en F1 (Logística)
```

### **Test 2: Modificación existente**

```python
result = crew.kickoff("""
De: cto@descorcha.cl
Asunto: Ajuste Vilaport

Necesitamos ajustar precios en el comparador Vilaport para competir con Vinos del Mundo.
""")

# Resultado esperado:
# - classification: "STRATEGIC"
# - Busca F4-101 (similarity > 0.85)
# - Actualiza con <mark>Ajustar precios dinámicos</mark>
```

### **Test 3: No estratégico**

```python
result = crew.kickoff("""
De: marketing@descorcha.cl
Asunto: Cambiar logo de la web

¿Podemos cambiar el logo del header?
""")

# Resultado esperado:
# - classification: "JUNK"
# - discarded: True
# - HTML NO actualizado
```

---

## 🛠️ **Archivos Modificados**

### **`src/triage_crew.py`**
- ❌ Eliminado: `kickoff()` antiguo (3 tiers: local/Gemini/stub)
- ✅ Nuevo: `kickoff()` unificado (solo Strategy Crew)
- ❌ Eliminado: `_build_crewai_crew()` (ya no se usa)
- ❌ Eliminado: `_parse_crewai_output()` (ya no se usa)
- ❌ Eliminado: Tools mock del `__init__` (Confluence, Email, Notification)
- ✅ Mantenido: `kickoff_strategy_crew()` (el único flujo)
- ✅ Mantenido: `kickoff_conversation()` (para conversaciones rápidas)

### **Archivos NO modificados (pero relevantes):**
- `src/strategy_tools/html_strategy_tool.py` - Única herramienta de escritura
- `data/estrategia_descorcha.html` - SSOT único
- `config/agents.yaml` - Configuración de 4 agentes
- `config/tasks.yaml` - Configuración de 4 tasks

---

## 🎯 **Próximos Pasos**

### **Inmediato (testing):**
1. ✅ Verificar compilación → **HECHO**
2. ⏳ Probar con conversación real en Telegram
3. ⏳ Verificar que HTML se actualice correctamente
4. ⏳ Validar deduplicación con iniciativa existente

### **Corto plazo (optimización):**
1. Agregar cache de ChromaDB para búsquedas rápidas
2. Implementar rate limiting en Strategy Crew (evitar sobrecarga Gemini)
3. Logging estructurado de decisiones (audit trail)

### **Mediano plazo (features):**
1. Dashboard de iniciativas (visualizar HTML)
2. Notificaciones a Telegram cuando HTML cambia
3. Integración con Confluence real (sincronizar cambios)

---

## 📚 **Referencias**

- **Documentación multi-agent:** `IMPLEMENTACION_MULTI_AGENT.md`
- **HTML SSOT:** `data/estrategia_descorcha.html`
- **Tool de estrategia:** `src/strategy_tools/html_strategy_tool.py`
- **Configuración agents:** `config/agents.yaml`

---

**Estado:** ✅ **IMPLEMENTADO Y COMPILADO**  
**Pendiente:** Testing en Telegram con conversación real
