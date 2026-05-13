from Lit_review_AI_for_SE.SysTemp.template import TemplateGeneratorAgent
import os
import json

# Initialize agent
agent = TemplateGeneratorAgent(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY")
)

# Sample structured dictionary from spec agent
structured_dict = {
    "Package": "BikeFork",
    "attributes": {
        "material": "Material type",
        "pivot_size": "Pivot size"
    },
    "constraints": {
        "weight_limit": "Minimize weight"
    },
    "requirements": {
        "Material": "Aluminum fork",
        "Pivot": "1\" 1/8 Aheadset pivot"
    }
}

# Generate template skeleton
result = agent.process(structured_dict)

# Print formatted output
print("Template Generation Result:")
print("=" * 50)
print(result)
print("=" * 50)
print(f"\nTemplate type: {type(result)}")
print(f"Template length: {len(result)} characters")
