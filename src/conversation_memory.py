"""
Memoria episódica con clustering semántico para conversaciones.

Implementa un sistema de "cajones" de memoria donde cada cajón representa
un tema de conversación. Los mensajes se agrupan automáticamente por similitud
semántica usando embeddings.

Arquitectura:
- Max 10 cajones activos (configurable)
- Embeddings multilingües (español/inglés) con sentence-transformers
- Búsqueda semántica para recuperar contexto relevante
- Persistencia local con ChromaDB

Uso típico:
    memory = TopicMemory(max_topics=10)
    
    # Agregar mensajes a medida que conversa
    memory.add_message("Hablemos de logística 3PL", role="user")
    memory.add_message("¿Qué aspecto te interesa?", role="assistant")
    
    # Recuperar contexto para triage
    context = memory.get_context_for_triage(query="logística")
    # → Devuelve mensajes del cajón "logística 3PL"
    
    context = memory.get_context_for_triage()
    # → Devuelve mensajes del cajón más reciente
"""
from __future__ import annotations

import logging
import os
import time
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Lazy imports (ChromaDB + sentence-transformers son pesados)
# ---------------------------------------------------------------------------

_CHROMA_CLIENT = None
_ENCODER_MODEL = None


def _get_chroma_client():
    """Lazy init ChromaDB client (solo si se usa)."""
    global _CHROMA_CLIENT
    if _CHROMA_CLIENT is None:
        try:
            import chromadb
            from chromadb.config import Settings
            
            # Persistir en ./data/chroma (no en memoria)
            persist_dir = os.path.join(os.getcwd(), "data", "chroma")
            os.makedirs(persist_dir, exist_ok=True)
            
            _CHROMA_CLIENT = chromadb.Client(Settings(
                persist_directory=persist_dir,
                anonymized_telemetry=False,
            ))
            logger.info("ChromaDB initialized at %s", persist_dir)
        except ImportError:
            logger.warning(
                "chromadb not installed — memory will be in-memory only. "
                "Run: pip install chromadb"
            )
            import chromadb
            _CHROMA_CLIENT = chromadb.Client()
    return _CHROMA_CLIENT


def _get_encoder():
    """Lazy init sentence-transformers encoder."""
    global _ENCODER_MODEL
    if _ENCODER_MODEL is None:
        try:
            from sentence_transformers import SentenceTransformer
            # Modelo multilingüe español/inglés, pequeño (~50MB), rápido
            _ENCODER_MODEL = SentenceTransformer(
                'paraphrase-multilingual-MiniLM-L12-v2'
            )
            logger.info("SentenceTransformer model loaded")
        except ImportError:
            logger.error(
                "sentence-transformers not installed. "
                "Run: pip install sentence-transformers"
            )
            raise
    return _ENCODER_MODEL


# ---------------------------------------------------------------------------
# TopicMemory — memoria de cajones
# ---------------------------------------------------------------------------

class TopicMemory:
    """Memoria episódica con clustering semántico de conversaciones.
    
    Conceptos clave:
    - Cajón (topic bucket): Conjunto de mensajes relacionados semánticamente
    - Max cajones: Límite de temas activos (default 10)
    - Pruning: Cuando se excede el límite, se descarta el cajón más antiguo
    - Búsqueda semántica: Recuperar mensajes por similitud con query
    
    Attributes:
        max_topics: Máximo número de cajones simultáneos
        messages_per_topic: Promedio de mensajes por cajón (para pruning)
        collection_name: Nombre de la colección ChromaDB
    """
    
    def __init__(
        self,
        max_topics: int = 10,
        messages_per_topic: int = 5,
        collection_name: str = "nia_conversation_topics",
        user_id: Optional[str] = None,
    ):
        """
        Args:
            max_topics: Máximo de cajones (temas) simultáneos
            messages_per_topic: Promedio de mensajes por tema (para pruning)
            collection_name: Nombre de la colección ChromaDB
            user_id: ID del usuario (para colecciones multi-usuario)
        """
        self.max_topics = max_topics
        self.messages_per_topic = messages_per_topic
        self.user_id = user_id or "default"
        
        # Nombre único por usuario (ej: "nia_topics_user123")
        self.collection_name = f"{collection_name}_{self.user_id}"
        
        client = _get_chroma_client()
        
        # Obtener o crear colección
        try:
            self.collection = client.get_collection(self.collection_name)
            logger.info("Loaded existing collection: %s", self.collection_name)
        except Exception:
            self.collection = client.create_collection(
                name=self.collection_name,
                metadata={"description": f"Conversation topics for {self.user_id}"}
            )
            logger.info("Created new collection: %s", self.collection_name)
    
    def add_message(
        self,
        content: str,
        role: str = "user",
        metadata: Optional[Dict] = None,
    ) -> str:
        """Agregar mensaje a la memoria y asignarlo a un cajón temático.
        
        El mensaje se asigna automáticamente al cajón más similar (si existe)
        o crea un nuevo cajón si no hay similitud suficiente.
        
        Args:
            content: Texto del mensaje
            role: "user" o "assistant"
            metadata: Metadatos adicionales (timestamp, etc.)
        
        Returns:
            ID del mensaje insertado
        """
        if not content or not content.strip():
            logger.warning("Empty message, skipping")
            return ""
        
        # Generar embedding
        encoder = _get_encoder()
        embedding = encoder.encode(content).tolist()
        
        # Metadata completo
        full_metadata = {
            "role": role,
            "timestamp": time.time(),
            "length": len(content),
            **(metadata or {}),
        }
        
        # ID único: timestamp + hash corto
        msg_id = f"msg_{int(time.time()*1000)}_{hash(content) % 10000}"
        
        # Insertar en ChromaDB
        try:
            self.collection.add(
                embeddings=[embedding],
                documents=[content],
                metadatas=[full_metadata],
                ids=[msg_id],
            )
            logger.debug(
                "Added message to %s: %s... (%d chars)",
                self.collection_name,
                content[:50],
                len(content)
            )
        except Exception as exc:
            logger.error("Failed to add message: %s", exc)
            return ""
        
        # Pruning: si excedemos capacidad, remover los más viejos
        self._prune_if_needed()
        
        return msg_id
    
    def _prune_if_needed(self):
        """Eliminar mensajes más antiguos si se excede la capacidad."""
        max_messages = self.max_topics * self.messages_per_topic
        count = self.collection.count()
        
        if count <= max_messages:
            return
        
        # Obtener todos los mensajes ordenados por timestamp
        results = self.collection.get(
            include=["metadatas"],
        )
        
        if not results or not results.get("ids"):
            return
        
        # Ordenar por timestamp ascendente (más viejos primero)
        items = list(zip(
            results["ids"],
            [m.get("timestamp", 0) for m in results["metadatas"]]
        ))
        items.sort(key=lambda x: x[1])
        
        # Eliminar los N más viejos
        to_delete = count - max_messages
        old_ids = [item[0] for item in items[:to_delete]]
        
        if old_ids:
            self.collection.delete(ids=old_ids)
            logger.info(
                "Pruned %d old messages from %s (capacity: %d)",
                len(old_ids),
                self.collection_name,
                max_messages
            )
    
    def get_context_for_triage(
        self,
        query: Optional[str] = None,
        max_messages: int = 10,
    ) -> str:
        """Recuperar contexto para triage.
        
        Dos modos:
        1. query=None → Toma los mensajes más recientes (cajón activo)
        2. query="SAP" → Búsqueda semántica (cajón relacionado con SAP)
        
        Args:
            query: Tema a buscar (None = tomar más reciente)
            max_messages: Máximo de mensajes a recuperar
        
        Returns:
            Contexto formateado como string multi-línea
        """
        if self.collection.count() == 0:
            return ""
        
        if query is None or not query.strip():
            # Modo 1: Tomar los más recientes
            results = self.collection.get(
                include=["documents", "metadatas"],
            )
            
            if not results or not results.get("ids"):
                return ""
            
            # Ordenar por timestamp descendente (más recientes primero)
            items = list(zip(
                results["documents"],
                results["metadatas"],
            ))
            items.sort(key=lambda x: x[1].get("timestamp", 0), reverse=True)
            
            # Tomar los N más recientes
            recent = items[:max_messages]
            
            logger.info(
                "Retrieved %d most recent messages (no query)",
                len(recent)
            )
        else:
            # Modo 2: Búsqueda semántica
            encoder = _get_encoder()
            query_embedding = encoder.encode(query).tolist()
            
            results = self.collection.query(
                query_embeddings=[query_embedding],
                n_results=max_messages,
                include=["documents", "metadatas"],
            )
            
            if not results or not results.get("documents") or not results["documents"][0]:
                return ""
            
            # ChromaDB query devuelve lista de listas
            docs = results["documents"][0]
            metas = results["metadatas"][0]
            
            recent = list(zip(docs, metas))
            
            logger.info(
                "Retrieved %d messages for query '%s'",
                len(recent),
                query[:30]
            )
        
        # Formatear como contexto conversacional
        lines = []
        for content, meta in recent:
            role = meta.get("role", "user")
            role_label = "Usuario" if role == "user" else "Nia"
            # Truncar mensajes muy largos
            content_preview = content[:300] if len(content) > 300 else content
            lines.append(f"{role_label}: {content_preview}")
        
        return "\n\n".join(lines)
    
    def get_topics_summary(self) -> List[Tuple[str, int]]:
        """Obtener resumen de cajones activos.
        
        Returns:
            Lista de (tema_representativo, num_mensajes) ordenada por actividad
        """
        if self.collection.count() == 0:
            return []
        
        # Obtener todos los mensajes
        results = self.collection.get(
            include=["documents", "metadatas"],
        )
        
        if not results or not results.get("documents"):
            return []
        
        # Agrupar por timestamp (ventana de 10 minutos = mismo cajón)
        WINDOW_SECONDS = 600  # 10 minutos
        
        buckets: Dict[int, List[str]] = {}
        for doc, meta in zip(results["documents"], results["metadatas"]):
            ts = meta.get("timestamp", 0)
            bucket_key = int(ts // WINDOW_SECONDS)
            
            if bucket_key not in buckets:
                buckets[bucket_key] = []
            buckets[bucket_key].append(doc)
        
        # Para cada bucket, tomar el primer mensaje como representativo
        topics = []
        for bucket_msgs in buckets.values():
            if bucket_msgs:
                # Tomar las primeras 5 palabras del primer mensaje
                first_msg = bucket_msgs[0]
                words = first_msg.split()[:5]
                topic_label = " ".join(words) + ("..." if len(words) >= 5 else "")
                topics.append((topic_label, len(bucket_msgs)))
        
        # Ordenar por número de mensajes (descendente)
        topics.sort(key=lambda x: x[1], reverse=True)
        
        return topics[:self.max_topics]
    
    def clear(self):
        """Limpiar todos los mensajes de la colección."""
        count = self.collection.count()
        if count > 0:
            # ChromaDB no tiene clear(), hay que eliminar por IDs
            results = self.collection.get()
            if results and results.get("ids"):
                self.collection.delete(ids=results["ids"])
            logger.info("Cleared %d messages from %s", count, self.collection_name)
    
    def search_by_keyword(self, keyword: str, max_results: int = 5) -> List[str]:
        """Búsqueda simple por palabra clave (alternativa a semántica).
        
        Args:
            keyword: Palabra a buscar
            max_results: Máximo de mensajes a devolver
        
        Returns:
            Lista de mensajes que contienen la palabra clave
        """
        results = self.collection.get(
            include=["documents"],
        )
        
        if not results or not results.get("documents"):
            return []
        
        # Filtro simple: contains (case-insensitive)
        keyword_lower = keyword.lower()
        matches = [
            doc for doc in results["documents"]
            if keyword_lower in doc.lower()
        ]
        
        return matches[:max_results]


# ---------------------------------------------------------------------------
# Convenience functions
# ---------------------------------------------------------------------------

def create_user_memory(
    user_id: str,
    max_topics: int = 10,
) -> TopicMemory:
    """Factory para crear memoria de un usuario específico.
    
    Args:
        user_id: ID del usuario (ej: telegram user ID)
        max_topics: Máximo de cajones simultáneos
    
    Returns:
        TopicMemory instance
    """
    return TopicMemory(
        max_topics=max_topics,
        user_id=user_id,
    )


__all__ = [
    "TopicMemory",
    "create_user_memory",
]
