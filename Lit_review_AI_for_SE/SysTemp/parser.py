import subprocess
import tempfile
import os

class ParserAgent:
    def __init__(self, model="gpt-4-turbo", api_key=None, java_parser_path="./parser.jar"):
        self.java_parser_path = java_parser_path

    def process(self, sysml_code):
        """Validate SysML v2 code and return errors using the Java parser"""
        return self._validate_with_java_parser(sysml_code)

    def _validate_with_java_parser(self, sysml_code):
        """Call external Java parser for formal validation"""
        try:
            # Write code to temporary file
            with tempfile.NamedTemporaryFile(mode='w', suffix='.sysml', delete=False) as f:
                f.write(sysml_code)
                temp_file = f.name
            
            # Run Java parser
            result = subprocess.run(
                ['java', '-jar', self.java_parser_path, temp_file],
                capture_output=True,
                text=True,
                timeout=10
            )
            
            # Clean up
            os.unlink(temp_file)
            
            errors = result.stdout
            if result.returncode != 0:
                errors += result.stderr
            
            return errors if errors else "No syntax errors detected"
            
        except Exception as e:
            return f"Validation error: {str(e)}"