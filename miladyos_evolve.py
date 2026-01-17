#!/usr/bin/env python3
"""
MiladyOS AlphaEvolve Integration
Evolutionary optimization of Jenkins pipelines using LLM-based code generation
"""

import asyncio
import json
import logging
import os
import random
import re
import time
import uuid
from datetime import datetime
from typing import Dict, List, Optional, Tuple, Any
import colorlog

# Configure logging
logger = colorlog.getLogger("miladyos-evolve")
handler = colorlog.StreamHandler()
handler.setFormatter(colorlog.ColoredFormatter(
    "%(log_color)s%(levelname)s%(reset)s: %(message)s"
))
logger.handlers = []
logger.addHandler(handler)
logger.setLevel(logging.INFO)


class JenkinsfileParser:
    """Utility for parsing and manipulating Jenkinsfile content."""
    
    @staticmethod
    def extract_evolve_blocks(content: str) -> List[Dict[str, Any]]:
        """
        Extract sections marked with // EVOLVE-BLOCK-START and // EVOLVE-BLOCK-END
        Returns list of blocks with their content and position information.
        """
        blocks = []
        lines = content.split('\n')
        in_block = False
        current_block = None
        
        for i, line in enumerate(lines):
            stripped = line.strip()
            
            if stripped.startswith('// EVOLVE-BLOCK-START'):
                if in_block:
                    logger.warning(f"Nested EVOLVE block found at line {i+1}, ignoring")
                    continue
                    
                # Extract block metadata from comment
                metadata = {}
                if ':' in stripped:
                    meta_part = stripped.split(':', 1)[1].strip()
                    if meta_part:
                        try:
                            metadata = json.loads(meta_part)
                        except json.JSONDecodeError:
                            logger.warning(f"Invalid metadata in EVOLVE block at line {i+1}")
                
                current_block = {
                    'start_line': i,
                    'metadata': metadata,
                    'content_lines': []
                }
                in_block = True
                
            elif stripped.startswith('// EVOLVE-BLOCK-END'):
                if not in_block:
                    logger.warning(f"EVOLVE-BLOCK-END without start at line {i+1}")
                    continue
                    
                current_block['end_line'] = i
                current_block['content'] = '\n'.join(current_block['content_lines'])
                blocks.append(current_block)
                current_block = None
                in_block = False
                
            elif in_block:
                current_block['content_lines'].append(line)
        
        if in_block:
            logger.warning("Unclosed EVOLVE block found")
            
        return blocks
    
    @staticmethod
    def replace_evolve_blocks(content: str, new_blocks: List[Dict[str, Any]]) -> str:
        """Replace EVOLVE blocks with new content."""
        lines = content.split('\n')
        result_lines = []
        block_index = 0
        i = 0
        
        while i < len(lines):
            line = lines[i].strip()
            
            if line.startswith('// EVOLVE-BLOCK-START') and block_index < len(new_blocks):
                # Find the corresponding end
                result_lines.append(lines[i])  # Keep the start comment
                
                # Add the new block content
                new_content = new_blocks[block_index]['content']
                result_lines.extend(new_content.split('\n'))
                
                # Skip to the end of the original block
                while i < len(lines) and not lines[i].strip().startswith('// EVOLVE-BLOCK-END'):
                    i += 1
                
                if i < len(lines):
                    result_lines.append(lines[i])  # Keep the end comment
                
                block_index += 1
            else:
                result_lines.append(lines[i])
            
            i += 1
        
        return '\n'.join(result_lines)
    
    @staticmethod
    def extract_metrics_from_console(console_output: str) -> Dict[str, float]:
        """Extract performance metrics from Jenkins console output."""
        metrics = {
            'duration_seconds': 0.0,
            'success_rate': 0.0,
            'error_count': 0.0,
            'warning_count': 0.0
        }
        
        # Extract duration from Jenkins output
        duration_patterns = [
            r'Build took (\d+\.?\d*) seconds',
            r'Total time: (\d+\.?\d*) seconds',
            r'Duration: (\d+)ms',
            r'Finished: \w+ .*Completed in (\d+\.?\d*)s'
        ]
        
        for pattern in duration_patterns:
            match = re.search(pattern, console_output, re.IGNORECASE)
            if match:
                duration = float(match.group(1))
                if 'ms' in pattern:
                    duration /= 1000.0
                metrics['duration_seconds'] = duration
                break
        
        # Count errors and warnings
        metrics['error_count'] = len(re.findall(r'\bERROR\b|\bFAILED\b', console_output, re.IGNORECASE))
        metrics['warning_count'] = len(re.findall(r'\bWARNING\b|\bWARN\b', console_output, re.IGNORECASE))
        
        # Determine success rate based on console output
        if re.search(r'\bSUCCESS\b|\bFinished: SUCCESS\b', console_output, re.IGNORECASE):
            metrics['success_rate'] = 1.0
        elif re.search(r'\bFAILED\b|\bFinished: FAILURE\b', console_output, re.IGNORECASE):
            metrics['success_rate'] = 0.0
        else:
            metrics['success_rate'] = 0.5  # Uncertain
        
        return metrics


class LLMCodeGenerator:
    """LLM-based code generation for evolving Jenkins pipelines."""
    
    def __init__(self, model_name: str = "openai/gpt-4"):
        self.model_name = model_name
        self.generation_count = 0
    
    async def generate_variant(self, original_code: str, goal: str, 
                              execution_history: List[Dict], 
                              metadata: Dict = None) -> str:
        """
        Generate a variant of the pipeline code using LLM.
        
        Args:
            original_code: The original code block to evolve
            goal: Evolution goal (e.g., 'reduce_execution_time')
            execution_history: Past execution results for context
            metadata: Additional metadata about the block
        
        Returns:
            Generated code variant
        """
        self.generation_count += 1
        
        # Create context-rich prompt
        prompt = self._create_evolution_prompt(
            original_code, goal, execution_history, metadata
        )
        
        # For now, simulate LLM generation with rule-based improvements
        # In production, this would call an actual LLM API
        return await self._simulate_llm_generation(original_code, goal, prompt)
    
    def _create_evolution_prompt(self, code: str, goal: str, 
                               history: List[Dict], metadata: Dict) -> str:
        """Create a detailed prompt for the LLM."""
        
        goal_descriptions = {
            'reduce_execution_time': 'optimize for faster execution and reduced build time',
            'improve_success_rate': 'improve reliability and reduce failure rate',
            'optimize_resource_usage': 'reduce CPU, memory, and resource consumption',
            'enhance_parallelization': 'increase parallelism and concurrent execution',
            'improve_error_handling': 'add better error handling and recovery mechanisms'
        }
        
        goal_desc = goal_descriptions.get(goal, goal)
        
        prompt = f"""You are an expert DevOps engineer tasked with optimizing Jenkins pipeline code.

GOAL: {goal_desc}

ORIGINAL CODE:
```groovy
{code}
```

EXECUTION HISTORY:
"""
        
        # Add relevant execution data
        if history:
            for i, execution in enumerate(history[-5:]):  # Last 5 executions
                prompt += f"""
Execution {i+1}:
- Status: {execution.get('status', 'unknown')}
- Duration: {execution.get('duration', 'unknown')}s
- Success: {execution.get('result') == 'SUCCESS'}
- Errors: {execution.get('error_count', 0)}
"""
        
        prompt += f"""

REQUIREMENTS:
1. The code must be valid Jenkins pipeline syntax
2. Preserve the essential functionality while optimizing for the goal
3. Only modify the code between EVOLVE-BLOCK-START and EVOLVE-BLOCK-END markers
4. Focus specifically on {goal_desc}
5. Consider the execution history to avoid known failure patterns

Generate an improved version of the code that addresses the goal while maintaining compatibility:
"""
        
        return prompt
    
    async def _simulate_llm_generation(self, original_code: str, goal: str, prompt: str) -> str:
        """
        Simulate LLM generation with rule-based improvements.
        In production, replace with actual LLM API calls.
        """
        
        # Apply goal-specific transformations
        if goal == 'reduce_execution_time':
            return self._optimize_for_speed(original_code)
        elif goal == 'improve_success_rate':
            return self._optimize_for_reliability(original_code)
        elif goal == 'optimize_resource_usage':
            return self._optimize_for_resources(original_code)
        elif goal == 'enhance_parallelization':
            return self._optimize_for_parallelism(original_code)
        elif goal == 'improve_error_handling':
            return self._optimize_for_error_handling(original_code)
        else:
            return self._apply_random_mutation(original_code)
    
    def _optimize_for_speed(self, code: str) -> str:
        """Apply speed optimizations."""
        optimizations = [
            # Add parallel execution
            (r'(\s+)sh\s+[\'"]([^"\']+)[\'"]', r'\1script {\n\1    parallel {\n\1        a: { sh "\2" }\n\1    }\n\1}'),
            # Use faster checkout
            (r'checkout scm', 'checkout([$class: "GitSCM", branches: [[name: "*/main"]], userRemoteConfigs: [[url: env.GIT_URL]], extensions: [[$class: "CloneOption", depth: 1, shallow: true]]])'),
            # Add caching
            (r'(sh\s+[\'"].*npm install.*[\'"])', r'dir("node_modules") { \1 }'),
        ]
        
        modified_code = code
        for pattern, replacement in optimizations:
            if random.random() < 0.3:  # Apply with some probability
                modified_code = re.sub(pattern, replacement, modified_code)
        
        return modified_code
    
    def _optimize_for_reliability(self, code: str) -> str:
        """Add reliability improvements."""
        improvements = [
            # Add retry logic
            (r'(sh\s+[\'"][^"\']*)([\'"])', r'retry(3) { \1\2 }'),
            # Add error handling
            (r'(sh\s+[\'"][^"\']*[\'"])', r'try {\n                \1\n            } catch (Exception e) {\n                echo "Command failed: ${e.getMessage()}"\n                currentBuild.result = "UNSTABLE"\n            }'),
            # Add timeout
            (r'steps\s*\{', 'steps {\n            timeout(time: 10, unit: "MINUTES") {'),
        ]
        
        modified_code = code
        for pattern, replacement in improvements:
            if random.random() < 0.4:
                modified_code = re.sub(pattern, replacement, modified_code)
        
        return modified_code
    
    def _optimize_for_resources(self, code: str) -> str:
        """Optimize resource usage."""
        optimizations = [
            # Add resource constraints
            (r'agent\s+any', 'agent {\n        label "small-executor"\n        kubernetes {\n            limits { memory "512Mi"; cpu "0.5" }\n        }\n    }'),
            # Cleanup after operations
            (r'(sh\s+[\'"][^"\']*[\'"])', r'\1\n            sh "docker system prune -f || true"'),
        ]
        
        modified_code = code
        for pattern, replacement in optimizations:
            if random.random() < 0.3:
                modified_code = re.sub(pattern, replacement, modified_code)
        
        return modified_code
    
    def _optimize_for_parallelism(self, code: str) -> str:
        """Enhance parallelization."""
        # Wrap sequential operations in parallel blocks
        if 'parallel' not in code and 'sh' in code:
            # Find all sh commands and group them
            sh_commands = re.findall(r'sh\s+[\'"][^"\']*[\'"]', code)
            if len(sh_commands) > 1:
                parallel_block = "parallel {\n"
                for i, cmd in enumerate(sh_commands[:3]):  # Limit to 3 for safety
                    parallel_block += f"                task{i+1}: {{ {cmd} }}\n"
                parallel_block += "            }"
                
                # Replace first sh command with parallel block
                modified_code = code.replace(sh_commands[0], parallel_block, 1)
                
                # Remove other sh commands that are now in parallel
                for cmd in sh_commands[1:3]:
                    modified_code = modified_code.replace(cmd, '', 1)
                
                return modified_code
        
        return code
    
    def _optimize_for_error_handling(self, code: str) -> str:
        """Improve error handling."""
        improvements = [
            # Add comprehensive try-catch blocks
            (r'(sh\s+[\'"][^"\']*[\'"])', r'try {\n                \1\n            } catch (Exception e) {\n                echo "Error: ${e.getMessage()}"\n                emailext to: "${env.CHANGE_AUTHOR_EMAIL}", subject: "Build Failed", body: e.getMessage()\n                throw e\n            }'),
            # Add status checks
            (r'steps\s*\{', 'steps {\n            script {\n                if (currentBuild.currentResult != "SUCCESS") {\n                    error("Previous stage failed")\n                }\n            }'),
        ]
        
        modified_code = code
        for pattern, replacement in improvements:
            if random.random() < 0.5:
                modified_code = re.sub(pattern, replacement, modified_code)
        
        return modified_code
    
    def _apply_random_mutation(self, code: str) -> str:
        """Apply random mutations to the code."""
        mutations = [
            # Change timeout values
            (r'timeout\(time:\s*(\d+)', lambda m: f'timeout(time: {int(m.group(1)) + random.randint(-2, 5)}'),
            # Modify agent specification
            (r'agent\s+any', 'agent { label "linux" }'),
            # Add environment variables
            (r'steps\s*\{', 'steps {\n            script { env.OPTIMIZED = "true" }'),
        ]
        
        modified_code = code
        for pattern, replacement in mutations:
            if random.random() < 0.2:
                if callable(replacement):
                    modified_code = re.sub(pattern, replacement, modified_code)
                else:
                    modified_code = re.sub(pattern, replacement, modified_code)
        
        return modified_code


class TemplateEvolver:
    """Main evolution controller for Jenkins templates."""
    
    def __init__(self, template_name: str, goal: str, metadata_manager, templates_dir: str):
        self.template_name = template_name
        self.goal = goal
        self.metadata_manager = metadata_manager
        self.templates_dir = templates_dir
        self.generator = LLMCodeGenerator()
        self.evolution_id = str(uuid.uuid4())
        
        # Evolution state
        self.population = []
        self.generation = 0
        self.best_fitness = float('-inf')
        self.improvements = []
        
    async def evolve(self, iterations: int = 50, use_execution_history: bool = True,
                    population_size: int = 10, mutation_rate: float = 0.3) -> Dict[str, Any]:
        """
        Run the evolution process.
        
        Args:
            iterations: Number of evolution iterations
            use_execution_history: Whether to use historical execution data
            population_size: Size of evolution population
            mutation_rate: Rate of mutation in evolution
            
        Returns:
            Evolution results summary
        """
        logger.info(f"Starting evolution of template '{self.template_name}' for goal '{self.goal}'")
        
        # Load original template
        original_content = self._load_template()
        original_blocks = JenkinsfileParser.extract_evolve_blocks(original_content)
        
        if not original_blocks:
            # If no evolve blocks found, make the entire pipeline evolvable
            logger.info("No EVOLVE blocks found, making entire pipeline evolvable")
            evolve_content = f"// EVOLVE-BLOCK-START\n{original_content}\n// EVOLVE-BLOCK-END"
            self._save_template_with_evolve_blocks(evolve_content)
            original_content = evolve_content
            original_blocks = JenkinsfileParser.extract_evolve_blocks(original_content)
        
        # Get execution history if requested
        execution_history = []
        if use_execution_history:
            execution_history = self._get_execution_history()
        
        # Initialize population
        await self._initialize_population(
            original_blocks, execution_history, population_size
        )
        
        # Evolution loop
        start_time = time.time()
        for iteration in range(iterations):
            self.generation = iteration + 1
            logger.info(f"Evolution iteration {self.generation}/{iterations}")
            
            # Evaluate population
            await self._evaluate_population(iteration)
            
            # Select and breed next generation
            await self._evolve_generation(mutation_rate)
            
            # Check for early termination
            if self._should_terminate():
                logger.info(f"Early termination at iteration {self.generation}")
                break
        
        evolution_time = time.time() - start_time
        
        # Select best candidate and save result
        best_candidate = self._select_best_candidate()
        if best_candidate:
            self._save_evolved_template(best_candidate)
        
        # Create evolution summary
        summary = {
            'template_name': self.template_name,
            'goal': self.goal,
            'iterations_completed': self.generation,
            'total_time_seconds': evolution_time,
            'population_size': population_size,
            'mutation_rate': mutation_rate,
            'improvements': self.improvements,
            'best_candidate': best_candidate,
            'performance_gain': self._calculate_performance_gain(),
            'evolution_id': self.evolution_id
        }
        
        logger.info(f"Evolution completed in {evolution_time:.2f} seconds with {len(self.improvements)} improvements")
        
        return {
            'iterations_completed': self.generation,
            'improvements': self.improvements,
            'best_candidate': best_candidate,
            'performance_gain': self._calculate_performance_gain(),
            'summary': summary
        }
    
    def _load_template(self) -> str:
        """Load the original template content."""
        template_path = os.path.join(self.templates_dir, f"{self.template_name}.Jenkinsfile")
        if not os.path.exists(template_path):
            raise FileNotFoundError(f"Template file not found: {template_path}")
        
        with open(template_path, 'r') as f:
            return f.read()
    
    def _save_template_with_evolve_blocks(self, content: str):
        """Save template with EVOLVE blocks added."""
        template_path = os.path.join(self.templates_dir, f"{self.template_name}.Jenkinsfile")
        with open(template_path, 'w') as f:
            f.write(content)
    
    def _save_evolved_template(self, candidate: Dict[str, Any]):
        """Save the best evolved template."""
        # Save as a new template version
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        evolved_name = f"{self.template_name}_evolved_{timestamp}"
        evolved_path = os.path.join(self.templates_dir, f"{evolved_name}.Jenkinsfile")
        
        with open(evolved_path, 'w') as f:
            f.write(candidate['content'])
        
        logger.info(f"Saved evolved template as {evolved_name}")
        
        # Optionally replace the original template
        if candidate.get('fitness', 0) > self.best_fitness:
            original_path = os.path.join(self.templates_dir, f"{self.template_name}.Jenkinsfile")
            backup_path = os.path.join(self.templates_dir, f"{self.template_name}_backup_{timestamp}.Jenkinsfile")
            
            # Backup original
            os.rename(original_path, backup_path)
            
            # Replace with evolved version
            with open(original_path, 'w') as f:
                f.write(candidate['content'])
            
            logger.info(f"Replaced original template with evolved version (backup saved as {os.path.basename(backup_path)})")
    
    def _get_execution_history(self) -> List[Dict]:
        """Retrieve execution history for the template."""
        try:
            executions = self.metadata_manager.list_executions(
                template_name=self.template_name,
                limit=50  # Get last 50 executions
            )
            
            # Enhance with console output metrics if available
            enhanced_executions = []
            for execution in executions:
                try:
                    execution_id = execution.get('id')
                    if execution_id:
                        console_key = f"miladyos:console:{execution_id}"
                        console_output = self.metadata_manager.redis.get(console_key)
                        if console_output:
                            if isinstance(console_output, bytes):
                                console_output = console_output.decode('utf-8')
                            
                            metrics = JenkinsfileParser.extract_metrics_from_console(console_output)
                            execution.update(metrics)
                    
                    enhanced_executions.append(execution)
                except Exception as e:
                    logger.warning(f"Error enhancing execution {execution.get('id', 'unknown')}: {e}")
                    enhanced_executions.append(execution)
            
            logger.info(f"Retrieved {len(enhanced_executions)} historical executions")
            return enhanced_executions
            
        except Exception as e:
            logger.warning(f"Could not retrieve execution history: {e}")
            return []
    
    async def _initialize_population(self, original_blocks: List[Dict], 
                                   history: List[Dict], population_size: int):
        """Initialize the evolution population."""
        logger.info(f"Initializing population of size {population_size}")
        
        self.population = []
        
        # Add original as first member
        original_candidate = {
            'id': str(uuid.uuid4()),
            'content': self._blocks_to_content(original_blocks),
            'blocks': original_blocks,
            'generation': 0,
            'fitness': None,
            'metrics': {},
            'parent_ids': []
        }
        self.population.append(original_candidate)
        
        # Generate variants
        for i in range(population_size - 1):
            candidate = await self._generate_candidate(original_blocks, history, generation=0)
            self.population.append(candidate)
        
        logger.info(f"Population initialized with {len(self.population)} candidates")
    
    async def _generate_candidate(self, base_blocks: List[Dict], 
                                history: List[Dict], generation: int,
                                parent_ids: List[str] = None) -> Dict[str, Any]:
        """Generate a new candidate from base blocks."""
        
        evolved_blocks = []
        for block in base_blocks:
            evolved_content = await self.generator.generate_variant(
                block['content'], self.goal, history, block.get('metadata', {})
            )
            
            evolved_block = block.copy()
            evolved_block['content'] = evolved_content
            evolved_blocks.append(evolved_block)
        
        candidate = {
            'id': str(uuid.uuid4()),
            'content': self._blocks_to_content(evolved_blocks),
            'blocks': evolved_blocks,
            'generation': generation,
            'fitness': None,
            'metrics': {},
            'parent_ids': parent_ids or []
        }
        
        return candidate
    
    def _blocks_to_content(self, blocks: List[Dict]) -> str:
        """Convert blocks back to full Jenkinsfile content."""
        # For simplicity, assume we're working with a single evolvable block
        if blocks:
            return blocks[0]['content']
        return ""
    
    async def _evaluate_population(self, iteration: int):
        """Evaluate fitness of all candidates in the population."""
        logger.info(f"Evaluating population fitness for iteration {iteration}")
        
        for candidate in self.population:
            if candidate['fitness'] is None:
                fitness = await self._evaluate_candidate(candidate)
                candidate['fitness'] = fitness
                
                if fitness > self.best_fitness:
                    self.best_fitness = fitness
                    self.improvements.append({
                        'iteration': iteration,
                        'fitness': fitness,
                        'candidate_id': candidate['id'],
                        'improvement_percent': ((fitness - self.best_fitness) / abs(self.best_fitness)) * 100 if self.best_fitness != 0 else 100
                    })
    
    async def _evaluate_candidate(self, candidate: Dict[str, Any]) -> float:
        """
        Evaluate a single candidate's fitness.
        
        This is a simplified evaluation - in production, you would:
        1. Deploy the candidate template
        2. Run it in a test environment
        3. Measure actual performance metrics
        """
        
        # Static analysis based heuristics
        content = candidate['content']
        fitness = 0.0
        
        # Goal-specific scoring
        if self.goal == 'reduce_execution_time':
            # Favor parallel operations, caching, shallow clones
            if 'parallel' in content:
                fitness += 10
            if 'cache' in content or 'Cache' in content:
                fitness += 5
            if 'depth: 1' in content:
                fitness += 3
            
        elif self.goal == 'improve_success_rate':
            # Favor error handling, retries, timeouts
            if 'try' in content and 'catch' in content:
                fitness += 15
            if 'retry' in content:
                fitness += 10
            if 'timeout' in content:
                fitness += 5
                
        elif self.goal == 'optimize_resource_usage':
            # Favor resource constraints, cleanup
            if 'memory' in content and 'cpu' in content:
                fitness += 10
            if 'prune' in content or 'cleanup' in content:
                fitness += 5
                
        elif self.goal == 'enhance_parallelization':
            # Count parallel blocks
            parallel_count = content.count('parallel')
            fitness += parallel_count * 8
            
        elif self.goal == 'improve_error_handling':
            # Count error handling constructs
            error_handling = content.count('try') + content.count('catch') + content.count('finally')
            fitness += error_handling * 6
        
        # Penalties for potential issues
        if 'sudo' in content:
            fitness -= 5  # Security risk
        if len(content.split('\n')) > 200:
            fitness -= 10  # Too complex
        
        # Bonus for maintaining readability
        if '// ' in content:  # Has comments
            fitness += 2
            
        # Simulate execution metrics (replace with actual test execution)
        candidate['metrics'] = {
            'estimated_duration': max(10, 60 - fitness),  # Inverse relationship
            'estimated_success_rate': min(1.0, (50 + fitness) / 100),
            'complexity_score': len(content.split('\n')) / 10
        }
        
        return fitness
    
    async def _evolve_generation(self, mutation_rate: float):
        """Evolve to the next generation."""
        # Sort by fitness
        self.population.sort(key=lambda x: x['fitness'], reverse=True)
        
        # Keep top performers (elitism)
        elite_count = max(1, len(self.population) // 4)
        next_generation = self.population[:elite_count]
        
        # Generate offspring
        execution_history = self._get_execution_history()
        while len(next_generation) < len(self.population):
            # Select parents (tournament selection)
            parent1 = self._tournament_selection()
            parent2 = self._tournament_selection()
            
            # Create offspring
            offspring = await self._crossover(parent1, parent2, execution_history)
            
            # Apply mutation
            if random.random() < mutation_rate:
                offspring = await self._mutate(offspring, execution_history)
            
            next_generation.append(offspring)
        
        self.population = next_generation
    
    def _tournament_selection(self, tournament_size: int = 3) -> Dict[str, Any]:
        """Select a parent using tournament selection."""
        tournament = random.sample(self.population, min(tournament_size, len(self.population)))
        return max(tournament, key=lambda x: x['fitness'])
    
    async def _crossover(self, parent1: Dict[str, Any], parent2: Dict[str, Any], 
                        history: List[Dict]) -> Dict[str, Any]:
        """Create offspring through crossover."""
        # Simple crossover: randomly choose content from either parent
        base_blocks = random.choice([parent1['blocks'], parent2['blocks']])
        
        offspring = await self._generate_candidate(
            base_blocks, history, self.generation,
            parent_ids=[parent1['id'], parent2['id']]
        )
        
        return offspring
    
    async def _mutate(self, candidate: Dict[str, Any], history: List[Dict]) -> Dict[str, Any]:
        """Apply mutation to a candidate."""
        # Re-generate one of the blocks
        mutated_blocks = []
        for block in candidate['blocks']:
            if random.random() < 0.5:  # 50% chance to mutate each block
                evolved_content = await self.generator.generate_variant(
                    block['content'], self.goal, history, block.get('metadata', {})
                )
                mutated_block = block.copy()
                mutated_block['content'] = evolved_content
                mutated_blocks.append(mutated_block)
            else:
                mutated_blocks.append(block)
        
        candidate['blocks'] = mutated_blocks
        candidate['content'] = self._blocks_to_content(mutated_blocks)
        candidate['fitness'] = None  # Re-evaluate
        
        return candidate
    
    def _should_terminate(self) -> bool:
        """Check if evolution should terminate early."""
        # Terminate if no improvement in last 10 generations
        if len(self.improvements) > 0:
            last_improvement = self.improvements[-1]['iteration']
            if self.generation - last_improvement > 10:
                return True
        
        # Terminate if fitness is very high
        if self.best_fitness > 50:
            return True
            
        return False
    
    def _select_best_candidate(self) -> Optional[Dict[str, Any]]:
        """Select the best candidate from the final population."""
        if not self.population:
            return None
        
        return max(self.population, key=lambda x: x['fitness'])
    
    def _calculate_performance_gain(self) -> float:
        """Calculate overall performance gain from evolution."""
        if not self.improvements:
            return 0.0
        
        initial_fitness = 0.0
        final_fitness = self.best_fitness
        
        if initial_fitness == 0:
            return 100.0 if final_fitness > 0 else 0.0
        
        return ((final_fitness - initial_fitness) / abs(initial_fitness)) * 100


# Utility functions for easier integration
async def evolve_template(template_name: str, goal: str = "improve_success_rate",
                         iterations: int = 50, metadata_manager=None, 
                         templates_dir: str = "templates") -> Dict[str, Any]:
    """
    Convenience function to evolve a template.
    
    Args:
        template_name: Name of template to evolve
        goal: Evolution goal
        iterations: Number of iterations
        metadata_manager: Metadata manager instance
        templates_dir: Templates directory
        
    Returns:
        Evolution results
    """
    evolver = TemplateEvolver(
        template_name=template_name,
        goal=goal,
        metadata_manager=metadata_manager,
        templates_dir=templates_dir
    )
    
    return await evolver.evolve(iterations=iterations)


if __name__ == "__main__":
    # Basic test
    async def test_evolution():
        # This would normally use the actual metadata manager
        from unittest.mock import Mock
        
        mock_metadata = Mock()
        mock_metadata.list_executions.return_value = []
        mock_metadata.redis.get.return_value = None
        
        result = await evolve_template(
            template_name="test-template",
            goal="improve_success_rate",
            iterations=5,
            metadata_manager=mock_metadata
        )
        
        print("Evolution result:", json.dumps(result, indent=2))
    
    asyncio.run(test_evolution())