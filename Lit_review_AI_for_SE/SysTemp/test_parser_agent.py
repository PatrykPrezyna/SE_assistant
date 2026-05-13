from Lit_review_AI_for_SE.SysTemp.parser import ParserAgent
import os

# Initialize agent
agent = ParserAgent(
    model="gpt-4o-mini",
    api_key=os.getenv("OPENAI_API_KEY"),
    java_parser_path="./parser.jar"  # Path to Java parser (if available)
)

# Sample valid SysML v2 code
valid_sysml = """package BikeFork {
    doc /* This is a bike fork specification */
    requirement Material {
        doc /* The fork should be made of aluminum */
        attribute material_type = aluminum;
    }
    requirement Pivot {
        doc /* Standard 1" 1/8 Aheadset pivot */
        attribute pivot_size = 1_125_inch;
    }
}"""

# Sample invalid SysML v2 code (with syntax error)
invalid_sysml = """package BikeFork {
    doc /* This has a syntax error */
    requirement Material {
        doc /* Missing semicolon below */
        attribute material_type = aluminum
    }
}"""

# Test with valid code
print("Testing Valid SysML Code:")
print("=" * 50)
result_valid = agent.process(valid_sysml)
print(result_valid)
print("=" * 50)

# Test with invalid code
print("\nTesting Invalid SysML Code:")
print("=" * 50)
result_invalid = agent.process(invalid_sysml)
print(result_invalid)
print("=" * 50)

# Validation results
print("\nValidation Summary:")
print(f"Valid code result: {result_valid}")
print(f"Invalid code result: {result_invalid}")
