import xml.etree.ElementTree as ET
import re
import sys

def extract_mermaid_positions(svg_file):
    """Extract positions from Mermaid SVG export"""
    
    tree = ET.parse(svg_file)
    root = tree.getroot()
    
    # Namespace handling
    ns = {'svg': 'http://www.w3.org/2000/svg'}
    
    positions = {}
    
    # Find all text elements with their parent transforms
    for text in root.findall('.//svg:text', ns):
        parent = text
        transform = ""
        
        # Traverse up to find transform attribute
        for g in root.findall('.//svg:g', ns):
            if text in g:
                transform = g.get('transform', '')
                break
        
        if transform and 'translate' in transform:
            match = re.search(r'translate\(([^,]+),([^)]+)\)', transform)
            if match:
                x = float(match.group(1))
                y = float(match.group(2))
                label = ''.join(text.itertext()).strip()
                positions[label] = (x, y)
    
    return positions

def generate_graphviz(positions):
    """Generate Graphviz DOT with positions"""
    
    dot = 'digraph TherapeuticSystem {\n'
    dot += '  rankdir=LR;\n'
    dot += '  node [shape=box, style=filled, fillcolor="#E8F4F8", color="#0066CC"];\n\n'
    
    for label, (x, y) in positions.items():
        # Scale positions if needed (adjust multiplier)
        dot += f'  {label.replace(" ", "_")} [label="{label}", pos="{x/10},{y/10}!"];\n'
    
    dot += '}\n'
    return dot

if __name__ == "__main__":
    svg_file = sys.argv[1]
    positions = extract_mermaid_positions(svg_file)
    graphviz_code = generate_graphviz(positions)
    print(graphviz_code)