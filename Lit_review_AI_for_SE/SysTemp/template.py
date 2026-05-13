from jinja2 import Template

class TemplateGeneratorAgent:
    def __init__(self, model="gpt-4-turbo", api_key=None):
        self.model = model
        self.system_prompt = """You are a SysML V2 template generator. You take a list of 
requirements and generate a SysML V2 template. You only write textual SysML V2 code 
encapsulated between ``` markers.

Example:
package package_name { 
    part part_name { 
        attribute attribute_name; 
    } 
}"""
        
        # Define Jinja2 template
        self.jinja_template = """package {{ package_name }} {
    doc /* This is the package containing the requirements */
    {% for requirement in requirements %}
    requirement {{ requirement.name }} {
        doc /* {{ requirement.description }} */
        {% if requirement.attributes %}
        {% for attribute in requirement.attributes %}
        attribute {{ attribute.name }} = {{ attribute.value }} {{ attribute.units }};
        {% endfor %}
        {% endif %}
    }
    {% endfor %}
}"""

    def process(self, structured_dict):
        """Generate skeleton from structured dictionary by directly applying Jinja2 template"""
        
        # Convert requirements dict to list of objects for template rendering
        requirements_list = []
        for req_name, req_desc in structured_dict.get("requirements", {}).items():
            requirements_list.append({
                "name": req_name,
                "description": req_desc,
                "attributes": []
            })
        
        # Apply Jinja2 template DIRECTLY to structured dictionary
        # No LLM processing - template tool applies rules directly
        template = Template(self.jinja_template)
        skeleton = template.render(
            package_name=structured_dict.get("Package", "DefaultPackage"),
            requirements=requirements_list
        )
        
        print(f"\n[TemplateGeneratorAgent] Skeleton generated (no LLM call - direct template application)")
        
        return skeleton