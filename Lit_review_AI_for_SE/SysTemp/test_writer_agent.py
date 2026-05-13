from Lit_review_AI_for_SE.SysTemp.writer import WriterAgent
import os
import json

# Initialize agent
agent = WriterAgent(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY")
)

# Sample skeleton from template agent
skeleton = """package BikeFork {
    doc /* This is the package containing the requirements */
    requirement Material {
        doc /* Aluminum fork */
    }
    requirement Pivot {
        doc /* 1" 1/8 Aheadset pivot */
    }
}"""

# Sample structured dictionary
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
        "Material": "Aluminum fork made from 6061 aluminum alloy",
        "Pivot": "1\" 1/8 Aheadset pivot compatible with standard headsets"
    }
}

# Generate completed model
result = agent.process(skeleton, structured_dict)

# Print formatted output
print("Writer Agent Result:")
print("=" * 50)
print(result)
print("=" * 50)
print(f"\nGenerated code type: {type(result)}")
print(f"Generated code length: {len(result)} characters")
print(f"\nContains 'package': {'package' in result}")
print(f"Contains 'requirement': {'requirement' in result}")
