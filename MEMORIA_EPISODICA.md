# Sistema de Memoria Episódica con Clustering Semántico

## Concepto

Implementación de memoria conversacional inspirada en la mente humana:
- **Memoria de corto plazo**: Últimos 10 mensajes (timeout 10 min)
- **Memoria de largo plazo**: Hasta 10 "cajones" temáticos con embeddings semánticos

## Arquitectura

```
Usuario conversa → Mensajes agregados a:
                   ├─ Short-term (últimos 10, in-memory)
                   └─ ChromaDB (embeddings, persistente)
                            ↓
                   Clustering automático
                   (similitud semántica)
                            ↓
              ┌─────────────┴───────────────┐
              │ Cajones temáticos (max 10)  │
              ├─────────────────────────────┤
              │ Cajón 1: SAP integración    │
              │ Cajón 2: Shopify eCommerce  │
              │ Cajón 3: Logística 3PL      │
              │ ...                         │
              └─────────────────────────────┘
                            ↓
          Triage solicita contexto:
          ├─ "analiza lo de SAP" → Búsqueda semántica → Cajón 1
          ├─ "haz el triage"     → Cajón más reciente
          └─ "/recall logística" → Búsqueda explícita → Cajón 3
```

## Componentes

### 1. `src/conversation_memory.py`
- **`TopicMemory`**: Clase principal de memoria semántica
- **`create_user_memory(user_id)`**: Factory para crear memoria por usuario
- **ChromaDB**: Base vectorial persistente (`./data/chroma`)
- **Embeddings**: `paraphrase-multilingual-MiniLM-L12-v2` (español/inglés)

### 2. `src/telegram_bot.py`
Modificaciones:
- `_handle_conversation()`: Agrega mensajes a memoria semántica
- `_handle_message()`: Detecta tema mencionado y recupera contexto
- `/topics`: Ver cajones activos
- `/recall <tema>`: Buscar conversación por tema

## Flujo de uso

### Conversación normal
```
Usuario: "Hablemos de integración SAP"
  → Agregado a short-term
  → Agregado a ChromaDB
  → Clusterizado en cajón "SAP integración"

Usuario: "¿Qué enfoque recomiendas?"
  → Mismo cajón (similitud semántica alta)

Usuario: "Cambiando de tema, Shopify..."
  → Nuevo cajón "Shopify eCommerce"
```

### Triage con contexto semántico
```
Usuario: "analiza lo de SAP que hablamos"
  → Detecta keyword "SAP"
  → Búsqueda semántica en ChromaDB
  → Recupera cajón SAP (todos los mensajes relacionados)
  → Envía contexto completo a kickoff()
  → Triage analiza con contexto relevante ✅

Usuario: "haz el triage" (sin tema específico)
  → No detecta keyword
  → Toma cajón más reciente (por timestamp)
  → Envía contexto a kickoff()
```

### Comandos
```
/topics
→ 🗂️ Cajones activos de memoria:
  1. `Necesitamos integrar SAP...` — 3 mensajes
  2. `Cambiando de tema, Shopify...` — 4 mensajes
  3. `Necesito discutir sobre logística...` — 2 mensajes

/recall SAP
→ 🧠 Recuerdos sobre: SAP
  Usuario: Necesitamos integrar SAP...
  Nia: La integración SAP requiere...
  Usuario: ¿Qué enfoque recomiendas?

/nueva
→ Limpia short-term (memoria semántica persiste)
```

## Diferencias clave vs solución anterior

| Aspecto | Solución anterior | Nueva solución |
|---------|------------------|----------------|
| Tipo memoria | Solo short-term (10 msgs) | Short-term + Semántica (embeddings) |
| Persistencia | In-memory (se pierde al reiniciar) | ChromaDB (persiste) |
| Recuperación | Últimos N mensajes | Búsqueda semántica por tema |
| Clustering | Manual (ninguno) | Automático (similitud vectorial) |
| Capacidad | 10 mensajes max | 10 cajones × ~5 msgs = ~50 mensajes |
| Robustez | Frágil (timeout 10 min) | Robusta (persiste semanas) |

## Ventajas

1. **Contexto inteligente**: Recupera temas relevantes, no solo mensajes recientes
2. **Persistencia**: Sobrevive reinicios del bot
3. **Escalabilidad**: Maneja conversaciones largas organizándolas en cajones
4. **Búsqueda natural**: "analiza lo de Shopify" → encuentra automáticamente
5. **Sin keywords frágiles**: Similitud semántica vs regex patterns

## Configuración

### Variables de entorno
Ninguna adicional. Usa configuración por defecto:
- `max_topics=10`: Máximo cajones simultáneos
- `messages_per_topic=5`: Promedio de mensajes por cajón
- Persistence dir: `./data/chroma` (auto-creado)

### Dependencias
```bash
pip install chromadb sentence-transformers
```

## Testing

### Test unitario
```bash
python test_memory_clustering.py
```

**Output esperado:**
```
✅ TODOS LOS TESTS PASARON
Arquitectura validada:
  ✓ Clustering automático funciona
  ✓ Búsqueda semántica por tema funciona
  ✓ Recuperación de contexto reciente funciona
  ✓ Memoria persiste en ChromaDB
```

### Test de integración (Telegram)
```bash
python main.py --mode telegram
```

**Escenario de prueba:**
1. Conversar sobre SAP (3-4 mensajes)
2. Cambiar de tema a Shopify (3-4 mensajes)
3. Cambiar a logística 3PL (2-3 mensajes)
4. Enviar `/topics` → Ver 3 cajones activos
5. Enviar "analiza lo de SAP" → Verificar que recupera contexto SAP
6. Enviar "haz el triage" → Verificar que usa cajón más reciente (3PL)

## Mantenimiento

### Limpiar base de datos
```python
from src.conversation_memory import create_user_memory

memory = create_user_memory("user_id")
memory.clear()  # Borra todos los mensajes del usuario
```

### Ajustar parámetros
```python
# En telegram_bot.py, modificar:
memory = create_user_memory(
    user_id,
    max_topics=15,  # Aumentar cajones
    messages_per_topic=10  # Más mensajes por cajón
)
```

## Troubleshooting

### Error: "chromadb not installed"
```bash
.venv313/bin/pip install chromadb sentence-transformers
```

### Error: "No space left on device"
ChromaDB genera embeddings (~50MB por modelo). Verificar espacio:
```bash
du -sh ./data/chroma
```

### Cajones no se crean correctamente
Verificar que los mensajes tengan suficiente contenido (>10 palabras) y que no sean idénticos. El clustering requiere variación semántica.

## Roadmap futuro

- [ ] Summarization de cajones antiguos (comprimir contexto)
- [ ] Configuración dinámica de max_topics por usuario
- [ ] Estadísticas de uso de memoria (`/memory_stats`)
- [ ] Exportar/importar memoria (backup/restore)
- [ ] Multi-idioma (detectar idioma dominante por cajón)

## Referencias

- [Memory Networks (Facebook AI, 2015)](https://arxiv.org/abs/1503.08895)
- [RAG with Vector Stores](https://python.langchain.com/docs/modules/data_connection/retrievers/)
- [ChromaDB Documentation](https://docs.trychroma.com/)
- [Sentence Transformers](https://www.sbert.net/)
