from Lit_review_AI_for_SE.SysTemp.spec import SpecificationGeneratorAgent
import os
import json

# Initialize agent
agent = SpecificationGeneratorAgent(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY")
)

# Run specification extraction
spec = "Write me a specification for a bike fork made of aluminum with a 1\" 1/8 Aheadset pivot."
result = agent.process(spec)

# Print formatted output
print("Specification Extract:")
print(json.dumps(result, indent=2))