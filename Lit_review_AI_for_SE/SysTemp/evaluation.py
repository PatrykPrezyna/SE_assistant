from Lit_review_AI_for_SE.SysTemp.orchestration import SysTempOrchestrator
from Lit_review_AI_for_SE.SysTemp.spec import SpecificationGeneratorAgent
from Lit_review_AI_for_SE.SysTemp.writer import WriterAgent
from Lit_review_AI_for_SE.SysTemp.parser import ParserAgent

class SysTempEvaluator:
    """Ablation study: with vs without TemplateGeneratorAgent"""
    
    def evaluate_with_template(self, spec):
        orchestrator = SysTempOrchestrator()
        return orchestrator.generate(spec)
    
    def evaluate_without_template(self, spec):
        """Direct WriterAgent without skeleton"""
        spec_agent = SpecificationGeneratorAgent()
        writer_agent = WriterAgent()
        parser_agent = ParserAgent()
        
        structured_dict = spec_agent.process(spec)
        model = writer_agent.process("", structured_dict, "")
        
        errors = parser_agent.process(model)
        return model, errors
    
    def count_errors(self, validation_output):
        """Count syntax errors"""
        return validation_output.count("Error:")

# Run comparison
evaluator = SysTempEvaluator()
with_template_result = evaluator.evaluate_with_template(test_spec)
without_template_model, errors = evaluator.evaluate_without_template(test_spec)