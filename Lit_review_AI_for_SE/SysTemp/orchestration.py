import json
from Lit_review_AI_for_SE.SysTemp.spec import SpecificationGeneratorAgent
from Lit_review_AI_for_SE.SysTemp.template import TemplateGeneratorAgent
from Lit_review_AI_for_SE.SysTemp.writer import WriterAgent
from Lit_review_AI_for_SE.SysTemp.parser import ParserAgent

class SysTempOrchestrator:
    def __init__(self, llm_model="gpt-4-turbo", api_key=None, java_parser_path="./parser.jar", use_template=True, parser_agent=None):
        self.spec_agent = SpecificationGeneratorAgent(model=llm_model, api_key=api_key)
        self.template_agent = TemplateGeneratorAgent(model=llm_model, api_key=api_key)
        self.writer_agent = WriterAgent(model=llm_model, api_key=api_key)
        self.parser_agent = parser_agent if parser_agent is not None else ParserAgent(java_parser_path=java_parser_path)
        self.max_iterations = 5
        self.use_template = use_template

    def generate(self, natural_language_spec):
        """Main pipeline execution"""
        
        print("Step 1: Extracting specifications...")
        structured_dict = self.spec_agent.process(natural_language_spec)
        print(f"✓ Structured dictionary created:\n{json.dumps(structured_dict, indent=2)}\n")
        
        if self.use_template:
            print("Step 2: Generating SysML v2 skeleton...")
            skeleton = self.template_agent.process(structured_dict)
            print(f"✓ Skeleton generated:\n{skeleton}\n")
        else:
            skeleton = None
            print("Step 2: Skipping template generation (ablation mode).\n")
        
        print("Step 3: Completing model and validating...")
        parser_feedback = ""
        completed_model = None
        
        for iteration in range(self.max_iterations):
            print(f"Iteration {iteration + 1}:")
            
            completed_model = self.writer_agent.process(
                skeleton,
                structured_dict,
                parser_feedback
            )
            print(f"  Generated model:\n{completed_model}\n")
            
            if not self.parser_agent:
                print("  No parser available; stopping after first iteration.\n")
                break
            
            errors = self.parser_agent.process(completed_model)
            print(f"  Validation result: {errors}\n")
            
            if "no errors" in errors.lower() or "no syntax errors" in errors.lower():
                print("✓ Model is valid! Exiting iteration loop.\n")
                break
            parser_feedback = errors
        
        return completed_model

# Usage
if __name__ == "__main__":
    orchestrator = SysTempOrchestrator(api_key="your-api-key")
    
    spec = """Write me a specification for a bike fork made of aluminum 
    with a 1" 1/8 Aheadset pivot."""
    
    result = orchestrator.generate(spec)
    print("Final SysML v2 Model:")
    print(result)
    