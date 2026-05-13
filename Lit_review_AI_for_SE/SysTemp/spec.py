import openai
import json

class SpecificationGeneratorAgent:
    def __init__(self, model="gpt-4-turbo", api_key=None):
        self.model = model
        self.client = openai.Client(api_key=api_key)
        self.system_prompt = """You are an extractor-generator agent. You take a description 
in natural language and return a python dictionary of packages. The format should be:
{
    "Package": "PackageName",
    "attributes": {
        "attribute1": "attributeName", ...
    },
    "constraints": {
        "constraint1": "constraintName", ...
    },
    "requirements": {
        "requirement1": "requirement description", ...
    }
}
Each requirement should belong to a package with a relevant name and description."""

    def few_shot_examples(self):
        """Provide 3 examples for few-shot learning"""
        return [
            {
                "input": "I need a specification for a mountain bike with an aluminum frame weighing less than 3 kg and 720 mm handlebars.",
                "output": {
                    "Package": "MountainBike",
                    "attributes": {
                        "frame_weight": "Weight of frame",
                        "handlebar_width": "Width of handlebars"
                    },
                    "requirements": {
                        "FrameMaterial": "Aluminum frame",
                        "WeightConstraint": "Less than 3 kg"
                    }
                }
            },
            # Add 2 more examples...
        ]

    def process(self, natural_language_spec):
        """Process natural language input"""
        examples_text = self._format_examples()
        
        messages = [
            {
                "role": "system",
                "content": self.system_prompt
            },
            {
                "role": "user",
                "content": f"{examples_text}\n\nNow process this specification:\n{natural_language_spec}"
            }
        ]
        
        response = self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=0.3
        )
        
        # Print usage information
        print(f"\n[SpecificationGeneratorAgent] Usage: {response.usage.prompt_tokens} prompt tokens, {response.usage.completion_tokens} completion tokens")
        
        output_text = response.choices[0].message.content
        return json.loads(output_text)

    def _format_examples(self):
        """Format few-shot examples"""
        examples = self.few_shot_examples()
        formatted = ""
        for i, ex in enumerate(examples, 1):
            formatted += f"### Example {i}:\nInput: {ex['input']}\nOutput: {json.dumps(ex['output'])}\n\n"
        return formatted