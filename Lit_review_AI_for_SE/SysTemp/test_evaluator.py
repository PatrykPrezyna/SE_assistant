from Lit_review_AI_for_SE.SysTemp.evaluation import SysTempEvaluator
import os

# Initialize evaluator
evaluator = SysTempEvaluator()

# Test specification
test_spec = """Write me a specification for a bike fork made of aluminum 
with a 1" 1/8 Aheadset pivot. The fork should weigh less than 500 grams."""

print("Running SysTempEvaluator Ablation Study:")
print("=" * 70)
print(f"Test Specification:\n{test_spec}\n")
print("=" * 70)

# Evaluate with template
print("\n1. Evaluating WITH Template (Full Pipeline):")
print("-" * 70)
try:
    with_template_result = evaluator.evaluate_with_template(test_spec)
    print("With Template Result:")
    print(with_template_result)
    print("-" * 70)
except Exception as e:
    print(f"Error in with_template evaluation: {str(e)}")
    with_template_result = None

# Evaluate without template
print("\n2. Evaluating WITHOUT Template (Direct WriterAgent):")
print("-" * 70)
try:
    without_template_model, errors = evaluator.evaluate_without_template(test_spec)
    print("Without Template Model:")
    print(without_template_model)
    print(f"\nValidation Errors:")
    print(errors)
    print("-" * 70)
except Exception as e:
    print(f"Error in without_template evaluation: {str(e)}")
    without_template_model = None
    errors = None

# Comparison
print("\n" + "=" * 70)
print("Comparison Summary:")
print("=" * 70)
if with_template_result:
    print(f"With Template - Length: {len(str(with_template_result))} characters")
if without_template_model:
    print(f"Without Template - Length: {len(str(without_template_model))} characters")
    if errors:
        error_count = evaluator.count_errors(errors)
        print(f"Without Template - Error Count: {error_count}")
