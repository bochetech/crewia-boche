#!/usr/bin/env python3
from bs4 import BeautifulSoup
from pathlib import Path

html_path = Path('data/estrategia_descorcha.html')

with open(html_path, 'r', encoding='utf-8') as f:
    soup = BeautifulSoup(f.read(), 'html.parser')

# Buscar todas las iniciativas en F3
f3_col = soup.find('div', id='F3')
if f3_col:
    initiatives = f3_col.find_all('div', class_='initiative')
    
    print(f'Total iniciativas en F3: {len(initiatives)}')
    print()
    
    # Mostrar la última iniciativa (la que acabamos de crear)
    if initiatives:
        last_init = initiatives[-1]
        init_id = last_init.get('id')
        title = last_init.find('h3')
        status = last_init.find('p', class_='status')
        
        # Buscar párrafos
        paragraphs = last_init.find_all('p')
        
        print(f'ÚLTIMA INICIATIVA CREADA:')
        print(f'ID: {init_id}')
        print(f'Título: {title.get_text() if title else "N/A"}')
        print(f'Status: {status.get_text() if status else "N/A"}')
        print()
        print('Detalles:')
        for p in paragraphs:
            text = p.get_text().strip()
            if text and not text.startswith('Status:'):
                print(f'  {text[:200]}')
