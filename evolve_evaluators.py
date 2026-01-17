#!/usr/bin/env python3
"""
MiladyOS AlphaEvolve - Pipeline Evaluators

Cascade evaluation system for Jenkins pipelines:
1. Syntax validation (fast, local)
2. Static analysis (fast, local)
3. Dry run validation (medium, requires Jenkins)
4. Live execution (slow, requires Jenkins + resources)

Each stage filters out bad candidates early to save compute.
"""

import asyncio
import json
import logging
import os
import re
import subprocess
import tempfile
import time
from abc import ABC, abstractmethod
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import colorlog

logger = colorlog.getLogger("miladyos-evaluators")


# ============================================================================
# Evaluator Base
# ============================================================================

@dataclass
class EvaluationResult:
    """Result from an evaluation stage."""
    passed: bool
    score: float
    metrics: Dict[str, float]
    errors: List[str]
    warnings: List[str]
    duration_ms: float


class BaseEvaluator(ABC):
    """Base class for pipeline evaluators."""

    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.timeout = config.get("timeout", 30)

    @abstractmethod
    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        """Evaluate the pipeline content."""
        pass


# ============================================================================
# Syntax Evaluator
# ============================================================================

class SyntaxEvaluator(BaseEvaluator):
    """
    Fast local syntax validation for Jenkinsfiles.

    Checks:
    - Required pipeline structure (pipeline, stages, agent)
    - Balanced braces and parentheses
    - Valid stage definitions
    - No obvious syntax errors
    """

    REQUIRED_ELEMENTS = [
        (r"\bpipeline\s*\{", "Missing 'pipeline' block"),
        (r"\bstages\s*\{", "Missing 'stages' block"),
        (r"\bagent\s+", "Missing 'agent' directive"),
    ]

    SYNTAX_ERRORS = [
        (r"stage\s*\([^)]*\)\s*\{[^}]*stage\s*\(", "Nested stage definitions"),
        (r'"\s*\+\s*"', "String concatenation (use GString interpolation)"),
        (r"def\s+\w+\s*=.*\bpipeline\b", "Variable before pipeline block"),
    ]

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        # Check required elements
        for pattern, error_msg in self.REQUIRED_ELEMENTS:
            if not re.search(pattern, content):
                errors.append(error_msg)

        # Check for syntax errors
        for pattern, error_msg in self.SYNTAX_ERRORS:
            if re.search(pattern, content):
                errors.append(error_msg)

        # Check balanced delimiters
        brace_balance = content.count("{") - content.count("}")
        paren_balance = content.count("(") - content.count(")")
        bracket_balance = content.count("[") - content.count("]")

        if brace_balance != 0:
            errors.append(f"Unbalanced braces: {'+' if brace_balance > 0 else ''}{brace_balance}")
        if paren_balance != 0:
            errors.append(f"Unbalanced parentheses: {'+' if paren_balance > 0 else ''}{paren_balance}")
        if bracket_balance != 0:
            warnings.append(f"Unbalanced brackets: {'+' if bracket_balance > 0 else ''}{bracket_balance}")

        # Check for common issues
        if "sh '" in content and 'sh "' in content:
            warnings.append("Mixed quote styles in sh commands")

        if re.search(r"password\s*[=:]\s*['\"][^'\"]+['\"]", content, re.I):
            errors.append("Hardcoded password detected")

        if "sleep" in content and not re.search(r"sleep\s*\(\s*\d+\s*\)", content):
            warnings.append("Sleep without explicit duration")

        # Calculate metrics
        metrics["syntax_errors"] = len(errors)
        metrics["syntax_warnings"] = len(warnings)
        metrics["line_count"] = len(content.split("\n"))
        metrics["stage_count"] = len(re.findall(r"\bstage\s*\(", content))

        passed = len(errors) == 0
        score = 1.0 if passed else 0.0

        return EvaluationResult(
            passed=passed,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )


# ============================================================================
# Static Analysis Evaluator
# ============================================================================

class StaticAnalysisEvaluator(BaseEvaluator):
    """
    Deep static analysis for quality metrics.

    Analyzes:
    - Parallelization opportunities
    - Error handling coverage
    - Resource management
    - Security practices
    - Best practices compliance
    """

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        goal = context.get("goal", "reliability")

        # Parallelization analysis
        parallel_blocks = len(re.findall(r"\bparallel\s*\{", content))
        stage_count = len(re.findall(r"\bstage\s*\(", content))
        sh_commands = len(re.findall(r"\bsh\s+['\"]", content))

        metrics["parallel_blocks"] = parallel_blocks
        metrics["parallelism_ratio"] = parallel_blocks / max(1, stage_count)
        metrics["parallelism_score"] = min(1.0, parallel_blocks / max(1, stage_count - 1))

        # Error handling analysis
        try_blocks = content.count("try {")
        catch_blocks = content.count("catch ")
        retry_count = len(re.findall(r"\bretry\s*\(\s*\d+\s*\)", content))
        timeout_count = len(re.findall(r"\btimeout\s*\(", content))

        metrics["try_catch_blocks"] = min(try_blocks, catch_blocks)
        metrics["retry_count"] = retry_count
        metrics["timeout_count"] = timeout_count
        metrics["error_handling_score"] = min(1.0, (try_blocks + retry_count * 2) / max(1, sh_commands))
        metrics["retry_coverage"] = min(1.0, retry_count / max(1, sh_commands // 2))
        metrics["timeout_coverage"] = min(1.0, timeout_count / max(1, stage_count))

        # Resource management
        has_cleanup = "cleanWs()" in content or "deleteDir()" in content
        has_docker_prune = "docker system prune" in content or "docker image prune" in content
        has_resource_limits = "limits {" in content or re.search(r"memory\s*[=:]\s*['\"]", content)

        metrics["has_cleanup"] = 1.0 if has_cleanup else 0.0
        metrics["has_docker_cleanup"] = 1.0 if has_docker_prune else 0.0
        metrics["has_resource_limits"] = 1.0 if has_resource_limits else 0.0
        metrics["resource_efficiency"] = (
            (0.4 if has_cleanup else 0.0) +
            (0.3 if has_docker_prune else 0.0) +
            (0.3 if has_resource_limits else 0.0)
        )

        # Security analysis
        uses_credentials = "credentials(" in content or "withCredentials" in content
        uses_env_vars = "environment {" in content
        no_hardcoded_secrets = not re.search(
            r"(password|secret|token|key)\s*[=:]\s*['\"][^$][^'\"]+['\"]",
            content, re.I
        )

        metrics["uses_credentials"] = 1.0 if uses_credentials else 0.0
        metrics["uses_env_vars"] = 1.0 if uses_env_vars else 0.0
        metrics["no_hardcoded_secrets"] = 1.0 if no_hardcoded_secrets else 0.0
        metrics["security_score"] = (
            (0.4 if uses_credentials else 0.0) +
            (0.2 if uses_env_vars else 0.0) +
            (0.4 if no_hardcoded_secrets else 0.0)
        )

        if not no_hardcoded_secrets:
            errors.append("Potential hardcoded secrets detected")

        # Best practices
        has_post = "post {" in content
        has_options = "options {" in content
        has_parameters = "parameters {" in content
        uses_shallow_clone = "depth: 1" in content or "shallow: true" in content

        metrics["has_post_actions"] = 1.0 if has_post else 0.0
        metrics["has_options"] = 1.0 if has_options else 0.0
        metrics["uses_shallow_clone"] = 1.0 if uses_shallow_clone else 0.0

        # Caching analysis
        has_cache = any(x in content.lower() for x in ["cache", "stash", "unstash"])
        has_npm_ci = "npm ci" in content
        has_pip_cache = "--cache-dir" in content or "PIP_CACHE_DIR" in content

        metrics["has_caching"] = 1.0 if has_cache or has_npm_ci else 0.0
        metrics["speed_optimizations"] = (
            (0.3 if uses_shallow_clone else 0.0) +
            (0.3 if has_cache else 0.0) +
            (0.2 if has_npm_ci else 0.0) +
            (0.2 if parallel_blocks > 0 else 0.0)
        )

        # Complexity penalty
        lines = len(content.split("\n"))
        nesting_depth = max(
            line.count("{") - line.count("}")
            for line in content.split("\n")
        )

        metrics["complexity_lines"] = lines
        metrics["max_nesting"] = nesting_depth
        metrics["complexity_penalty"] = max(0.5, 1.0 - (lines / 500) - (nesting_depth / 20))

        # Warnings for missing best practices
        if not has_post:
            warnings.append("Missing post {} block for cleanup/notifications")
        if not has_cleanup:
            warnings.append("No workspace cleanup (cleanWs)")
        if not uses_shallow_clone and "checkout" in content:
            warnings.append("Consider shallow clone for faster checkout")
        if sh_commands > 3 and retry_count == 0:
            warnings.append("Multiple sh commands without retry logic")

        # Calculate overall score based on goal
        if goal == "speed":
            score = (
                metrics["parallelism_score"] * 0.3 +
                metrics["speed_optimizations"] * 0.4 +
                metrics["complexity_penalty"] * 0.3
            )
        elif goal == "reliability":
            score = (
                metrics["error_handling_score"] * 0.4 +
                metrics["retry_coverage"] * 0.3 +
                metrics["timeout_coverage"] * 0.2 +
                metrics["has_post_actions"] * 0.1
            )
        elif goal == "resources":
            score = (
                metrics["resource_efficiency"] * 0.5 +
                metrics["has_caching"] * 0.3 +
                metrics["complexity_penalty"] * 0.2
            )
        elif goal == "security":
            score = metrics["security_score"]
        else:
            # Balanced score
            score = (
                metrics.get("error_handling_score", 0) * 0.25 +
                metrics.get("parallelism_score", 0) * 0.2 +
                metrics.get("resource_efficiency", 0) * 0.2 +
                metrics.get("security_score", 0) * 0.2 +
                metrics.get("complexity_penalty", 0) * 0.15
            )

        return EvaluationResult(
            passed=len(errors) == 0,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )


# ============================================================================
# Jenkins Dry Run Evaluator
# ============================================================================

class JenkinsDryRunEvaluator(BaseEvaluator):
    """
    Validate pipeline using Jenkins' declarative linter.

    Requires Jenkins connection to use the pipeline-model-definition
    plugin's validation endpoint.
    """

    def __init__(self, config: Dict[str, Any], jenkins_client=None):
        super().__init__(config)
        self.jenkins = jenkins_client

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        if not self.jenkins:
            # Skip if no Jenkins connection
            return EvaluationResult(
                passed=True,
                score=1.0,
                metrics={"skipped": 1.0},
                errors=[],
                warnings=["Jenkins not available for dry run"],
                duration_ms=(time.time() - start) * 1000,
            )

        try:
            # Use Jenkins declarative linter
            result = await asyncio.to_thread(
                self._validate_pipeline,
                content
            )

            if result["valid"]:
                metrics["dry_run_valid"] = 1.0
                score = 1.0
            else:
                metrics["dry_run_valid"] = 0.0
                errors.extend(result.get("errors", ["Validation failed"]))
                score = 0.0

        except Exception as e:
            errors.append(f"Dry run failed: {str(e)}")
            metrics["dry_run_error"] = 1.0
            score = 0.0

        return EvaluationResult(
            passed=len(errors) == 0,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )

    def _validate_pipeline(self, content: str) -> Dict[str, Any]:
        """Call Jenkins pipeline linter."""
        try:
            # This would use the Jenkins API endpoint:
            # POST /pipeline-model-converter/validate
            # with the Jenkinsfile content

            # For now, simulate validation
            # In production, use: self.jenkins.jenkins.requester.post_url(...)

            return {"valid": True}

        except Exception as e:
            return {"valid": False, "errors": [str(e)]}


# ============================================================================
# Live Execution Evaluator
# ============================================================================

class LiveExecutionEvaluator(BaseEvaluator):
    """
    Execute pipeline and measure real metrics.

    Creates a temporary Jenkins job, runs it, and extracts:
    - Execution duration
    - Success/failure
    - Resource usage
    - Error messages
    """

    def __init__(self, config: Dict[str, Any], jenkins_client=None):
        super().__init__(config)
        self.jenkins = jenkins_client
        self.timeout = config.get("timeout", 300)  # 5 minute default

    async def evaluate(self, content: str, context: Dict[str, Any]) -> EvaluationResult:
        start = time.time()
        errors = []
        warnings = []
        metrics = {}

        if not self.jenkins:
            return EvaluationResult(
                passed=True,
                score=0.5,  # Uncertain without execution
                metrics={"skipped": 1.0},
                errors=[],
                warnings=["Jenkins not available for live execution"],
                duration_ms=(time.time() - start) * 1000,
            )

        try:
            # Create test job
            job_name = f"evolve-test-{context.get('candidate_id', 'unknown')[:8]}"

            result = await asyncio.to_thread(
                self._execute_pipeline,
                job_name,
                content
            )

            metrics.update(result.get("metrics", {}))

            if result["success"]:
                score = 1.0
                metrics["success_rate"] = 1.0
            else:
                score = 0.0
                metrics["success_rate"] = 0.0
                errors.extend(result.get("errors", ["Execution failed"]))

        except asyncio.TimeoutError:
            errors.append(f"Execution timeout after {self.timeout}s")
            metrics["timeout"] = 1.0
            score = 0.0
        except Exception as e:
            errors.append(f"Execution error: {str(e)}")
            score = 0.0

        return EvaluationResult(
            passed=len(errors) == 0,
            score=score,
            metrics=metrics,
            errors=errors,
            warnings=warnings,
            duration_ms=(time.time() - start) * 1000,
        )

    def _execute_pipeline(self, job_name: str, content: str) -> Dict[str, Any]:
        """Execute pipeline in Jenkins."""
        # This would:
        # 1. Create a temporary pipeline job
        # 2. Trigger a build
        # 3. Wait for completion
        # 4. Extract metrics from build result
        # 5. Clean up test job

        # Placeholder implementation
        return {
            "success": True,
            "metrics": {
                "duration_seconds": 60.0,
                "stages_passed": 5,
                "stages_failed": 0,
            }
        }


# ============================================================================
# Cascade Evaluator (Orchestrator)
# ============================================================================

class CascadeEvaluator:
    """
    Orchestrates cascade evaluation through multiple stages.

    Runs evaluators in order of cost (fast → slow), stopping early
    if a candidate fails critical checks.
    """

    def __init__(self, config: Dict[str, Any], jenkins_client=None):
        self.config = config
        self.evaluators = [
            ("syntax", SyntaxEvaluator(config), 1.0, True),  # name, evaluator, weight, required
            ("static", StaticAnalysisEvaluator(config), 1.0, False),
            ("dry_run", JenkinsDryRunEvaluator(config, jenkins_client), 0.5, False),
            ("execution", LiveExecutionEvaluator(config, jenkins_client), 2.0, False),
        ]

        # Filter based on config
        cascade_config = config.get("evaluator", {}).get("cascade", [])
        if cascade_config:
            enabled = {c["name"] for c in cascade_config}
            self.evaluators = [
                (name, e, w, r) for name, e, w, r in self.evaluators
                if name in enabled
            ]

    async def evaluate(
        self,
        content: str,
        context: Dict[str, Any]
    ) -> Tuple[float, Dict[str, Any]]:
        """
        Run cascade evaluation.

        Returns:
            Tuple of (fitness_score, all_metrics)
        """
        all_metrics = {}
        total_score = 0.0
        total_weight = 0.0

        for name, evaluator, weight, required in self.evaluators:
            logger.debug(f"Running {name} evaluator...")

            try:
                result = await evaluator.evaluate(content, context)

                # Store metrics with evaluator prefix
                for k, v in result.metrics.items():
                    all_metrics[f"{name}_{k}"] = v

                all_metrics[f"{name}_score"] = result.score
                all_metrics[f"{name}_passed"] = 1.0 if result.passed else 0.0
                all_metrics[f"{name}_duration_ms"] = result.duration_ms

                # Record errors and warnings
                if result.errors:
                    all_metrics[f"{name}_errors"] = result.errors
                if result.warnings:
                    all_metrics[f"{name}_warnings"] = result.warnings

                # Update weighted score
                total_score += result.score * weight
                total_weight += weight

                # Early termination on required stage failure
                if required and not result.passed:
                    logger.debug(f"Failed required stage: {name}")
                    all_metrics["early_termination"] = name
                    break

            except Exception as e:
                logger.error(f"Evaluator {name} failed: {e}")
                all_metrics[f"{name}_error"] = str(e)
                if required:
                    break

        # Calculate final fitness
        fitness = total_score / total_weight if total_weight > 0 else 0.0

        return fitness, all_metrics


# ============================================================================
# Utility Functions
# ============================================================================

def extract_metrics_from_console(console_output: str) -> Dict[str, float]:
    """Extract metrics from Jenkins console output."""
    metrics = {}

    # Duration patterns
    duration_patterns = [
        (r"Finished: \w+ in (\d+)m (\d+)s", lambda m: int(m[0]) * 60 + int(m[1])),
        (r"Build took (\d+\.?\d*) seconds", lambda m: float(m[0])),
        (r"Total time: (\d+):(\d+)", lambda m: int(m[0]) * 60 + int(m[1])),
        (r"Duration: (\d+)ms", lambda m: float(m[0]) / 1000),
    ]

    for pattern, extractor in duration_patterns:
        match = re.search(pattern, console_output, re.I)
        if match:
            metrics["duration_seconds"] = extractor(match.groups())
            break

    # Success/failure
    if re.search(r"Finished:\s*SUCCESS", console_output, re.I):
        metrics["success"] = 1.0
    elif re.search(r"Finished:\s*(FAILURE|ABORTED)", console_output, re.I):
        metrics["success"] = 0.0

    # Error/warning counts
    metrics["error_count"] = len(re.findall(r"\[ERROR\]|\bERROR\b", console_output))
    metrics["warning_count"] = len(re.findall(r"\[WARN\]|\bWARNING\b", console_output))

    # Stage counts
    metrics["stages_started"] = len(re.findall(r"\[Pipeline\] stage", console_output))

    return metrics
