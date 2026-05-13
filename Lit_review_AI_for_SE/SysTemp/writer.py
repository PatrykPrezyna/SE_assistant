import openai
import json

class WriterAgent:
    def __init__(self, model="gpt-4-turbo", api_key=None):
        self.model = model
        self.client = openai.Client(api_key=api_key)
        self.system_prompt = """You are a SysML V2 code generator. You complete a template 
with requirements or generate a full model from a requirements dictionary if no template is provided. 
You should never add or remove requirements or change the logical intent of the input.
Output only textual SysML V2 code between ``` markers.

Examples:
package package_name { 
    part part_name { 
        attribute attribute_name; 
    } 
}"""

    def process(self, skeleton, structured_dict, parser_feedback=""):
        """Complete skeleton or generate full SysML V2 model based on specifications and feedback"""
        
        few_shot_examples = self._get_examples()
        
        if skeleton:
            prompt = f"""Template skeleton:
{skeleton}

Requirements dictionary:
{json.dumps(structured_dict)}

{f"Parser feedback to fix: {parser_feedback}" if parser_feedback else ""}

Please complete the template with detailed specifications."""
        else:
            prompt = f"""Requirements dictionary:
{json.dumps(structured_dict)}

{f"Parser feedback to fix: {parser_feedback}" if parser_feedback else ""}

Please create a complete SysML V2 model that includes all requirements from the dictionary."""
        
        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            },
            {
                "role": "user",
                "content": f"{few_shot_examples}\n\n{prompt}"
            }
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3
        )
        
        # Print usage information
        print(f"\n[WriterAgent] Usage: {response.usage.prompt_tokens} prompt tokens, {response.usage.completion_tokens} completion tokens")
        
        completed_model = response.choices[0].message.content
        # Extract code between markers
        return self._extract_code(completed_model)

    def _get_examples(self):
        """Provide few-shot examples"""
        return """### Example 1:
Input template: package BikeFork { requirement Material { doc /* Material requirement */ } }
Output: package BikeFork { requirement Material { doc /* The bike fork should be made of aluminum. */ attribute material_type = aluminum; } }"""

    def _extract_code(self, text):
        """Extract SysML v2 code from response"""
        if "```" in text:
            start = text.find("```") + 3
            end = text.rfind("```")
            return text[start:end].strip()
        return text.strip()