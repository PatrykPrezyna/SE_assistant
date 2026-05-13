from Lit_review_AI_for_SE.SysTemp.orchestration import SysTempOrchestrator
import os
import json

# Initialize orchestrator
orchestrator = SysTempOrchestrator(
    llm_model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    java_parser_path="./parser.jar"  # Path to Java parser (if available)
)

# Natural language specification
spec = """Create a SysMLv2 model that structures a vehicle into its core components and specifies their relationships and constraints. This model should be capable of defining a generic vehicle with a chassis assembly that includes options for roll bars and wheels with lug bolts, and an engine that includes cylinders. Additionally, create specializations of this generic vehicle that demonstrate variations in the number of cylinders, types of roll bars, and quantity of lug bolts to showcase different vehicle configurations."""

# Run the complete pipeline
print("Running SysTempOrchestrator Pipeline:")
print("=" * 70)
print(f"Input Specification:\n{spec}\n")
print("=" * 70)

result = orchestrator.generate(spec)

print("\n" + "=" * 70)
print("Final Generated Model:")
print("=" * 70)
print(result)
print("=" * 70)
print(f"\nFinal model type: {type(result)}")
print(f"Final model length: {len(result)} characters")
