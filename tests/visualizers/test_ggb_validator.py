"""Tests for GeoGebra command validator fatal-pattern checks."""

from deeptutor.tools.vision.ggb_validator import (
    validate_command,
    validate_ggbscript,
)


class TestTextArity:
    def test_text_with_3_args_is_rejected(self):
        # The fatal pattern from #1324: Text["str", expr, expr]
        command = 'T9=Text["$(a+b)^2=a^2+2ab+b^2$",(a+b)/2,a+b+0.8]'
        result = validate_command(command)
        assert not result.is_valid
        assert any("no 3-argument signature" in e for e in result.errors)

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

    def test_non_text_commands_unaffected(self):
        command = "S1=Segment[E,F]"
        result = validate_command(command)
        assert result.is_valid
        assert result.errors == []


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
    def test_mixed_script_reports_line_number(self):
        script = "\n".join(
            [
                "a=Slider(1,5,0.1)",
                "b=Slider(1,5,0.1)",
                'T9=Text["$(a+b)^2$",(a+b)/2,a+b+0.8]',
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
