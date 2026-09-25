"""Tests for GeoGebra command validator fatal-pattern checks."""

import json

from deeptutor.tools.vision.ggb_validator import (
    validate_command,
    validate_ggbscript,
)
from deeptutor.visualizers.builtin import bundled_visualizers


class TestTextArity:
    def test_scalar_text_coordinates_are_combined(self):
        # The fatal pattern from #1324: Text["str", expr, expr]
        command = 'T9=Text["$(a+b)^2=a^2+2ab+b^2$",(a+b)/2,a+b+0.8]'
        result = validate_command(command)
        assert not result.is_valid
        assert result.errors == []
        assert result.fixed == ('T9=Text["$(a+b)^2=a^2+2ab+b^2$",((a+b)/2,a+b+0.8)]')
        assert any("Combined scalar" in warning for warning in result.warnings)

    def test_text_with_2_args_passes(self):
        command = 'T1=Text["$a^2$",(a/2,a/2)]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_text_with_4_args_passes(self):
        command = 'T2=Text["$ab$",(a+b/2,a/2),true,true]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_text_with_object_point_and_boolean_passes(self):
        command = 'T1=Text["$a^2$",P,true]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_non_text_commands_unaffected(self):
        command = "S1=Segment[E,F]"
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_text_with_point_and_non_boolean_third_argument_is_rejected(self):
        command = 'T1=Text["$a^2$",(1,2),3]'
        result = validate_command(command)
        assert not result.is_valid
        assert any("Invalid 3-argument Text[] signature" in error for error in result.errors)

    def test_uppercase_point_arguments_are_not_combined(self):
        command = 'T1=Text["label",P,Q]'
        result = validate_command(command)
        # Q could be a named Boolean. Static validation cannot infer its type.
        assert result.is_valid
        assert result.fixed == command

    def test_text_with_five_arguments_is_rejected(self):
        command = 'T1=Text["$a^2$",(1,2),true,true,5]'
        result = validate_command(command)
        assert not result.is_valid
        assert any("one to four arguments, or six" in error for error in result.errors)

    def test_text_with_six_alignment_arguments_passes(self):
        command = 'T1=Text["$a^2$",(1,2),true,true,-1,0]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []

    def test_named_boolean_third_argument_is_preserved(self):
        command = 'T1=Text["label",P,showVariables]'
        result = validate_command(command)
        assert result.is_valid
        assert result.fixed == command


class TestLaTeXBalance:
    def test_unbalanced_dollar_is_rejected(self):
        command = 'T1=Text["$a^2,(a/2,a/2)]'
        result = validate_command(command)
        assert not result.is_valid
        assert len(result.errors) > 0

    def test_balanced_dollar_passes(self):
        command = 'T1=Text["$a^2+b^2$",(a/2,a/2)]'
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []


class TestScriptLevel:
    def test_visualizer_payload_normalizes_repaired_text_command(self):
        visualizer = next(
            plugin for plugin in bundled_visualizers() if plugin.manifest.id == "geogebra"
        )
        payload = json.dumps(
            {
                "app_name": "geometry",
                "commands": [
                    "A=(0,0)",
                    'T9=Text["$(a+b)^2$",(a+b)/2,a+b+0.8]',
                ],
                "view": {"x_min": -1, "x_max": 2, "y_min": -1, "y_max": 2},
            }
        )

        is_valid, normalized, error = visualizer.validator(payload)

        assert is_valid
        assert error == ""
        assert normalized["commands"][-1] == ('T9=Text["$(a+b)^2$",((a+b)/2,a+b+0.8)]')
        assert normalized["validation_warnings"] == [
            "Line 2: Combined scalar x and y arguments into a Text[] point argument"
        ]

    def test_geogebra_prompt_documents_text_signatures(self):
        visualizer = next(
            plugin for plugin in bundled_visualizers() if plugin.manifest.id == "geogebra"
        )
        prompt = visualizer.manifest.prompt

        assert "Text[<object>, <point>, <boolean>]" in prompt
        assert 'Text["$x^2$", ((a+b)/2, a+b+0.8)]' in prompt
        assert 'Text["$x^2$", (a+b)/2, a+b+0.8]' in prompt

    def test_scalar_coordinates_are_repaired_with_line_warning(self):
        script = "\n".join(
            [
                "a=Slider(1,5,0.1)",
                "b=Slider(1,5,0.1)",
                'T9=Text["$(a+b)^2$",(a+b)/2,a+b+0.8]',
            ]
        )
        fixed, warnings, errors = validate_ggbscript(script)
        assert errors == []
        assert 'T9=Text["$(a+b)^2$",((a+b)/2,a+b+0.8)]' in fixed.splitlines()
        assert warnings == [
            "Line 3: Combined scalar x and y arguments into a Text[] point argument"
        ]

    def test_mixed_script_reports_line_number(self):
        script = "\n".join(
            [
                "a=Slider(1,5,0.1)",
                "b=Slider(1,5,0.1)",
                'T9=Text["$(a+b)^2$",(1,2),3]',
            ]
        )
        _, _, errors = validate_ggbscript(script)
        assert len(errors) == 1
        assert errors[0].startswith("Line 3:")

    def test_clean_script_has_no_errors(self):
        script = "\n".join(
            [
                "A=(0,0)",
                "B=(1,1)",
                'T1=Text["$x$",(0.5,0.5)]',
            ]
        )
        _, warnings, errors = validate_ggbscript(script)
        assert errors == []
