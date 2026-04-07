"""
HTMLStrategyTool — Read/write Descorcha strategic initiatives in HTML SSOT.

This tool provides surgical CRUD operations on `data/estrategia_descorcha.html`:
- read_initiative(id)       : Extract initiative by ID (F1-106, F2-208, etc.)
- update_initiative(id, new) : Update existing initiative with <mark> highlighting
- create_initiative(foco, data) : Add new initiative to specified Foco column
- search_similar(query, threshold) : Semantic search for duplicates (ChromaDB)

The tool is designed to work with the multi-agent crew (BA, Researcher) and
prevent duplication by consulting ChromaDB before writing.
"""
from __future__ import annotations
import os
import json
import logging
import re
from typing import Any, Dict, List, Optional
from pathlib import Path

from bs4 import BeautifulSoup, NavigableString
try:
    from crewai.tools import BaseTool  # type: ignore
except ImportError:
    # Fallback si crewai no está disponible
    class BaseTool:  # type: ignore
        name: str = ""
        description: str = ""
        def _run(self, **kwargs): raise NotImplementedError

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


# Schema de argumentos para CrewAI
class HTMLStrategyToolInput(BaseModel):
    """Input schema for HTMLStrategyTool."""
    action: str = Field(
        ..., 
        description="Action to perform: 'read', 'update', 'create', 'search', 'list_all'"
    )
    initiative_id: Optional[str] = Field(
        None, 
        description="Initiative ID (e.g., 'F1-106') for read/update actions"
    )
    query: Optional[str] = Field(
        None, 
        description="Search query for 'search' action"
    )
    threshold: Optional[float] = Field(
        0.85, 
        description="Similarity threshold for 'search' action (0.0-1.0)"
    )
    foco: Optional[str] = Field(
        None, 
        description="Foco ID (F1-F4) for 'create' action"
    )
    initiative_data: Optional[Dict[str, str]] = Field(
        None, 
        description="Initiative data dict for 'create' action"
    )
    new_content: Optional[Dict[str, str]] = Field(
        None, 
        description="Updated content dict for 'update' action"
    )
    mark_changed: Optional[bool] = Field(
        True, 
        description="Highlight changes with <mark> tags for 'update' action"
    )


class HTMLStrategyTool(BaseTool):
    """Tool to read/write strategic initiatives in HTML SSOT."""
    
    name: str = "html_strategy_database"
    description: str = (
        "Manage Descorcha strategic initiatives in HTML SSOT (data/estrategia_descorcha.html). "
        "Actions: 'read' (get initiative by ID), 'search' (find similar initiatives), "
        "'create' (add new initiative), 'update' (modify existing), 'list_all' (get all IDs). "
        "Use this to document strategic initiatives validated by the multi-agent crew."
    )
    args_schema: type[BaseModel] = HTMLStrategyToolInput
    
    html_path: str = Field(default="data/estrategia_descorcha.html")
    
    def _run(
        self,
        action: str,
        initiative_id: Optional[str] = None,
        query: Optional[str] = None,
        threshold: float = 0.85,
        foco: Optional[str] = None,
        initiative_data: Optional[Dict[str, str]] = None,
        new_content: Optional[Dict[str, str]] = None,
        mark_changed: bool = True
    ) -> str:
        """Execute action on HTML SSOT.
        
        Args:
            action: One of ['read', 'update', 'create', 'search', 'list_all']
            initiative_id: Initiative ID for read/update
            query: Search query for search action
            threshold: Similarity threshold for search
            foco: Foco ID for create action
            initiative_data: Data dict for create action
            new_content: Updated content for update action
            mark_changed: Highlight changes for update action
            
        Returns:
            JSON string with result
        """
        # ── AUDIT LOG: confirmar que el agente realmente invocó el tool ──────
        print(f"\n🔧 [HTMLStrategyTool._run] INVOCADO — action={action!r}, query={query!r}, foco={foco!r}, initiative_id={initiative_id!r}")
        logger.info("HTMLStrategyTool._run called: action=%s query=%s foco=%s initiative_id=%s", action, query, foco, initiative_id)

        if action == "read":
            if not initiative_id:
                return json.dumps({"status": "error", "message": "initiative_id required for 'read' action"})
            return self._read_initiative(initiative_id)
        
        elif action == "update":
            if not initiative_id or not new_content:
                return json.dumps({"status": "error", "message": "initiative_id and new_content required for 'update' action"})
            return self._update_initiative(initiative_id, new_content, mark=mark_changed)
        
        elif action == "create":
            if not foco or not initiative_data:
                return json.dumps({"status": "error", "message": "foco and initiative_data required for 'create' action"})
            return self._create_initiative(foco, initiative_data)
        
        elif action == "search":
            if not query:
                return json.dumps({"status": "error", "message": "query required for 'search' action"})
            return self._search_similar(query, threshold=threshold)
        
        elif action == "list_all":
            return self._list_all_initiatives()
        
        else:
            return json.dumps({
                "status": "error",
                "message": f"Unknown action: {action}. Valid: read, update, create, search, list_all"
            })
    
    def _get_html_path(self) -> Path:
        """Get absolute path to HTML file."""
        workspace_root = Path(__file__).parent.parent.parent
        return workspace_root / self.html_path
    
    def _load_soup(self) -> BeautifulSoup:
        """Load HTML file as BeautifulSoup object."""
        html_file = self._get_html_path()
        if not html_file.exists():
            raise FileNotFoundError(f"HTML SSOT not found: {html_file}")
        
        with open(html_file, 'r', encoding='utf-8') as f:
            return BeautifulSoup(f.read(), 'html.parser')
    
    def _save_soup(self, soup: BeautifulSoup) -> None:
        """Save modified BeautifulSoup back to HTML file."""
        html_file = self._get_html_path()
        with open(html_file, 'w', encoding='utf-8') as f:
            f.write(str(soup.prettify()))
        logger.info(f"HTML SSOT updated: {html_file}")
    
    def _read_initiative(self, initiative_id: str) -> str:
        """Read initiative by ID (e.g., 'F1-106', 'F2-208').
        
        Returns:
            JSON string with initiative details
        """
        try:
            soup = self._load_soup()
            element = soup.find(id=initiative_id)
            
            if not element:
                return json.dumps({
                    "status": "not_found",
                    "initiative_id": initiative_id,
                    "message": f"Initiative {initiative_id} not found in HTML SSOT"
                })
            
            # Extract structured data
            title_elem = element.find('h3')
            status_elem = element.find('p', class_='status')
            
            paragraphs = element.find_all('p')
            objective = ""
            impact = ""
            owner = ""
            deadline = ""
            
            for p in paragraphs:
                text = p.get_text()
                if text.startswith("Objetivo:"):
                    objective = text.replace("Objetivo:", "").strip()
                elif text.startswith("Impacto:"):
                    impact = text.replace("Impacto:", "").strip()
                elif text.startswith("Owner:"):
                    owner = text.replace("Owner:", "").strip()
                elif text.startswith("Deadline:"):
                    deadline = text.replace("Deadline:", "").strip()
            
            return json.dumps({
                "status": "ok",
                "initiative_id": initiative_id,
                "title": title_elem.get_text() if title_elem else "",
                "status_text": status_elem.get_text() if status_elem else "",
                "objective": objective,
                "impact": impact,
                "owner": owner,
                "deadline": deadline,
                "html_content": str(element)
            }, ensure_ascii=False, indent=2)
            
        except Exception as exc:
            logger.error(f"Error reading initiative {initiative_id}: {exc}")
            return json.dumps({
                "status": "error",
                "message": str(exc)
            })
    
    def _update_initiative(self, initiative_id: str, new_content: Dict[str, str], mark: bool = True) -> str:
        """Update existing initiative with new content.
        
        Args:
            initiative_id: ID like 'F4-101'
            new_content: Dict with keys: title, objective, impact, owner, deadline
            mark: If True, wrap updated fields in <mark> tags
            
        Returns:
            JSON string with result
        """
        try:
            soup = self._load_soup()
            element = soup.find(id=initiative_id)
            
            if not element:
                return json.dumps({
                    "status": "not_found",
                    "initiative_id": initiative_id,
                    "message": f"Initiative {initiative_id} not found"
                })
            
            # Update fields if provided
            if 'title' in new_content:
                title_elem = element.find('h3')
                if title_elem:
                    title_elem.string = new_content['title']
            
            # Update paragraphs
            for p in element.find_all('p'):
                text = p.get_text()
                
                if text.startswith("Objetivo:") and 'objective' in new_content:
                    new_text = f"Objetivo: {new_content['objective']}"
                    if mark:
                        p.clear()
                        p.append(soup.new_tag('strong'))
                        p.strong.string = "Objetivo: "
                        mark_tag = soup.new_tag('mark')
                        mark_tag.string = new_content['objective']
                        p.append(mark_tag)
                    else:
                        p.string = new_text
                
                elif text.startswith("Impacto:") and 'impact' in new_content:
                    new_text = f"Impacto: {new_content['impact']}"
                    if mark:
                        p.clear()
                        p.append(soup.new_tag('strong'))
                        p.strong.string = "Impacto: "
                        mark_tag = soup.new_tag('mark')
                        mark_tag.string = new_content['impact']
                        p.append(mark_tag)
                    else:
                        p.string = new_text
                
                elif text.startswith("Owner:") and 'owner' in new_content:
                    p.string = f"Owner: {new_content['owner']}"
                
                elif text.startswith("Deadline:") and 'deadline' in new_content:
                    p.string = f"Deadline: {new_content['deadline']}"
            
            self._save_soup(soup)
            
            return json.dumps({
                "status": "ok",
                "action": "updated",
                "initiative_id": initiative_id,
                "updated_fields": list(new_content.keys()),
                "marked": mark
            }, ensure_ascii=False, indent=2)
            
        except Exception as exc:
            logger.error(f"Error updating initiative {initiative_id}: {exc}")
            return json.dumps({
                "status": "error",
                "message": str(exc)
            })
    
    def _create_initiative(self, foco: str, initiative_data: Dict[str, str]) -> str:
        """Create new initiative in specified Foco column.
        
        Args:
            foco: One of ['F1', 'F2', 'F3', 'F4']
            initiative_data: Dict with: title, status, objective, impact, owner, deadline
                            (id is optional - will be auto-generated if not provided)
            
        Returns:
            JSON string with result
        """
        try:
            soup = self._load_soup()
            
            # Validate foco
            if foco not in ['F1', 'F2', 'F3', 'F4']:
                return json.dumps({
                    "status": "error",
                    "message": f"Invalid foco: {foco}. Must be F1, F2, F3, or F4"
                })
            
            # Find the correct <td> column (0=F1, 1=F2, 2=F3, 3=F4)
            table = soup.find('table', id='focos-estrategicos')
            if not table:
                return json.dumps({
                    "status": "error",
                    "message": "Table 'focos-estrategicos' not found in HTML"
                })
            
            tbody = table.find('tbody')
            row = tbody.find('tr')
            columns = row.find_all('td')
            
            foco_index = int(foco[1]) - 1  # F1 → 0, F2 → 1, etc.
            target_column = columns[foco_index]
            
            # Auto-generate ID if not provided
            if 'id' not in initiative_data or not initiative_data['id']:
                # Find existing initiatives in this foco to get next ID
                existing_initiatives = target_column.find_all('div', class_='initiative')
                existing_ids = []
                for init in existing_initiatives:
                    init_id = init.get('id', '')
                    if init_id.startswith(f'{foco}-'):
                        try:
                            num = int(init_id.split('-')[1])
                            existing_ids.append(num)
                        except (IndexError, ValueError):
                            pass
                
                # Generate next ID
                next_id = max(existing_ids) + 1 if existing_ids else 101
                initiative_data['id'] = f'{foco}-{next_id}'
                
                logger.info(f"Auto-generated initiative ID: {initiative_data['id']}")
            
            # Create new initiative div
            new_div = soup.new_tag('div', attrs={'class': 'initiative', 'id': initiative_data['id']})
            
            # Title
            h3 = soup.new_tag('h3')
            h3.string = initiative_data.get('title', 'Nueva Iniciativa')
            new_div.append(h3)
            
            # Status
            p_status = soup.new_tag('p', attrs={'class': 'status'})
            p_status.string = f"Status: {initiative_data.get('status', 'Planificado')}"
            new_div.append(p_status)
            
            # Objective
            p_obj = soup.new_tag('p')
            strong_obj = soup.new_tag('strong')
            strong_obj.string = "Objetivo: "
            p_obj.append(strong_obj)
            p_obj.append(initiative_data.get('objective', ''))
            new_div.append(p_obj)
            
            # Impact
            p_imp = soup.new_tag('p')
            strong_imp = soup.new_tag('strong')
            strong_imp.string = "Impacto: "
            p_imp.append(strong_imp)
            p_imp.append(initiative_data.get('impact', ''))
            new_div.append(p_imp)
            
            # Owner
            p_own = soup.new_tag('p')
            strong_own = soup.new_tag('strong')
            strong_own.string = "Owner: "
            p_own.append(strong_own)
            p_own.append(initiative_data.get('owner', 'TBD'))
            new_div.append(p_own)
            
            # Deadline
            p_dead = soup.new_tag('p')
            strong_dead = soup.new_tag('strong')
            strong_dead.string = "Deadline: "
            p_dead.append(strong_dead)
            p_dead.append(initiative_data.get('deadline', 'TBD'))
            new_div.append(p_dead)
            
            # Append to column
            target_column.append(new_div)
            
            self._save_soup(soup)
            
            return json.dumps({
                "status": "ok",
                "action": "created",
                "initiative_id": initiative_data['id'],
                "foco": foco,
                "title": initiative_data.get('title')
            }, ensure_ascii=False, indent=2)
            
        except Exception as exc:
            logger.error(f"Error creating initiative in {foco}: {exc}")
            return json.dumps({
                "status": "error",
                "message": str(exc)
            })
    
    def _search_similar(self, query: str, threshold: float = 0.85) -> str:
        """Search for similar initiatives using semantic similarity.
        
        Uses ChromaDB to find initiatives with similarity > threshold.
        
        Args:
            query: Search query (e.g., "ajustar precios Vilaport")
            threshold: Similarity threshold (0.0-1.0), default 0.85
            
        Returns:
            JSON string with matching initiatives
        """
        try:
            from src.conversation_memory import create_user_memory
            
            # Use strategy-specific memory collection
            memory = create_user_memory("strategy_initiatives", max_topics=50)
            
            # Query ChromaDB
            results = memory.collection.query(
                query_texts=[query],
                n_results=5
            )
            
            if not results or not results['ids'] or len(results['ids'][0]) == 0:
                return json.dumps({
                    "status": "ok",
                    "query": query,
                    "matches": [],
                    "message": "No similar initiatives found"
                })
            
            # Convert distances to similarities and filter by threshold
            matches = []
            for i, doc_id in enumerate(results['ids'][0]):
                distance = results['distances'][0][i]
                similarity = 1 - distance  # ChromaDB returns L2 distance, convert to similarity
                
                if similarity >= threshold:
                    metadata = results['metadatas'][0][i] if results.get('metadatas') else {}
                    matches.append({
                        "initiative_id": metadata.get('initiative_id', doc_id),
                        "similarity": round(similarity, 3),
                        "content": results['documents'][0][i],
                        "metadata": metadata
                    })
            
            # Sort by similarity descending
            matches.sort(key=lambda x: x['similarity'], reverse=True)
            
            return json.dumps({
                "status": "ok",
                "query": query,
                "threshold": threshold,
                "matches": matches,
                "action": "MODIFICACIÓN" if matches else "NUEVA_INICIATIVA"
            }, ensure_ascii=False, indent=2)
            
        except Exception as exc:
            logger.error(f"Error searching similar initiatives: {exc}")
            return json.dumps({
                "status": "error",
                "message": str(exc),
                "action": "NUEVA_INICIATIVA"  # Fallback: create new if search fails
            })
    
    def _list_all_initiatives(self) -> str:
        """List all initiatives in HTML SSOT.
        
        Returns:
            JSON string with all initiative IDs and titles
        """
        try:
            soup = self._load_soup()
            initiatives = []
            
            for div in soup.find_all('div', class_='initiative'):
                initiative_id = div.get('id')
                title_elem = div.find('h3')
                title = title_elem.get_text() if title_elem else ""
                
                initiatives.append({
                    "id": initiative_id,
                    "title": title
                })
            
            return json.dumps({
                "status": "ok",
                "total": len(initiatives),
                "initiatives": initiatives
            }, ensure_ascii=False, indent=2)
            
        except Exception as exc:
            logger.error(f"Error listing initiatives: {exc}")
            return json.dumps({
                "status": "error",
                "message": str(exc)
            })


# Convenience function for testing
def test_html_tool():
    """Test HTMLStrategyTool basic operations."""
    tool = HTMLStrategyTool()
    
    print("=" * 80)
    print("TEST 1: Read existing initiative F4-101")
    print("=" * 80)
    result = tool._run("read", initiative_id="F4-101")
    print(result)
    
    print("\n" + "=" * 80)
    print("TEST 2: Search similar to 'precios Vilaport'")
    print("=" * 80)
    result = tool._run("search", query="precios Vilaport competencia", threshold=0.85)
    print(result)
    
    print("\n" + "=" * 80)
    print("TEST 3: List all initiatives")
    print("=" * 80)
    result = tool._run("list_all")
    print(result)
    
    print("\n✅ HTMLStrategyTool tests completed")


if __name__ == "__main__":
    test_html_tool()
