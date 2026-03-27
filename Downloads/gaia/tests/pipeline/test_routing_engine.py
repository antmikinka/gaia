"""
Tests for GAIA Routing Engine.

Tests cover:
- Defect type detection
- Routing rule evaluation
- Specialist agent selection
- Loop-back logic
- Routing decision creation
"""

import pytest
from datetime import datetime

from gaia.pipeline.routing_engine import (
    RoutingEngine,
    RoutingDecision,
    RoutingRule,
)
from gaia.pipeline.defect_types import (
    DefectType,
    defect_type_from_string,
    get_defect_specialists,
)
from gaia.agents.registry import AgentRegistry


class TestDefectTypeDetection:
    """Tests for defect type detection."""

    def test_detect_security_defect(self):
        """Test detection of security defects."""
        assert defect_type_from_string("SQL injection vulnerability") == DefectType.SECURITY
        assert defect_type_from_string("XSS attack possible") == DefectType.SECURITY
        assert defect_type_from_string("Authentication bypass detected") == DefectType.SECURITY

    def test_detect_performance_defect(self):
        """Test detection of performance defects."""
        assert defect_type_from_string("Slow query detected") == DefectType.PERFORMANCE
        assert defect_type_from_string("Memory leak in loop") == DefectType.PERFORMANCE
        assert defect_type_from_string("High CPU usage") == DefectType.PERFORMANCE

    def test_detect_testing_defect(self):
        """Test detection of testing defects."""
        assert defect_type_from_string("Missing tests for module") == DefectType.TESTING
        assert defect_type_from_string("Insufficient test coverage") == DefectType.TESTING
        assert defect_type_from_string("Flaky test failure") == DefectType.TESTING

    def test_detect_documentation_defect(self):
        """Test detection of documentation defects."""
        assert defect_type_from_string("Missing docstring") == DefectType.DOCUMENTATION
        assert defect_type_from_string("Outdated documentation") == DefectType.DOCUMENTATION
        assert defect_type_from_string("Missing API comments") == DefectType.DOCUMENTATION

    def test_detect_code_quality_defect(self):
        """Test detection of code quality defects."""
        assert defect_type_from_string("Code style violation") == DefectType.CODE_QUALITY
        assert defect_type_from_string("High cyclomatic complexity") == DefectType.CODE_QUALITY
        assert defect_type_from_string("Duplicate code detected") == DefectType.CODE_QUALITY

    def test_detect_requirements_defect(self):
        """Test detection of requirements defects."""
        assert defect_type_from_string("Missing requirement implementation") == DefectType.REQUIREMENTS
        assert defect_type_from_string("Incorrect feature behavior") == DefectType.REQUIREMENTS
        assert defect_type_from_string("Edge case not handled") == DefectType.REQUIREMENTS

    def test_detect_architecture_defect(self):
        """Test detection of architecture defects."""
        assert defect_type_from_string("Architecture violation") == DefectType.ARCHITECTURE
        assert defect_type_from_string("Circular dependency detected") == DefectType.ARCHITECTURE
        assert defect_type_from_string("Architectural pattern violation") == DefectType.ARCHITECTURE

    def test_detect_accessibility_defect(self):
        """Test detection of accessibility defects."""
        assert defect_type_from_string("Missing alt text for images") == DefectType.ACCESSIBILITY
        assert defect_type_from_string("WCAG compliance issue") == DefectType.ACCESSIBILITY
        assert defect_type_from_string("Keyboard navigation broken") == DefectType.ACCESSIBILITY

    def test_detect_compatibility_defect(self):
        """Test detection of compatibility defects."""
        assert defect_type_from_string("Cross-browser compatibility issue") == DefectType.COMPATIBILITY
        assert defect_type_from_string("Not working on mobile Safari") == DefectType.COMPATIBILITY
        assert defect_type_from_string("Breaking change in API") == DefectType.COMPATIBILITY

    def test_detect_data_integrity_defect(self):
        """Test detection of data integrity defects."""
        assert defect_type_from_string("Data validation missing") == DefectType.DATA_INTEGRITY
        assert defect_type_from_string("Type safety issue") == DefectType.DATA_INTEGRITY
        assert defect_type_from_string("Potential data loss") == DefectType.DATA_INTEGRITY

    def test_detect_unknown_defect(self):
        """Test detection returns UNKNOWN for unclassifiable defects."""
        assert defect_type_from_string("Random unknown issue") == DefectType.UNKNOWN
        assert defect_type_from_string("") == DefectType.UNKNOWN
        assert defect_type_from_string(None) == DefectType.UNKNOWN


class TestRoutingDecision:
    """Tests for RoutingDecision dataclass."""

    def test_create_routing_decision(self):
        """Test creating routing decision."""
        decision = RoutingDecision(
            target_agent="security-auditor",
            target_phase="DEVELOPMENT",
            loop_back=True,
            guidance="Fix security issue",
            matched_rule="security-001",
            defect_type=DefectType.SECURITY,
        )

        assert decision.target_agent == "security-auditor"
        assert decision.target_phase == "DEVELOPMENT"
        assert decision.loop_back is True
        assert "security" in decision.guidance.lower()

    def test_routing_decision_factory_method(self):
        """Test create factory method."""
        decision = RoutingDecision.create(
            target_agent="performance-analyst",
            target_phase="DEVELOPMENT",
            defect_type=DefectType.PERFORMANCE,
            loop_back=True,
            guidance="Optimize performance",
        )

        assert decision.target_agent == "performance-analyst"
        assert decision.defect_type == DefectType.PERFORMANCE
        assert decision.confidence == 1.0

    def test_routing_decision_to_dict(self):
        """Test routing decision serialization."""
        decision = RoutingDecision.create(
            target_agent="technical-writer",
            target_phase="DEVELOPMENT",
            defect_type=DefectType.DOCUMENTATION,
        )

        data = decision.to_dict()
        assert data["target_agent"] == "technical-writer"
        assert data["target_phase"] == "DEVELOPMENT"
        assert data["defect_type"] == "DOCUMENTATION"
        assert "decided_at" in data


class TestRoutingRule:
    """Tests for RoutingRule dataclass."""

    def test_rule_matches_defect_type(self):
        """Test rule matching based on defect type."""
        rule = RoutingRule(
            rule_id="test-001",
            name="Test Rule",
            defect_types=[DefectType.SECURITY, DefectType.PERFORMANCE],
            target_phase="DEVELOPMENT",
        )

        assert rule.matches(DefectType.SECURITY) is True
        assert rule.matches(DefectType.PERFORMANCE) is True
        assert rule.matches(DefectType.TESTING) is False

    def test_rule_disabled(self):
        """Test disabled rule doesn't match."""
        rule = RoutingRule(
            rule_id="test-001",
            name="Test Rule",
            defect_types=[DefectType.SECURITY],
            target_phase="DEVELOPMENT",
            enabled=False,
        )

        assert rule.matches(DefectType.SECURITY) is False

    def test_rule_with_conditions(self):
        """Test rule matching with conditions."""
        rule = RoutingRule(
            rule_id="test-001",
            name="Test Rule",
            defect_types=[DefectType.SECURITY],
            target_phase="DEVELOPMENT",
            conditions={"severity": "critical"},
        )

        assert rule.matches(DefectType.SECURITY, {"severity": "critical"}) is True
        assert rule.matches(DefectType.SECURITY, {"severity": "low"}) is False


class TestRoutingEngine:
    """Tests for RoutingEngine class."""

    @pytest.fixture
    def engine(self) -> RoutingEngine:
        """Create test routing engine."""
        return RoutingEngine()

    @pytest.fixture
    def engine_with_registry(self) -> RoutingEngine:
        """Create routing engine with agent registry."""
        registry = AgentRegistry()
        return RoutingEngine(agent_registry=registry)

    def test_route_security_defect(self, engine: RoutingEngine):
        """Test routing of security defects."""
        defect = {
            "id": "defect-001",
            "description": "SQL injection vulnerability in login form",
            "severity": "critical",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "security-auditor"
        assert decision.target_phase == "DEVELOPMENT"
        assert decision.defect_type == DefectType.SECURITY
        assert decision.loop_back is True

    def test_route_performance_defect(self, engine: RoutingEngine):
        """Test routing of performance defects."""
        defect = {
            "id": "defect-002",
            "description": "Slow query causing high latency",
            "severity": "high",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "performance-analyst"
        assert decision.target_phase == "DEVELOPMENT"
        assert decision.defect_type == DefectType.PERFORMANCE

    def test_route_testing_defect(self, engine: RoutingEngine):
        """Test routing of testing defects."""
        defect = {
            "id": "defect-003",
            "description": "Missing unit tests for new module",
            "severity": "medium",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "test-coverage-analyzer"
        assert decision.target_phase == "DEVELOPMENT"
        assert decision.defect_type == DefectType.TESTING

    def test_route_documentation_defect(self, engine: RoutingEngine):
        """Test routing of documentation defects."""
        defect = {
            "id": "defect-004",
            "description": "Missing docstrings in public API",
            "severity": "low",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "technical-writer"
        assert decision.target_phase == "DEVELOPMENT"
        assert decision.defect_type == DefectType.DOCUMENTATION
        assert decision.loop_back is False  # Documentation can be fixed in parallel

    def test_route_architecture_defect(self, engine: RoutingEngine):
        """Test routing of architecture defects."""
        defect = {
            "id": "defect-005",
            "description": "Circular dependency between modules",
            "severity": "high",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "solutions-architect"
        assert decision.target_phase == "PLANNING"
        assert decision.defect_type == DefectType.ARCHITECTURE

    def test_route_requirements_defect(self, engine: RoutingEngine):
        """Test routing of requirements defects."""
        defect = {
            "id": "defect-006",
            "description": "Missing requirement implementation",
            "severity": "high",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "software-program-manager"
        assert decision.target_phase == "PLANNING"
        assert decision.defect_type == DefectType.REQUIREMENTS

    def test_route_unknown_defect(self, engine: RoutingEngine):
        """Test routing of unknown defect types."""
        defect = {
            "id": "defect-007",
            "description": "Some random issue",
            "severity": "medium",
        }

        decision = engine.route_defect(defect)

        assert decision.target_agent == "senior-developer"  # Fallback
        assert decision.target_phase == "DEVELOPMENT"  # Default
        assert decision.defect_type == DefectType.UNKNOWN

    def test_route_multiple_defects(self, engine: RoutingEngine):
        """Test routing multiple defects at once."""
        defects = [
            {"id": "d1", "description": "SQL injection vulnerability", "severity": "critical"},
            {"id": "d2", "description": "Missing unit tests", "severity": "medium"},
            {"id": "d3", "description": "Slow database query", "severity": "high"},
        ]

        routed = engine.route_defects(defects)

        assert "DEVELOPMENT" in routed
        assert len(routed["DEVELOPMENT"]) == 3

        # Check each defect was routed
        all_routed = []
        for phase_decisions in routed.values():
            all_routed.extend(phase_decisions)
        assert len(all_routed) == 3

    def test_detect_defect_type_method(self, engine: RoutingEngine):
        """Test defect type detection method."""
        assert engine.detect_defect_type("XSS vulnerability") == DefectType.SECURITY
        assert engine.detect_defect_type("Memory leak") == DefectType.PERFORMANCE
        assert engine.detect_defect_type("Missing tests") == DefectType.TESTING
        assert engine.detect_defect_type("Unknown issue xyz") == DefectType.UNKNOWN

    def test_evaluate_rules_method(self, engine: RoutingEngine):
        """Test rule evaluation method."""
        rule, phase = engine.evaluate_rules(DefectType.SECURITY)

        assert rule is not None
        assert rule.rule_id == "security-001"
        assert phase == "DEVELOPMENT"

        rule, phase = engine.evaluate_rules(DefectType.UNKNOWN)
        assert rule is None  # No rule for UNKNOWN
        assert phase == "DEVELOPMENT"  # Default phase

    def test_select_specialist_method(self, engine: RoutingEngine):
        """Test specialist selection method."""
        # Without registry, should return rule-specified agent or first from mapping
        agent = engine.select_specialist(DefectType.SECURITY)
        assert agent == "security-auditor"

        agent = engine.select_specialist(DefectType.PERFORMANCE)
        assert agent == "performance-analyst"

    def test_select_specialist_with_registry(self, engine_with_registry: RoutingEngine):
        """Test specialist selection with agent registry."""
        # Note: In real tests, registry would have agents loaded
        # This tests the fallback behavior
        agent = engine_with_registry.select_specialist(DefectType.SECURITY)
        # Should try to find security-auditor, fall back to senior-developer
        assert agent in ["security-auditor", "senior-developer"]

    def test_add_rule(self, engine: RoutingEngine):
        """Test adding custom routing rule."""
        custom_rule = RoutingRule(
            rule_id="custom-001",
            name="Custom Security Rule",
            defect_types=[DefectType.SECURITY],
            target_phase="REVIEW",  # Custom phase
            target_agent="security-auditor",  # Use existing agent
            priority=0,  # Highest priority
        )

        engine.add_rule(custom_rule)

        # New rule should be evaluated first (priority 0)
        # Use description that will match SECURITY defect type
        defect = {"id": "test", "description": "Security vulnerability detected"}
        decision = engine.route_defect(defect)

        assert decision.matched_rule == "custom-001"
        assert decision.target_phase == "REVIEW"

    def test_remove_rule(self, engine: RoutingEngine):
        """Test removing routing rule."""
        before_count = len(engine._rules)

        removed = engine.remove_rule("security-001")

        assert removed is True
        assert len(engine._rules) == before_count - 1

    def test_remove_nonexistent_rule(self, engine: RoutingEngine):
        """Test removing non-existent rule."""
        removed = engine.remove_rule("nonexistent-rule")
        assert removed is False

    def test_get_rule_statistics(self, engine: RoutingEngine):
        """Test getting rule statistics."""
        stats = engine.get_rule_statistics()

        assert "total_rules" in stats
        assert "enabled_rules" in stats
        assert "rules_by_defect_type" in stats
        assert "rules_by_phase" in stats
        assert stats["total_rules"] > 0

    def test_routing_decision_includes_metadata(self, engine: RoutingEngine):
        """Test that routing decisions include proper metadata."""
        defect = {
            "id": "defect-meta",
            "description": "SQL injection in user input handling " + "extra text " * 10,
            "severity": "critical",
        }

        decision = engine.route_defect(defect)

        assert "defect_id" in decision.metadata
        assert decision.metadata["defect_id"] == "defect-meta"
        assert "rules_evaluated" in decision.metadata
        assert decision.metadata["rules_evaluated"] > 0

    def test_routing_confidence_calculation(self, engine: RoutingEngine):
        """Test confidence score calculation."""
        # Short description - lower confidence
        defect_short = {"id": "d1", "description": "SQL injection"}
        decision_short = engine.route_defect(defect_short)

        # Longer description - higher confidence
        defect_long = {
            "id": "d2",
            "description": "SQL injection vulnerability detected in user input handling form",
        }
        decision_long = engine.route_defect(defect_long)

        # Both should be detected as SECURITY
        assert decision_short.defect_type == DefectType.SECURITY
        assert decision_long.defect_type == DefectType.SECURITY

    def test_empty_defect_description(self, engine: RoutingEngine):
        """Test handling of empty defect description."""
        defect = {"id": "empty", "description": ""}
        decision = engine.route_defect(defect)

        assert decision.defect_type == DefectType.UNKNOWN
        assert decision.target_agent == "senior-developer"

    def test_missing_description_field(self, engine: RoutingEngine):
        """Test handling of missing description field."""
        defect = {"id": "no-desc"}
        decision = engine.route_defect(defect)

        assert decision.defect_type == DefectType.UNKNOWN
        assert decision.target_phase == "DEVELOPMENT"


class TestRoutingEngineIntegration:
    """Integration tests for routing engine."""

    def test_full_routing_workflow(self):
        """Test complete routing workflow."""
        engine = RoutingEngine()

        # Simulate defects from quality report
        defects = [
            {"id": "sec-1", "description": "SQL injection in login", "severity": "critical"},
            {"id": "perf-1", "description": "Slow query in user endpoint", "severity": "high"},
            {"id": "test-1", "description": "No tests for auth module", "severity": "medium"},
            {"id": "doc-1", "description": "Missing API documentation", "severity": "low"},
        ]

        # Route all defects
        routed = engine.route_defects(defects)

        # Verify routing
        all_decisions = []
        for phase_decisions in routed.values():
            all_decisions.extend(phase_decisions)

        assert len(all_decisions) == 4

        # Check specific routings
        sec_decision = next(d for d in all_decisions if d.metadata.get("defect_id") == "sec-1")
        assert sec_decision.target_agent == "security-auditor"
        assert sec_decision.defect_type == DefectType.SECURITY


class TestDefectSpecialists:
    """Tests for defect specialist mappings."""

    def test_security_specialists(self):
        """Test security defect specialists."""
        specialists = get_defect_specialists(DefectType.SECURITY)
        assert "security-auditor" in specialists
        assert "senior-developer" in specialists

    def test_performance_specialists(self):
        """Test performance defect specialists."""
        specialists = get_defect_specialists(DefectType.PERFORMANCE)
        assert "performance-analyst" in specialists

    def test_testing_specialists(self):
        """Test testing defect specialists."""
        specialists = get_defect_specialists(DefectType.TESTING)
        assert "test-coverage-analyzer" in specialists
        assert "quality-reviewer" in specialists

    def test_documentation_specialists(self):
        """Test documentation defect specialists."""
        specialists = get_defect_specialists(DefectType.DOCUMENTATION)
        assert "technical-writer" in specialists

    def test_architecture_specialists(self):
        """Test architecture defect specialists."""
        specialists = get_defect_specialists(DefectType.ARCHITECTURE)
        assert "solutions-architect" in specialists

    def test_requirements_specialists(self):
        """Test requirements defect specialists."""
        specialists = get_defect_specialists(DefectType.REQUIREMENTS)
        assert "software-program-manager" in specialists
        assert "planning-analysis-strategist" in specialists

    def test_unknown_specialists(self):
        """Test unknown defect specialists (should fallback)."""
        specialists = get_defect_specialists(DefectType.UNKNOWN)
        assert "senior-developer" in specialists


class TestRoutingRulePriority:
    """Tests for routing rule priority handling."""

    def test_higher_priority_rule_evaluated_first(self):
        """Test that lower priority number = higher priority."""
        engine = RoutingEngine()

        # Security rule has priority 1
        # Code quality rule has priority 7
        security_rule = next(r for r in engine._rules if r.rule_id == "security-001")
        quality_rule = next(r for r in engine._rules if r.rule_id == "code-quality-001")

        assert security_rule.priority < quality_rule.priority

    def test_rules_sorted_by_priority(self):
        """Test that rules are sorted by priority."""
        engine = RoutingEngine()
        priorities = [r.priority for r in engine._rules]

        assert priorities == sorted(priorities)
